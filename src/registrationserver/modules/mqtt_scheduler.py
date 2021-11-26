"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import time

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.config import ismqtt_config, mqtt_config
from registrationserver.helpers import get_key, short_id
from registrationserver.logger import logger
from registrationserver.modules import ismqtt_messages
from registrationserver.modules.messages import RETURN_MESSAGES
from thespian.actors import Actor, ActorExitRequest

logger.debug("%s -> %s", __package__, __file__)


class MqttSchedulerActor(Actor):
    """Actor interacting with a new device"""

    ACCEPTED_COMMANDS = {
        "ADD": "_add",
        "REMOVE": "_remove",
    }
    ACCEPTED_RETURNS = {
        "SEND": "_send_to_rs",
    }
    MAX_RESERVE_TIME = 300

    @overrides
    def __init__(self):
        """
        * Initialize variables
        * Connect to MQTT broker
        * Start MQTT loop
        """
        super().__init__()
        self.cluster = {}
        self.reservations = {}
        self.ungr_disconn = 2
        self.is_connected = False
        self.mid = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check
        # Start MQTT client
        self.is_id = ismqtt_config["IS_ID"]
        self.mqttc = MQTT.Client()
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.is_meta = ismqtt_messages.InstrumentServerMeta(
            state=0,
            host=self.is_id,
            description=ismqtt_config["DESCRIPTION"],
            place=ismqtt_config["PLACE"],
            latitude=ismqtt_config["LATITUDE"],
            longitude=ismqtt_config["LONGITUDE"],
            height=ismqtt_config["HEIGHT"],
        )
        self.mqttc.will_set(
            retain=True,
            topic=f"{self.is_id}/meta",
            payload=ismqtt_messages.get_is_meta(self.is_meta),
        )
        mqtt_broker = mqtt_config["MQTT_BROKER"]
        port = mqtt_config["PORT"]
        logger.info("Using MQTT broker %s with port %d", mqtt_broker, port)
        self.mqttc.connect(mqtt_broker, port=port)
        self.mqttc.loop_start()

    @overrides
    def receiveMessage(self, msg, sender):
        """Handles received Actor messages / verification of the message format"""
        if isinstance(msg, dict):
            logger.debug("Msg: %s, Sender: %s", msg, sender)
            return_key = msg.get("RETURN", None)
            cmd_key = msg.get("CMD", None)
            if ((return_key is None) and (cmd_key is None)) or (
                (return_key is not None) and (cmd_key is not None)
            ):
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_MESSAGE"])
                return
            if cmd_key is not None:
                cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
                if cmd_function is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.",
                        msg,
                        sender,
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                    )
                    return
                if getattr(self, cmd_function, None) is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.",
                        msg,
                        sender,
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                    )
                    return
                getattr(self, cmd_function)(msg, sender)
            elif return_key is not None:
                return_function = self.ACCEPTED_RETURNS.get(return_key, None)
                if return_function is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                if getattr(self, return_function, None) is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                getattr(self, return_function)(msg, sender)
        else:
            if isinstance(msg, ActorExitRequest):
                self._kill(msg, sender)
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

    def _add(self, msg, sender):
        """Handler for actor messages with command 'ADD'

        Adds a new instrument to the list of available instruments."""
        instr_id = msg["PAR"]["INSTR_ID"]
        self.cluster[instr_id] = sender
        logger.debug(
            "[ADD] %s added to cluster. Complete list is now %s", instr_id, self.cluster
        )
        ismqtt_messages.add_instr(
            client=self.mqttc, is_id=self.is_id, instr_id=instr_id
        )

    def _remove(self, msg, _sender):
        """Handler for actor messages with command 'REMOVE'

        Removes an instrument from the list of available instruments."""
        instr_id = msg["PAR"]["INSTR_ID"]
        self.cluster.pop(instr_id, None)
        logger.debug(
            "[REMOVE] %s removed from cluster. Complete list is now %s",
            instr_id,
            self.cluster,
        )
        ismqtt_messages.del_instr(
            client=self.mqttc, is_id=self.is_id, instr_id=instr_id
        )

    def _kill(self, _msg, _sender):
        ismqtt_messages.del_is(
            client=self.mqttc, is_id=self.is_id, is_meta=self.is_meta._replace(state=0)
        )
        self._disconnect()
        time.sleep(1)

    def _unsubscribe(self, topics: list) -> bool:
        logger.info("Unsubscribe topic %s", topics)
        if not self.is_connected:
            logger.error("[Unsubscribe] failed, not connected to broker")
            return False
        return_code, self.mid["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topics)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Unsubscribe] failed; result code is: %s", return_code)
            return False
        logger.info("[Unsubscribe] from %s successful", topics)
        return True

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.debug("Disconnect from MQTT broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn in [0, 1]:
            self.ungr_disconn = 2
            logger.debug("Already disconnected")
        self.mqttc.loop_stop()
        logger.debug("Disconnected gracefully")

    def on_connect(self, _client, _userdata, _flags, result_code):
        """Will be carried out when the client connected to the MQTT broker."""
        if result_code == 0:
            self.is_connected = True
            logger.debug(
                "[CONNECT] IS ID %s connected with result code %s.",
                self.is_id,
                result_code,
            )
            self.mqttc.publish(
                retain=True,
                topic=f"{self.is_id}/meta",
                payload=ismqtt_messages.get_is_meta(self.is_meta._replace(state=2)),
            )
        else:
            self.is_connected = False
            logger.error(
                "[CONNECT] Connection to MQTT broker failed with %s",
                result_code,
            )

    def on_disconnect(self, _client, _userdata, result_code):
        """Will be carried out when the client disconnected from the MQTT broker."""
        logger.info("Disconnected from MQTT broker")
        if result_code >= 1:
            logger.warning(
                "Ungraceful disconnect from MQTT broker (%s). Trying to reconnect.",
                result_code,
            )
            # There is no need to do anything.
            # With loop_start() in place, re-connections will be handled automatically.
        else:
            self.ungr_disconn = 0
            logger.debug("Gracefully disconnected from MQTT broker.")
        self.is_connected = False

    def on_message(self, _client, _userdata, message):
        """
        Event handler for after a MQTT message was received on a subscribed topic.
        This could be a control or a cmd message.
        """
        logger.debug("%s(%s)", message.topic, len(message.topic))
        if message.payload is None:
            logger.error("The payload is none")
        else:
            if (
                len(message.topic) > len("cmd") + len(self.is_id) + 2
                and message.topic[-len("cmd") :] == "cmd"
            ):
                instrument_id = message.topic[: -len("cmd") - 1][len(self.is_id) + 1 :]
                for instr_id in self.cluster:
                    if instr_id == instrument_id:
                        if self.reservations.get(instr_id):
                            old = self.reservations[instr_id]
                            self.reservations[instr_id] = ismqtt_messages.Reservation(
                                active=old.active,
                                app=old.app,
                                host=old.host,
                                timestamp=time.time(),
                                user=old.user,
                            )
                            self.process_cmd(message, instr_id)
                # TODO: If code gets here, then the instrument got disconnected
                return
            if (
                len(message.topic) > len("control") + len(self.is_id) + 2
                and message.topic[-len("control") :] == "control"
            ):
                instrument_id = message.topic[: -len("control") - 1][
                    len(self.is_id) + 1 :
                ]
                for instr_id in self.cluster:
                    if instr_id == instrument_id:
                        self.process_control(message, instr_id)

    def process_cmd(self, msg, instr_id):
        """
        Sub-event handler for after a MQTT message was received on a subscribed
        topic this is specific for processing raw SARAD frames
        """
        cmd = msg.payload
        logger.debug("Forward command %s to device actor", cmd)
        cmd_msg = {"CMD": "SEND", "PAR": {"DATA": cmd, "HOST": "localhost"}}
        self.send(self.cluster[instr_id], cmd_msg)

    def _send_to_rs(self, msg, sender):
        """Handler for actor messages returning from 'SEND" command

        Forward the payload received from device_actor via MQTT."""
        reply = msg["RESULT"]["DATA"]
        instr_id = get_key(sender, self.cluster)
        self.mqttc.publish(f"{self.is_id}/{instr_id}/msg", reply)

    def process_control(self, msg, instr_id):
        """
        Sub-Event Handler for after a mqtt message was received on a
        subscribed topic this is specific for processing control messages
        """
        logger.debug(msg.payload)
        control = ismqtt_messages.get_instr_control(msg)
        logger.debug(control)
        if control.ctype == ismqtt_messages.ControlType.RESERVE:
            self.process_reserve(instr_id, control)
        if control.ctype == ismqtt_messages.ControlType.FREE:
            try:
                self.process_free(instr_id, control)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to handle FREE comand")

    def process_reserve(self, instr_id, control):
        """Sub event handler that will be called from the on_message event handler, when a MQTT
        control message with a 'reserve' request was received for a specific instrument
        ID."""
        logger.debug(
            "[RESERVE] client=%s, instrument=%s, control=%s",
            self.mqttc,
            instr_id,
            control,
        )
        success = False

        if not success and not self.reservations.get(instr_id, None):
            success = True

        if not success and (
            self.reservations[instr_id].host == control.data.host
            and self.reservations[instr_id].app == control.data.app
            and self.reservations[instr_id].user == control.data.user
        ):
            success = True

        if (
            not success
            and control.data.timestamp - self.reservations[instr_id].timestamp
            > self.MAX_RESERVE_TIME
        ):
            success = True

        if success:
            self.reservations[instr_id] = ismqtt_messages.Reservation(
                active=True,
                app=control.data.app,
                host=control.data.host,
                timestamp=control.data.timestamp,
                user=control.data.user,
            )

        self.mqttc.publish(
            topic=f"{self.is_id}/{instr_id}/reservation",
            payload=ismqtt_messages.get_instr_reservation(self.reservations[instr_id]),
        )  # static result

    def process_free(self, instr_id, control):
        """Sub event handler that will be called from the on_message event handler, when a MQTT
        control message with a 'free' request was received for a specific instrument
        ID."""
        logger.debug(
            "[FREE] client=%s, instr_id=%s, control=%s",
            self.mqttc,
            instr_id,
            control,
        )
        success = False

        if not success and self.reservations.get(instr_id, None) is None:
            logger.debug(
                "[FREE] Instrument is not in the list of reserved instruments."
            )
            success = True

        if not success and (
            self.reservations[instr_id].host == control.data.host
            and self.reservations[instr_id].app == control.data.app
            and self.reservations[instr_id].user == control.data.user
        ):
            success = True

        if not success and (
            control.data.timestamp - self.reservations[instr_id].timestamp
            > self.MAX_RESERVE_TIME
        ):
            success = True

        if success:
            self.reservations[instr_id] = None

        self.mqttc.publish(
            topic=f"{self.is_id}/{instr_id}/reservation",
            payload=ismqtt_messages.get_instr_reservation(
                ismqtt_messages.Reservation(active=False, timestamp=time.time())
            ),
        )
