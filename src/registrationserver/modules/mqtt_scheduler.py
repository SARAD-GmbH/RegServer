"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import json
import os
import ssl
import threading
import time
from datetime import datetime

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.config import ismqtt_config, mqtt_config
from registrationserver.helpers import get_key
from registrationserver.logger import logger
from registrationserver.modules import ismqtt_messages
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.shutdown import system_shutdown
from thespian.actors import Actor, ActorExitRequest, PoisonMessage

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
        self.lock = threading.Lock()
        self.cluster = {}  # {instr_id: actor_address}
        self.instr_meta = {}  # {instr_id: {<meta>}}
        self.reservations = {}  # {instr_id: <reservation object>}
        # cmd_id to check the correct order of messages
        self.cmd_ids = {}  # {instr_id: <command id>}
        self.ungr_disconn = 2
        self.is_connected = False
        self.msg_id = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }
        # Start MQTT client
        self.is_id = ismqtt_config["IS_ID"]
        self._subscriptions = {}
        self.mqttc = MQTT.Client()
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.message_callback_add("+/+/control", self.on_control)
        self.mqttc.message_callback_add("+/+/cmd", self.on_cmd)
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
        self._connect(mqtt_broker, port)
        self.mqttc.loop_start()

    def _connect(self, mqtt_broker, port):
        success = False
        retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)

        while not success and self.ungr_disconn > 0:
            try:
                logger.info(
                    "Attempting to connect to broker %s: %s",
                    mqtt_broker,
                    port,
                )
                if mqtt_config["TLS_USE_TLS"] and self.mqttc._ssl_context is None:
                    ca_certs = os.path.expanduser(mqtt_config["TLS_CA_FILE"])
                    certfile = os.path.expanduser(mqtt_config["TLS_CERT_FILE"])
                    keyfile = os.path.expanduser(mqtt_config["TLS_KEY_FILE"])
                    logger.info(
                        "Setting up TLS: %s | %s | %s", ca_certs, certfile, keyfile
                    )
                    self.mqttc.tls_set(
                        ca_certs=ca_certs,
                        certfile=certfile,
                        keyfile=keyfile,
                        cert_reqs=ssl.CERT_REQUIRED,
                    )
                self.mqttc.connect(mqtt_broker, port=port)
                success = True
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("Could not connect to Broker, retrying...: %s", exception)
                time.sleep(retry_interval)

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
            if isinstance(msg, PoisonMessage):
                logger.critical("PoisonMessage --> System shutdown.")
                system_shutdown()
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            system_shutdown()
            return

    def _add(self, msg, sender):
        """Handler for actor messages with command 'ADD'

        Adds a new instrument to the list of available instruments."""
        with self.lock:
            instr_id = msg["PAR"]["INSTR_ID"]
            device_status = msg["PAR"]["DEVICE_STATUS"]
            self.cluster[instr_id] = sender
            logger.debug(
                "[ADD] %s added to cluster. Complete list is now %s",
                instr_id,
                self.cluster,
            )
            new_subscriptions = [
                (f"{self.is_id}/{instr_id}/control", 0),
                (f"{self.is_id}/{instr_id}/cmd", 0),
            ]
            self.mqttc.subscribe(new_subscriptions)
            for (topic, qos) in new_subscriptions:
                self._subscriptions[topic] = qos
            identification = device_status["Identification"]
            message = {"State": 2, "Identification": identification}
            self.mqttc.publish(
                topic=f"{self.is_id}/{instr_id}/meta",
                payload=json.dumps(message),
                retain=True,
            )
            self.instr_meta[instr_id] = identification

    def _remove(self, msg, _sender):
        """Handler for actor messages with command 'REMOVE'

        Removes an instrument from the list of available instruments."""
        with self.lock:
            instr_id = msg["PAR"]["INSTR_ID"]
            self.cluster.pop(instr_id, None)
            self.instr_meta.pop(instr_id, None)
            self.reservations.pop(instr_id, None)
            logger.debug(
                "[REMOVE] %s removed from cluster. Complete list is now %s",
                instr_id,
                self.cluster,
            )
            gone_subscriptions = [
                f"{self.is_id}/{instr_id}/control",
                f"{self.is_id}/{instr_id}/cmd",
            ]
            self.mqttc.unsubscribe(gone_subscriptions)
            for topic in gone_subscriptions:
                self._subscriptions.pop(topic)
            self.mqttc.publish(
                retain=True,
                topic=f"{self.is_id}/{instr_id}/meta",
                payload=json.dumps({"State": 0}),
            )

    def _kill(self, _msg, _sender):
        self.mqttc.unsubscribe(topic="+")
        self.mqttc.publish(
            retain=True, topic=f"{self.is_id}/meta", payload=json.dumps({"State": 0})
        )
        self._disconnect()
        time.sleep(1)

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
            for topic, qos in self._subscriptions.items():
                logger.debug("Restore subscription to %s", topic)
                self.mqttc.subscribe(topic, qos)
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

    def on_control(self, _client, _userdata, message):
        """Event handler for all MQTT messages with control topic."""
        with self.lock:
            logger.debug("[on_control] %s: %s", message.topic, message.payload)
            instrument_id = message.topic[: -len("control") - 1][len(self.is_id) + 1 :]
            if instrument_id in self.cluster:
                old_control = self.reservations.get(instrument_id)
                control = ismqtt_messages.get_instr_control(message, old_control)
                logger.debug("Control object: %s", control)
                if control.ctype == ismqtt_messages.ControlType.RESERVE:
                    self.process_reserve(instrument_id, control)
                if control.ctype == ismqtt_messages.ControlType.FREE:
                    self.process_free(instrument_id)
                    logger.debug(
                        "[FREE] client=%s, instr_id=%s, control=%s",
                        self.mqttc,
                        instrument_id,
                        control,
                    )
            else:
                logger.error(
                    "[on_control] The requested instrument %s is not connected",
                    instrument_id,
                )

    def on_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic."""
        with self.lock:
            logger.debug("[on_cmd] %s: %s", message.topic, message.payload)
            instr_id = message.topic[: -len("cmd") - 1][len(self.is_id) + 1 :]
            self.cmd_ids[instr_id] = message.payload[0]
            cmd = message.payload[1:]
            device_actor = self.cluster.get(instr_id)
            if device_actor is not None:
                logger.debug("Forward command %s to device actor %s", cmd, device_actor)
                cmd_msg = {
                    "CMD": "SEND",
                    "PAR": {"DATA": cmd, "HOST": "localhost"},
                }
                self.send(device_actor, cmd_msg)

    def on_message(self, _client, _userdata, message):
        """
        Event handler for after a MQTT message was received on a subscribed topic.
        This will catch only remaining topics that are not control or cmd messages.
        """
        logger.error("%s(%s): %s", message.topic, len(message.topic), message.payload)

    def _send_to_rs(self, msg, sender):
        """Handler for actor messages returning from 'SEND" command

        Forward the payload received from device_actor via MQTT."""
        instr_id = get_key(sender, self.cluster)
        reply = bytes([self.cmd_ids[instr_id]]) + msg["RESULT"]["DATA"]
        self.mqttc.publish(f"{self.is_id}/{instr_id}/msg", reply)

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
            reservation = ismqtt_messages.Reservation(
                active=True,
                app=control.data.app,
                host=control.data.host,
                timestamp=control.data.timestamp,
                user=control.data.user,
            )
            self.reservations[instr_id] = reservation
            reservation_json = ismqtt_messages.get_instr_reservation(reservation)
            topic = f"{self.is_id}/{instr_id}/reservation"
            logger.debug("Publish %s on %s", reservation_json, topic)
            self.mqttc.publish(topic=topic, payload=reservation_json, retain=True)

    def process_free(self, instr_id):
        """Sub event handler that will be called from the on_message event handler, when a MQTT
        control message with a 'free' request was received for a specific instrument
        ID."""
        if self.reservations.get(instr_id) is None:
            logger.debug(
                "[FREE] Instrument is not in the list of reserved instruments."
            )
            return
        reservation = json.loads(
            ismqtt_messages.get_instr_reservation(self.reservations[instr_id])
        )
        reservation["Active"] = False
        reservation["Timestamp"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self.reservations[instr_id] = None
        self.mqttc.publish(
            topic=f"{self.is_id}/{instr_id}/reservation",
            payload=json.dumps(reservation),
            retain=True,
        )
