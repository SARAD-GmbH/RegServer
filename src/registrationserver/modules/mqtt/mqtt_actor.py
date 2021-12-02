"""Main actor of the Registration Server -- implementation for MQTT

Created
    2021-02-16

Author
    Yang, Yixiang
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_actor.puml
"""
import datetime
import json
import time
import os
import ssl

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.config import mqtt_config
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.modules.messages import RETURN_MESSAGES

logger.debug("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """Actor interacting with a new device"""

    @overrides
    def __init__(self):
        super().__init__()
        self.ACCEPTED_COMMANDS["PREPARE"] = "_prepare"
        self.subscriber = None
        self.is_id = None
        self.instr_id = None
        self.allowed_sys_topics = {
            "CTRL": "/control",
            "RESERVE": "/reservation",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
        }
        self.allowed_sys_options = {
            "CTRL": "/control",
            "RESERVE": "/reservation",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
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
        self.mqttc = None
        self.ungr_disconn = 2
        self.is_connected = False
        self.mid = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check

    def _send(self, msg, sender) -> None:
        if msg is None:
            logger.error("[SEND] no contents to send for actor %s", self.globalName)
            return
        data = msg.get("PAR", None).get("DATA", None)
        if (data is None) or (not isinstance(data, bytes)):
            logger.error(
                "[SEND] no data to send for actor %s or the data are not bytes",
                self.globalName,
            )
            return
        logger.debug("To send: %s", data)
        logger.debug("CMD ID is: %s", self.cmd_id)
        qos = msg.get("PAR", None).get("qos", None)
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

    def _reserve_at_is(self):
        logger.debug(
            "[Reserve] Subscribe MQTT actor %s to the 'reserve' topic",
            self.globalName,
        )
        if not self.state["RESERVE"]["Pending"]:
            if not self._subscribe([(self.allowed_sys_topics["RESERVE"], 0)]):
                return
            if not self._subscribe([(self.allowed_sys_topics["MSG"], 0)]):
                return
            _msg = {
                "topic": self.allowed_sys_topics["CTRL"],
                "payload": json.dumps(
                    {
                        "Req": "reserve",
                        "App": self.app,
                        "Host": self.host,
                        "User": self.user,
                    }
                ),
                "qos": 0,
            }
            self.state["RESERVE"]["Pending"] = True
            if not self._publish(_msg):
                self.state["RESERVE"]["Pending"] = False
                return
            logger.debug("[Reserve at IS]: Waiting for reply to reservation request")

    @overrides
    def _free(self, msg, sender) -> None:
        logger.debug("Free-Request")
        if msg is None:
            logger.critical("Actor message is None. This schould never happen.")
            super()._free(msg, sender)
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
            super()._free(msg, sender)
            return
        logger.info(
            "[Free] Unsubscribe MQTT actor %s from 'reserve' and 'msg' topics",
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
            super()._free(msg, sender)
            return
        super()._free(msg, sender)

    def _kill(self, msg, sender):
        logger.debug(self.allowed_sys_topics)
        self._unsubscribe(["+"])
        self._disconnect()
        time.sleep(1)
        super()._kill(msg, sender)

    def _prepare(self, msg, sender):
        logger.debug("Actor name = %s", self.globalName)
        self.subscriber = sender
        mqtt_cid = self.globalName + ".client"
        self.instr_id = self.globalName.split(".")[0]
        self.is_id = msg.get("PAR", None).get("is_id", None)
        mqtt_broker = msg.get("PAR", None).get("mqtt_broker", "127.0.0.1")
        port = msg.get("PAR", None).get("port", 1883)
        logger.info("Using MQTT broker %s with port %d", mqtt_broker, port)
        if self.is_id is None:
            logger.error("No Instrument Server ID received!")
            self.send(
                sender,
                {
                    "RETURN": "PREPARE",
                    "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
                },
            )
            return
        self.mqttc = MQTT.Client(mqtt_cid)
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        for k in self.allowed_sys_topics:
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_options[k]
            )
            logger.debug("allowed topic: %s", self.allowed_sys_topics[k])
        self.mqttc.message_callback_add(
            self.allowed_sys_topics["RESERVE"], self.on_reserve
        )
        self.mqttc.message_callback_add(self.allowed_sys_topics["MSG"], self.on_msg)
        logger.debug(
            "When I die, the instrument shall be given free. This is my last will."
        )
        self.mqttc.will_set(
            self.allowed_sys_topics["CTRL"],
            payload=json.dumps({"Req": "free"}),
            qos=0,
            retain=True,
        )
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

                if(mqtt_config["TLS_USE_TLS"]):
                    self.mqttc.tls_set(ca_certs=os.path.expanduser(mqtt_config["TLS_CA_FILE"]), certfile=os.path.expanduser(mqtt_config["TLS_CERT_FILE"]), keyfile=os.path.expanduser(mqtt_config["TLS_KEY_FILE"]), cert_reqs=ssl.CERT_REQUIRED)

                self.mqttc.connect(mqtt_broker, port=port)
                success = True
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("Could not connect to Broker, retrying...: %s", exception)
                time.sleep(retry_interval)

    def on_reserve(self, _client, _userdata, message):
        """Handler for MQTT messages regarding reservation of instruments"""
        payload = json.loads(message.payload)
        if self.state["RESERVE"]["Pending"]:
            instr_status = payload.get("Active")
            app = payload.get("App")
            host = payload.get("Host")
            user = payload.get("User")
            timestamp = payload.get("Timestamp")
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
                        datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
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

    def on_msg(self, _client, _userdata, message):
        """Handler for MQTT messages regarding binary messages from instrument"""
        payload = message.payload
        logger.debug("Send status is: %s", self.state["SEND"]["Pending"])
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

    def on_connect(self, _client, _userdata, _flags, result_code):
        """Will be carried out when the client connected to the MQTT broker."""
        if result_code == 0:
            self.is_connected = True
            logger.info("[CONNECT] Connected to MQTT broker")
            self.send(
                self.subscriber,
                {
                    "RETURN": "PREPARE",
                    "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                },
            )
        else:
            self.is_connected = False
            logger.error(
                "[CONNECT] Connection to MQTT broker failed with %s",
                result_code,
            )
            self.send(
                self.subscriber,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_STATE"]["ERROR_CODE"],
                },
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

    def on_publish(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_pub = 0
        logger.debug("The message with Message-ID %d is published to the broker!", mid)
        logger.debug("Publish: check the mid")
        if mid == self.mid["PUBLISH"]:
            logger.debug("Publish: mid is matched")

    def on_subscribe(self, _client, _userdata, mid, _grant_qos):
        """Here should be a docstring."""
        logger.debug("on_subscribe")
        logger.debug("mid is %s", mid)
        logger.debug("stored mid is %s", self.mid["SUBSCRIBE"])
        if mid == self.mid["SUBSCRIBE"]:
            logger.debug("Subscribed to the topic successfully!\n")

    def on_unsubscribe(self, _client, _userdata, mid):
        """Here should be a docstring."""
        logger.debug("on_unsubscribe")
        logger.debug("mid is %s", mid)
        logger.debug("stored mid is %s", self.mid["UNSUBSCRIBE"])
        if mid == self.mid["UNSUBSCRIBE"]:
            logger.debug("Unsubscribed to the topic successfully!\n")

    @staticmethod
    def on_message(_client, _userdata, message):
        """Handler for all MQTT messages that cannot be handled by on_reserve or on_msg."""
        logger.debug("message received: %s", message.payload)
        logger.debug("message topic: %s", message.topic)
        logger.debug("message qos: %s", message.qos)
        logger.debug("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.warning("The payload is none")
        else:
            logger.warning("Unknown MQTT message")

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.debug("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn in (1, 0):
            self.ungr_disconn = 2
            logger.debug("Already disconnected")
        logger.debug("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.debug("Disconnected gracefully")

    def _publish(self, msg) -> bool:
        logger.debug("Work state: publish")
        if not self.is_connected:
            logger.warning("Failed to publish the message because of disconnection")
            return False
        mqtt_topic = msg["topic"]
        mqtt_payload = msg["payload"]
        mqtt_qos = msg["qos"]
        retain = msg.get("retain", None)
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
