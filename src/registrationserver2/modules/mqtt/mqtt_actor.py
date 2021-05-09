"""Main actor of the Registration Server -- implementation for MQTT

Created
    2021-02-16

Author
    Yang, Yixiang

.. uml :: uml-mqtt_actor.puml
"""
import json
import queue
import time

import paho.mqtt.client as MQTT  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.messages import RETURN_MESSAGES
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import ActorExitRequest, ChildActorExited, WakeupMessage

logger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """ Actor interacting with a new device"""

    # "copy" ACCEPTED_COMMANDS of the DeviceBaseActor
    ACCEPTED_COMMANDS = DeviceBaseActor.ACCEPTED_COMMANDS
    # add some new accessible methods
    ACCEPTED_COMMANDS["PREPARE"] = "_prepare"
    # ACCEPTED_COMMANDS["RESERVATION_CANCEL"] = "_reserve_cancel"
    # ACCEPTED_COMMANDS["PARSE"] = "_parse"
    # ACCEPTED_COMMANDS["TEST"] = "_test"
    REPLY_TO_WAIT_FOR = {}

    @overrides
    def __init__(self):
        super().__init__()
        self.subscriber = None
        self.is_id = None
        self.instr_id = None
        self.rc_disc = 2
        self.allowed_sys_topics = {
            "CTRL": "/control",
            "RESERVE": "/reservation",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
        }
        self.REPLY_TO_WAIT_FOR["RESERVE"] = {}
        self.REPLY_TO_WAIT_FOR["SEND"] = {}
        # if there be a reply to wait for, then it should be true
        self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = False
        # store the reservation status
        self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
        # if there be a reply to wait for, then it should be true
        self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
        self.test_cnt = 0
        logger.info("test_cnt = %s", self.test_cnt)
        self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
        # store the CMD ID
        # self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"] = False # if matched, it is true
        self.REPLY_TO_WAIT_FOR["SEND"]["Reply"] = None
        self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = None
        # store the address of the sender
        self.binary_reply = b""
        self.mqtt_broker = None
        self.port = None

        self.subscriber_addr = None
        self.cmd_id = 0

        self.mqtt_topic: str = ""
        self.mqtt_payload: str = ""
        self.mqtt_cid: str = ""
        self.mqttc = None
        self.lwt_payload = None
        self.lwt_topic = None
        self.lwt_qos = None
        self.mqtt_qos = 0
        self.retain = False

        # An queue to parse would store the mqtt messages when the client actor is at setup state
        self.queue_to_parse = queue.Queue()
        self.ungr_disconn = 2
        self.is_connected = False
        self.mid = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check
        # self.work_mode = 0 # 1: test mode; 0: work mode

    @overrides
    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, dict):
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
                        "Received %s from %s. This should never happen.", msg, sender
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                    )
                    return
                if getattr(self, cmd_function, None) is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.", msg, sender
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
            if isinstance(msg, WakeupMessage):
                if msg.payload == "Parse":
                    self._parse(msg)
                # elif msg.payload == "Reserve":
                #    self._reserve_at_is(None, None, None)
                else:
                    logger.debug("Received an unknown wakeup message")
                return
            if isinstance(msg, ChildActorExited):
                logger.info("The child actor is killed")
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

    def _send(self, msg: dict, sender) -> None:
        if msg is None:
            logger.error(
                "SEND: no contents received for the actor '%s' to send", self.globalName
            )
            return
        data = msg.get("PAR", None).get("DATA", None)
        if (data is None) or (not isinstance(data, bytes)):
            logger.error(
                "SEND: no data received for the actor '%s' to send or the data are not bytes",
                self.globalName,
            )
            return
        logger.info("To send: %s", data)
        logger.info("CMD ID is: %s", self.cmd_id)
        qos = msg.get("PAR", None).get("qos", None)
        if qos is None:
            qos = 0

        _msg = {
            "CMD": "SUBSCRIBE",
            "PAR": {"INFO": [(self.allowed_sys_topics["MSG"], 0)]},
        }
        _re = self._subscribe(_msg)
        logger.info(_re)
        if _re["ERROR_CODE"] not in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error(
                "Failed subscription to the topic '%s', for which the error code is %s",
                self.allowed_sys_topics["MSG"],
                _re["ERROR_CODE"],
            )
            return
        self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = True
        self.test_cnt = self.test_cnt + 1
        logger.info("test_cnt = %s", self.test_cnt)
        self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = bytes([self.cmd_id])
        logger.info("CMD ID is: %s", self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"])
        self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = sender
        _msg = {
            "CMD": "PUBLISH",
            "PAR": {
                "topic": self.allowed_sys_topics["CMD"],
                "payload": bytes([self.cmd_id]) + data,
                "qos": qos,
            },
        }
        _re = self._publish(_msg)
        if self.cmd_id == 255:
            self.cmd_id = 0
        else:
            self.cmd_id = self.cmd_id + 1
        logger.info(_re)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error(
                (
                    "Failed to publish a message with an ID '%s' under the topic '%s', "
                    "for which the error code is %s"
                ),
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
                _re["ERROR_CODE"],
            )
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
            self.test_cnt = self.test_cnt + 1
            logger.info("test_cnt = %s", self.test_cnt)
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
            return
        logger.info("[SEND] send status is: ")
        logger.info(self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"])

    def _reserve_at_is(self):
        logger.info(
            "[Reserve]\tThe MQTT actor '%s' is to subscribe to the 'reserve' topic",
            self.globalName,
        )
        if not self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"]:
            _msg = {
                "CMD": "SUBSCRIBE",
                "PAR": {"INFO": [(self.allowed_sys_topics["RESERVE"], 0)]},
            }
            _re = self._subscribe(_msg)
            if _re["ERROR_CODE"] not in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.error(_re)
                return
            _msg = {
                "CMD": "PUBLISH",
                "PAR": {
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
                },
            }
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = True
            _re = self._publish(_msg)
            if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.error(_re)
                self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = False
                return
            logger.info("[Reserve at IS]: To wait for the reply to reservation request")

    @overrides
    def _free(self, msg, sender) -> None:
        logger.info("Free-Request")
        if msg is None:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return
        _msg = {
            "CMD": "PUBLISH",
            "PAR": {
                "topic": self.allowed_sys_topics["CTRL"],
                "payload": json.dumps({"Req": "free"}),
                "qos": 0,
            },
        }
        _re = self._publish(_msg)
        logger.info(_re)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            self.send(sender, {"RETURN": "FREE", "ERROR_CODE": _re["ERROR_CODE"]})
            return
        logger.info(
            "[Free]\tThe MQTT actor '%s' is to unsusbcribe to the 'reserve' and 'msg' topics",
            self.globalName,
        )
        topics = [self.allowed_sys_topics["RESERVE"], self.allowed_sys_topics["MSG"]]
        _re = self._unsubscribe(topics)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            self.send(sender, {"RETURN": "FREE", "ERROR_CODE": _re["ERROR_CODE"]})
            return
        super()._free(msg, sender)

    def _kill(self, msg: dict, sender):
        logger.debug(self.allowed_sys_topics)
        self._unsubscribe("+")
        self._disconnect()
        time.sleep(1)
        super()._kill(msg, sender)
        # TODO: clear the used memory space
        # TODO: let others like the other actors and this actor's IS MQTT know this actor is killed

    def _prepare(self, msg: dict, sender):
        logger.info("Actor name = %s", self.globalName)
        self.subscriber = sender
        self.mqtt_cid = self.globalName + ".client"
        self.instr_id = self.globalName.split(".")[0]
        self.is_id = msg.get("PAR", None).get("is_id", None)
        self.mqtt_broker = msg.get("PAR", None).get("mqtt_broker", None)
        self.port = msg.get("PAR", None).get("port", None)
        if self.is_id is None:
            logger.error("No Instrument Server ID received!")
            self.send(
                sender,
                {
                    "RETURN": "PREPARE",
                    "ERROR_CODE": RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT", None).get(
                        "ERROR_CODE", None
                    ),
                },
            )
            return
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
        logger.info("Using the mqtt broker: %s", self.mqtt_broker)
        if self.port is None:
            self.port = 1883
        logger.info("Using the port: %s", self.port)
        self._connect(True)

    def _parse(self, msg: dict) -> None:
        topic = msg.get("PAR", None).get("topic", None)
        payload = msg.get("PAR", None).get("payload", None)
        if topic is None or payload is None:
            logger.warning(
                "The topic or payload is none; topic: %s, payload: %s", topic, payload
            )
            return
        if topic not in (
            self.allowed_sys_topics["MSG"],
            self.allowed_sys_topics["RESERVE"],
        ):
            logger.warning(
                "The topic is not illegal; topic: %s, payload: %s", topic, payload
            )
            return
        if topic == self.allowed_sys_topics["RESERVE"]:
            if self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"]:
                instr_status = json.loads(payload).get("Active", None)
                if instr_status:
                    logger.info(
                        "MQTT Actor '%s' receives a permission of the reservation on the instrument '%s'",
                        self.globalName,
                        self.instr_id,
                    )
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = True
                else:
                    logger.info(
                        "MQTT Actor '%s' receives a decline of the reservation on the instrument '%s'",
                        self.globalName,
                        self.instr_id,
                    )
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = False
                logger.info(self.sender_api)
                logger.info(self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"])
                self._forward_reservation(self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"])
                return
            logger.warning(
                "MQTT Actor '%s' receives a reply to an non-requested reservation on the instrument '%s'",
                self.globalName,
                self.instr_id,
            )
            return
        if topic == self.allowed_sys_topics["MSG"]:
            logger.info("[PARSE] send status is: ")
            logger.info(self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"])
            if not isinstance(payload, bytes):
                logger.error(
                    "Received a reply that should be bytes while not; the message is %s",
                    payload,
                )
                return
            if len(payload) == 0:
                logger.error("Received an empty reply")
                return
            if self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"]:
                re_cmd_id = payload[0]
                st_cmd_id = int.from_bytes(
                    self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"], "big"
                )
                logger.info("Received CMD ID is %s", re_cmd_id)
                logger.info(
                    "Stored CMD ID is %s", self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"]
                )
                if re_cmd_id == st_cmd_id:
                    self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
                    self.test_cnt = self.test_cnt + 1
                    logger.info("test_cnt = %s", self.test_cnt)

                    logger.info(
                        "MQTT Actor '%s' receives a binary reply '%s' from the instrument '%s'",
                        self.globalName,
                        payload[1:],
                        self.instr_id,
                    )
                    self.REPLY_TO_WAIT_FOR["SEND"]["Reply"] = payload[1:]
                    # self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"] = True
                    _re = {
                        "RETURN": "SEND",
                        "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        "RESULT": {"DATA": self.REPLY_TO_WAIT_FOR["SEND"]["Reply"]},
                    }
                    # self.send(self.REPLY_TO_WAIT_FOR["SEND"]["Sender"], _re)
                    ActorSystem().tell(self.REPLY_TO_WAIT_FOR["SEND"]["Sender"], _re)
                    return
                logger.warning(
                    (
                        "MQTT Actor '%s' receives a binary reply '%s' with a unexpected "
                        "CMD ID '%s' from the instrument '%s'"
                    ),
                    self.globalName,
                    payload,
                    re_cmd_id,
                    self.instr_id,
                )
                return
            logger.warning(
                "MQTT Actor '%s' receives an unknown binary reply '%s' from the instrument '%s'",
                self.globalName,
                payload,
                self.instr_id,
            )
            return
        logger.warning(
            "MQTT Actor '%s' receives an unknown message '%s' from the instrument '%s'",
            self.globalName,
            payload,
            self.instr_id,
        )
        return

    def on_connect(self, _client, _userdata, _flags, result_code):
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        logger.info("on_connect")
        if result_code == 0:
            logger.info("Connected with MQTT %s.", self.mqtt_broker)
            self.is_connected = True
            for k in self.allowed_sys_topics:
                self.allowed_sys_topics[k] = (
                    self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
                )
            logger.info(self.allowed_sys_topics)
            self.lwt_topic = self.allowed_sys_topics["CTRL"]
            logger.info("LWT topic = %s", self.lwt_topic)
            self.lwt_payload = json.dumps({"Req": "free"})
            self.lwt_qos = 0
            logger.info("[CONN]: '%s' connected", self.mqtt_cid)
            self.send(
                self.subscriber,
                {
                    "RETURN": "PREPARE",
                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                },
            )
        else:
            logger.info(
                "Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
            )
            self.send(
                self.subscriber,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_STATE"]["ERROR_CODE"],
                },
            )
            self.is_connected = False

    def on_disconnect(self, _client, _userdata, result_code):
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        logger.warning("Disconnected")
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.info(
                "Disconnection from MQTT-broker ungracefully. result_code=%s",
                result_code,
            )
            self._connect(True)
        else:
            self.ungr_disconn = 0
            logger.info("Gracefully disconnected from MQTT-broker.")
        self.is_connected = False

    def on_publish(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_pub = 0
        logger.info("The message with Message-ID %d is published to the broker!\n", mid)
        logger.info("Publish: check the mid")
        if mid == self.mid["PUBLISH"]:
            logger.info("Publish: mid is matched")

    def on_subscribe(self, _client, _userdata, mid, _grant_qos):
        """Here should be a docstring."""
        logger.info("on_subscribe")
        logger.info("mid is %s", mid)
        logger.info("stored mid is %s", self.mid["SUBSCRIBE"])
        if mid == self.mid["SUBSCRIBE"]:
            logger.info("Subscribed to the topic successfully!\n")

    def on_unsubscribe(self, _client, _userdata, mid):
        """Here should be a docstring."""
        logger.info("on_unsubscribe")
        logger.info("mid is %s", mid)
        logger.info("stored mid is %s", self.mid["UNSUBSCRIBE"])
        if mid == self.mid["UNSUBSCRIBE"]:
            logger.info("Unsubscribed to the topic successfully!\n")

    def on_message(self, _client, _userdata, message):
        """Here should be a docstring."""
        logger.info("message received: %s", message.payload)
        logger.info("message topic: %s", message.topic)
        logger.info("message qos: %s", message.qos)
        logger.info("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.error("The payload is none")
        else:
            msg_buf = {
                "CMD": "PARSE",
                "PAR": {
                    "topic": message.topic,
                    "payload": message.payload,
                },
            }
            self._parse(msg_buf)

    def _connect(self, lwt_set: bool) -> dict:
        self.mqttc = MQTT.Client(self.mqtt_cid)
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        logger.info("Try to connect to the mqtt broker")
        if lwt_set:
            logger.info("Set will")
            self.mqttc.will_set(
                self.allowed_sys_topics["CTRL"],
                payload=json.dumps({"Req": "free"}),
                qos=0,
                retain=True,
            )
        self.mqttc.connect(self.mqtt_broker, port=self.port)
        self.mqttc.loop_start()
        if self.is_connected:
            return {
                "RETURN": "CONNECT",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
        return {
            "RETURN": "CONNECT",
            "ERROR_CODE": RETURN_MESSAGES["CONNECT"]["ERROR_CODE"],
        }

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.info("Already disconnected")
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("Disconnection gracefully: %s", RETURN_MESSAGES["OK_SKIPPED"])

    def _publish(self, msg: dict) -> dict:
        logger.info("Work state: publish")
        if not self.is_connected:
            logger.warning("Failed to publish the message because of disconnection")
            self._connect(True)
            return {
                "RETURN": "PUBLISH",
                "ERROR_CODE": RETURN_MESSAGES["PUBLISH"]["ERROR_CODE"],
            }
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        self.mqtt_payload = msg.get("PAR", None).get("payload", None)
        if (self.mqtt_topic is None) or not isinstance(self.mqtt_topic, str):
            logger.warning("the topic is none or not a string")
            return {
                "RETURN": "PUBLISH",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
        if self.mqtt_payload is None:
            logger.warning("the payload is none")
            return {
                "RETURN": "PUBLISH",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
        self.mqtt_qos = msg.get("PAR", None).get("qos", None)
        self.retain = msg.get("PAR", None).get("retain", None)
        if self.retain is None:
            self.retain = False
        logger.info("To publish")
        return_code, self.mid["PUBLISH"] = self.mqttc.publish(
            self.mqtt_topic,
            payload=self.mqtt_payload,
            qos=self.mqtt_qos,
            retain=self.retain,
        )
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Publish failed; result code is: %s", return_code)
            return {
                "RETURN": "PUBLISH",
                "ERROR_CODE": RETURN_MESSAGES["PUBLISH"]["ERROR_CODE"],
            }
        return {
            "RETURN": "PUBLISH",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }

    def _subscribe(self, msg: dict) -> dict:
        logger.info("Work state: subscribe")
        if not self.is_connected:
            logger.warning(
                "Failed to subscribe to the topic(s) because of disconnection"
            )
            self._connect(True)
            return {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE"]["ERROR_CODE"],
            }
        sub_info = msg.get("PAR", None).get("INFO", None)
        if sub_info is None:
            logger.warning("[Subscribe]: the INFO for subscribe is none")
            return {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
        if isinstance(sub_info, list):
            for ele in sub_info:
                if not isinstance(ele, tuple):
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list "
                        "while it contains a non-tuple element"
                    )
                    return {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                        ],
                    }
                if len(ele) != 2:
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list while it contains "
                        "a tuple elemnt whose length is not equal to 2"
                    )
                    return {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                        ],
                    }
                if len(ele) == 2 and ele[0] is None:
                    logger.warning(
                        "[Subscribe]: the first element of one tuple namely the 'topic' is None"
                    )
                    return {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                        ],
                    }
            return_code, self.mid["SUBSCRIBE"] = self.mqttc.subscribe(sub_info)
            if return_code != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Subscribe failed; result code is: %s", return_code)
                return {
                    "RETURN": "SUBCRIBE",
                    "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"]["ERROR_CODE"],
                }
            return {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
        return {
            "RETURN": "SUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
        }

    def _unsubscribe(self, topics):
        logger.debug("Unsubscribe topic %s", topics)
        if not self.is_connected:
            logger.warning(
                "Failed to unsubscribe to the topic(s) because of disconnection"
            )
            return {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
            }
        if (
            topics is None
            and not isinstance(topics, list)
            and not isinstance(topics, str)
        ):
            logger.warning(
                "[Unsubscribe]: The topic is none or it is neither a string nor a list "
            )
            return {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
            }
        return_code, self.mid["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topics)
        if return_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Unsubscribe failed; result code is: %s", return_code)
            return {
                "RETURN": "UNSUBCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
            }
        return {
            "RETURN": "UNSUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
