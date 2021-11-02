"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import datetime
import json
import time

import paho.mqtt.client as MQTT  # type: ignore
import registrationserver.modules.ismqtt_messages as ismqtt_messages
from overrides import overrides  # type: ignore
from registrationserver.config import config, ismqtt_config, mqtt_config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from thespian.actors import Actor, ActorExitRequest

logger.debug("%s -> %s", __package__, __file__)


class MqttSchedulerActor(Actor):
    """Actor interacting with a new device"""

    ACCEPTED_COMMANDS = {
        "ADD": "_add",
        "REMOVE": "_remove",
        "SEND": "_send",
    }
    ACCEPTED_RETURNS = {
        "SEND": "_send_to_app",
    }
    ALLOWED_SYS_OPTIONS = {
        "CTRL": "/control",
        "RESERVE": "/reservation",
        "CMD": "/cmd",
        "MSG": "/msg",
        "META": "/meta",
    }
    MAX_RESERVE_TIME = 300

    @overrides
    def __init__(self):
        """
        *"""
        super().__init__()
        self.allowed_sys_topics = {
            "CTRL": "",
            "RESERVE": "",
            "CMD": "",
            "MSG": "",
            "META": "",
        }
        self.state = {
            "RESERVE": {
                "Pending": False,
                # if there be a reply to wait for, then it should be true
                "Active": None,
                # store the reservation status
            },
            "SEND": {
                "Pending": False,
                # if there be a reply to wait for, then it should be true
                "CMD_ID": None,
                # store the CMD ID
                "Reply": None,
                "Sender": None,
                # store the address of the sender
            },
        }
        self.test_cnt = 0
        logger.debug("test_cnt = %s", self.test_cnt)
        self.cmd_id = 0
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
        disconnect = ismqtt_messages.get_is_meta(
            ismqtt_messages.InstrumentServerMeta(
                state=0,
                host=self.is_id,
                description=ismqtt_config["DESCRIPTION"],
                place=ismqtt_config["PLACE"],
                latitude=ismqtt_config["LATITUDE"],
                longitude=ismqtt_config["LONGITUDE"],
                height=ismqtt_config["HEIGHT"],
            ),
        )
        self.mqttc.will_set(
            retain=True,
            topic=f"{self.is_id}/meta",
            payload=disconnect,
        )
        mqtt_broker = mqtt_config["MQTT_BROKER"]
        port = mqtt_config["PORT"]
        logger.info("Using MQTT broker %s with port %d", mqtt_broker, port)
        self.mqttc.connect(mqtt_broker, port=port)
        self.mqttc.subscribe(f"{self.is_id}/+/meta")
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

    def _send(self, message: dict, sender) -> None:
        if message is None:
            logger.error("[SEND] no contents to send for actor %s", self.globalName)
            return
        data = message.get("PAR", None).get("DATA", None)
        if (data is None) or (not isinstance(data, bytes)):
            logger.error(
                "[SEND] no data to send for actor %s or the data are not bytes",
                self.globalName,
            )
            return
        logger.debug("To send: %s", data)
        logger.debug("CMD ID is: %s", self.cmd_id)
        qos = message.get("PAR", None).get("qos", None)
        if qos is None:
            qos = 0
        self.state["SEND"]["Pending"] = True
        self.test_cnt = self.test_cnt + 1
        logger.debug("test_cnt = %s", self.test_cnt)
        self.state["SEND"]["CMD_ID"] = bytes([self.cmd_id])
        logger.debug("CMD ID is: %s", self.state["SEND"]["CMD_ID"])
        self.state["SEND"]["Sender"] = sender
        _msg = {
            "topic": self.allowed_sys_topics["CMD"],
            "payload": bytes([self.cmd_id]) + data,
            "qos": qos,
        }
        _re = self._publish(_msg)
        if self.cmd_id == 255:
            self.cmd_id = 0
        else:
            self.cmd_id = self.cmd_id + 1
        if not _re:
            logger.error(
                "Failed to publish message with ID %s in topic %s",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.state["SEND"]["Pending"] = False
            self.test_cnt = self.test_cnt + 1
            logger.debug("test_cnt = %s", self.test_cnt)
            self.state["SEND"]["CMD_ID"] = None
            return
        logger.debug("[SEND] send status is %s", self.state["SEND"]["Pending"])

    @overrides
    def _free(self, message, sender) -> None:
        logger.debug("Free-Request")
        if message is None:
            logger.critical("Actor message is None. This schould never happen.")
            return
        _msg = {
            "topic": self.allowed_sys_topics["CTRL"],
            "payload": json.dumps({"Req": "free"}),
            "qos": 0,
        }
        _re = self._publish(_msg)
        if not _re:
            self.send(
                sender,
                {
                    "RETURN": "FREE",
                    "ERROR_CODE": RETURN_MESSAGES["PUBLISH"]["ERROR_CODE"],
                },
            )
            return
        logger.info(
            "[Free] Unsubscribe MQTT actor %s from 'reserve' and 'message' topics",
            self.globalName,
        )
        topics = [self.allowed_sys_topics["RESERVE"], self.allowed_sys_topics["MSG"]]
        if not self._unsubscribe(topics):
            self.send(
                sender,
                {
                    "RETURN": "FREE",
                    "ERROR_CODE": RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
                },
            )
            return

    def _kill(self, _message: dict, _sender):
        self._unsubscribe(["+"])
        self._disconnect()
        time.sleep(1)

    def _parse(self, message: dict) -> None:
        topic = message["topic"]
        payload = message["payload"]
        if topic == self.allowed_sys_topics["RESERVE"]:
            if self.state["RESERVE"]["Pending"]:
                instr_status = json.loads(payload).get("Active", None)
                app = json.loads(payload).get("App", None)
                host = json.loads(payload).get("Host", None)
                user = json.loads(payload).get("User", None)
                timestamp = json.loads(payload).get("Timestamp", None)
                if (
                    (instr_status)
                    and (app == self.app)
                    and (host == self.host)
                    and (user == self.user)
                ):
                    logger.debug(
                        "MQTT actor %s receives permission for reservation on instrument %s",
                        self.globalName,
                        self.instr_id,
                    )
                    if timestamp is None:
                        timestamp = (
                            datetime.datetime.utcnow().isoformat(timespec="seconds")
                            + "Z"
                        )
                    self.state["RESERVE"]["Active"] = True
                else:
                    logger.debug(
                        "MQTT actor %s receives decline of reservation on instrument %s",
                        self.globalName,
                        self.instr_id,
                    )
                    self.state["RESERVE"]["Active"] = False
                is_reserved = self.state["RESERVE"]["Active"]
                logger.debug("Instrument reserved %s", is_reserved)
                self._forward_reservation(is_reserved)
                self.state["RESERVE"]["Pending"] = False
                return
            logger.warning(
                "MQTT actor %s receives a reply to a non-requested reservation on instrument %s",
                self.globalName,
                self.instr_id,
            )
            return
        if topic == self.allowed_sys_topics["MSG"]:
            logger.debug("[PARSE] send status is: %s", self.state["SEND"]["Pending"])
            if not isinstance(payload, bytes):
                logger.error(
                    "Received a reply that should be bytes while not; the message is %s",
                    payload,
                )
                return
            if len(payload) == 0:
                logger.error("Received an empty reply")
                return
            if self.state["SEND"]["Pending"]:
                re_cmd_id = payload[0]
                st_cmd_id = int.from_bytes(self.state["SEND"]["CMD_ID"], "big")
                logger.debug("Received CMD ID is %s", re_cmd_id)
                logger.debug("Stored CMD ID is %s", self.state["SEND"]["CMD_ID"])
                if re_cmd_id == st_cmd_id:
                    self.state["SEND"]["Pending"] = False
                    self.test_cnt = self.test_cnt + 1
                    logger.debug("test_cnt = %s", self.test_cnt)
                    logger.debug(
                        "MQTT actor %s receives a binary reply %s from instrument %s",
                        self.globalName,
                        payload[1:],
                        self.instr_id,
                    )
                    self.state["SEND"]["Reply"] = payload[1:]
                    # self.state["SEND"]["Reply_Status"] = True
                    _re = {
                        "RETURN": "SEND",
                        "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        "RESULT": {"DATA": self.state["SEND"]["Reply"]},
                    }
                    self.send(
                        self.my_redirector,
                        _re,
                    )
                    return
                logger.warning(
                    (
                        "MQTT actor %s receives a binary reply %s with an unexpected "
                        "CMD ID %s from instrument %s"
                    ),
                    self.globalName,
                    payload,
                    re_cmd_id,
                    self.instr_id,
                )
                return
            logger.warning(
                "MQTT actor %s receives an unknown binary reply %s from instrument %s",
                self.globalName,
                payload,
                self.instr_id,
            )
            return
        logger.warning(
            "MQTT actor %s receives an unknown message %s from instrument %s",
            self.globalName,
            payload,
            self.instr_id,
        )
        return

    def on_connect(self, _client, _userdata, _flags, result_code):
        """Will be carried out when the client connected to the MQTT broker."""
        if result_code == 0:
            self.is_connected = True
            logger.debug(
                "[CONNECT] IS ID %s connected with result code %s.",
                self.is_id,
                result_code,
            )
            for k in self.allowed_sys_topics:
                self.allowed_sys_topics[k] = self.is_id + self.ALLOWED_SYS_OPTIONS[k]
            self.mqttc.publish(
                retain=True,
                topic=f"{self.is_id}/meta",
                payload=ismqtt_messages.get_is_meta(
                    ismqtt_messages.InstrumentServerMeta(
                        state=2,
                        host=self.is_id,
                        description=ismqtt_config["DESCRIPTION"],
                        place=ismqtt_config["PLACE"],
                        latitude=ismqtt_config["LATITUDE"],
                        longitude=ismqtt_config["LONGITUDE"],
                        height=ismqtt_config["HEIGHT"],
                    )
                ),
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
                for instrument in mycluster:
                    if instrument.device_id == instrument_id:
                        if locks.get(instrument.device_id, None):
                            with locks[instrument.device_id]:
                                if reservations.get(instrument.device_id, None):
                                    old = reservations[instrument.device_id]
                                    reservations[
                                        instrument.device_id
                                    ] = ismqtt_messages.Reservation(
                                        active=old.active,
                                        app=old.app,
                                        host=old.host,
                                        timestamp=time.time(),
                                        user=old.user,
                                    )
                                    self.process_cmd(message, instrument)
                # TODO: If code gets here, then the instrument got disconnected
                return
            if (
                len(message.topic) > len("control") + len(self.is_id) + 2
                and message.topic[-len("control") :] == "control"
            ):
                instrument_id = message.topic[: -len("control") - 1][
                    len(self.is_id) + 1 :
                ]
                for instrument in mycluster:
                    if instrument.device_id == instrument_id:
                        self.process_control(message, instrument)
            if (
                len(message.topic) > len("meta") + len(self.is_id) + 2
                and message.topic[-len("meta") :] == "meta"
            ):
                instrument_id = message.topic[: -len("meta") - 1][len(self.is_id) + 1 :]
                logger.debug("Check if %s is still connected", instrument_id)
                if instrument_id not in mycluster.connected_instruments:
                    logger.debug("%s not connected", instrument_id)
                    self.process_old(message, instrument_id)

    def process_cmd(self, msg, device_id):
        """
        Sub-event handler for after a MQTT message was received on a subscribed
        topic this is specific for processing raw SARAD frames
        """
        cmd = msg.payload
        logger.debug("Received command %s", cmd)
        logger.debug("Trying to get reply from instrument.")
        # TODO: Actorgerecht aufteilen!
        reply = cmd[:1] + instrument.get_message_payload(cmd[1:], 3)
        # TODO: Actorgerecht aufteilen!
        self.mqttc.publish(f"{self.is_id}/{device_id}/msg", reply)

    def process_control(self, msg, instrument):
        """
        Sub-Event Handler for after a mqtt message was received on a
        subscribed topic this is specific for processing control messages
        """
        logger.debug(msg.payload)
        controll = ismqtt_messages.get_instr_control(msg)
        logger.debug(controll)
        if controll.ctype == ismqtt_messages.ControlType.RESERVE:
            self.process_reserve(instrument, controll)
        if controll.ctype == ismqtt_messages.ControlType.FREE:
            try:
                with locks[instrument.device_id]:
                    self.process_free(instrument, controll)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failde tor handle FREE comand")

    def process_reserve(self, instrument, controll):
        """
        Sub-event handler for after a MQTT message was received on a subscribed
        topic this is specific for processing control messages,
        reservation requests to be specific
        """
        logger.debug(
            "[RESERVE] client=%s, instrument=%s, controll=%s",
            self.mqttc,
            instrument,
            controll,
        )
        success = False

        if not success and not reservations.get(instrument.device_id, None):
            success = True

        if not success and (
            reservations[instrument.device_id].host == controll.data.host
            and reservations[instrument.device_id].app == controll.data.app
            and reservations[instrument.device_id].user == controll.data.user
        ):
            success = True

        if (
            not success
            and controll.data.timestamp - reservations[instrument.device_id].timestamp
            > self.MAX_RESERVE_TIME
        ):
            success = True

        if success:
            reservations[instrument.device_id] = ismqtt_messages.Reservation(
                active=True,
                app=controll.data.app,
                host=controll.data.host,
                timestamp=controll.data.timestamp,
                user=controll.data.user,
            )

        self.mqttc.publish(
            topic=f"{self.is_id}/{instrument.device_id}/reservation",
            payload=ismqtt_messages.get_instr_reservation(
                reservations[instrument.device_id]
            ),
        )  # static result

    def process_free(self, instrument, controll):
        """
        Sub-Event Handler for after a mqtt message was received on a subscribed
        topic this is specific for processing control messages,
        free (dropping reservation) requests to be specific
        """
        logger.debug(
            "[FREE] client=%s, instrument=%s, controll=%s",
            self.mqttc,
            instrument,
            controll,
        )
        success = False

        if not success and reservations.get(instrument.device_id, None) is None:
            logger.debug(
                "[FREE] Instrument is not in the list of reserved instruments."
            )
            success = True

        if not success and (
            reservations[instrument.device_id].host == controll.data.host
            and reservations[instrument.device_id].app == controll.data.app
            and reservations[instrument.device_id].user == controll.data.user
        ):
            success = True

        if not success and (
            controll.data.timestamp - reservations[instrument.device_id].timestamp
            > self.MAX_RESERVE_TIME
        ):
            success = True

        if success:
            reservations[instrument.device_id] = None

        self.mqttc.publish(
            topic=f"{self.is_id}/{instrument.device_id}/reservation",
            payload=ismqtt_messages.get_instr_reservation(
                ismqtt_messages.Reservation(active=False, timestamp=time.time())
            ),
        )

    def process_old(self, msg, instrument_id):
        """
        Publish a message that instrument_id is not connected.
        """
        old = ismqtt_messages.get_instr_meta_msg(msg)
        if old is None or old.state == 0:
            logger.debug("Nothing to do with instrument %s", instrument_id)
            return
        logger.debug("Freeing old instrument %s", instrument_id)
        self.mqttc.publish(
            topic=msg.topic,
            retain=msg.retain,
            payload=ismqtt_messages.get_instr_meta(
                ismqtt_messages.InstrumentMeta(
                    state=0,
                    host=old.host,
                    family=old.family,
                    instrumentType=old.instrumentType,
                    name=old.name,
                    serial=old.serial,
                )
            ),
        )  # def publish(self, topic, payload=None, qos=0, retain=False, properties=None)

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.debug("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.debug("Already disconnected")
        logger.debug("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.debug("Disconnected gracefully")

    def _publish(self, message: dict) -> bool:
        logger.debug("Work state: publish")
        if not self.is_connected:
            logger.warning("Failed to publish the message because of disconnection")
            return False
        mqtt_topic = message["topic"]
        mqtt_payload = message["payload"]
        mqtt_qos = message["qos"]
        retain = message.get("retain", None)
        if retain is None:
            retain = False
        logger.debug("To publish")
        return_code, self.mid["PUBLISH"] = self.mqttc.publish(
            mqtt_topic,
            payload=mqtt_payload,
            qos=mqtt_qos,
            retain=retain,
        )
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Publish failed; result code is: %s", return_code)
            return False
        return True

    def _subscribe(self, sub_info: list) -> bool:
        logger.debug("Work state: subscribe")
        if not self.is_connected:
            logger.error("[Subscribe] failed, not connected to broker")
            return False
        return_code, self.mid["SUBSCRIBE"] = self.mqttc.subscribe(sub_info)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.error("Subscribe failed; result code is: %s", return_code)
            return False
        logger.info("[Subscribe] to %s successful", sub_info)
        return True

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