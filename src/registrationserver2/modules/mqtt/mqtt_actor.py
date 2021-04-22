"""Main actor of the Registration Server -- implementation for MQTT

Created
    2021-02-16

Author
    Yang, Yixiang

.. uml :: uml-mqtt_actor.puml

Todo:
    * uml-mqtt_actor.puml is only a copy of uml-rfc2217_actor.puml. It has to
      be updated.
    * use lazy formatting in logger
"""
import datetime
import json
import time
from pickle import NONE, TRUE

import paho.mqtt.client as MQTT  # type: ignore
from _datetime import datetime
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES, is_JSON
from registrationserver2.modules.mqtt.mqtt_client_actor import MqttClientActor
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import (ActorExitRequest, ActorSystem,  # type: ignore
                             WakeupMessage)

logger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    is_id: str

    instr_id: str

    # "copy" ACCEPTED_COMMANDS of the DeviceBaseActor
    ACCEPTED_COMMANDS = DeviceBaseActor.ACCEPTED_COMMANDS
    # add some new accessible methods
    ACCEPTED_COMMANDS["PREPARE"] = "_prepare"
    ACCEPTED_COMMANDS["RESERVATION_CANCEL"] = "_reserve_cancel"

    REPLY_TO_WAIT_FOR = {}

    @overrides
    def __init__(self):
        super().__init__()
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        self.allowed_sys_topics = {
            "CTRL": "/control",
            "RESERVE": "/reserve",
            "CMD": "/cmd",
            "MSG": "/msg",
            # "META": "/meta",
        }
        self.REPLY_TO_WAIT_FOR["RESERVE"] = {}
        self.REPLY_TO_WAIT_FOR["SEND"] = {}
        self.REPLY_TO_WAIT_FOR["RESERVE"][
            "Send_Status"
        ] = False  # if there be a reply to wait for, then it should be true
        self.REPLY_TO_WAIT_FOR["RESERVE"][
            "Active"
        ] = None  # store the reservation status
        self.REPLY_TO_WAIT_FOR["SEND"][
            "Send_Status"
        ] = False  # if there be a reply to wait for, then it should be true
        self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None  # store the CMD ID
        self.REPLY_TO_WAIT_FOR["SEND"][
            "Sender"
        ] = None  # store the address of the sender
        self.binary_reply = b""
        self.mqtt_cid = self.globalName + ".client"
        self.mqtt_broker = None
        self.port = None
        self.instr_id = self.globalName.split("/")[1]
        self.subscriber_addr = None
        self.myClient = None
        self.cmd_id = 0

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
                if msg.payload == "Parser":
                    self.__mqtt_parser(msg, sender)
                elif msg.payload == "Reserve":
                    self._reserve_at_is(None, None, None)
                else:
                    logger.debug("Received an unknown wakeup message")
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

    def _send(self, msg: dict, sender) -> None:
        if msg is None:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return
        data = msg.get("PAR", None).get("Data", None)
        if (data is None) or (not isinstance(data, bytes)):
            self.send(
                sender,
                {
                    "RETURN": "SEND",
                    "ERROR_CODE": RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT", None).get(
                        "ERROR_CODE", None
                    ),
                },
            )
            return
        qos = msg.get("PAR", None).get("qos", None)
        if qos is None:
            qos = 0

        ask_msg = {
            "CMD": "SUBSCRIBE",
            "PAR": {"INFO": (self.allowed_sys_topics["MSG"], 0)},
        }
        ask_return = ActorSystem().ask(self.myClient, ask_msg)
        logger.info(ask_return)
        if ask_return is None:
            logger.error(
                "Got no reply to asking the client to subscribe to the topic '%s'",
                self.allowed_sys_topics["MSG"],
            )
            self.send(
                sender,
                {
                    "RETURN": "SEND",
                    "ERROR_CODE": RETURN_MESSAGES.get("ASK_NO_REPLY", None).get(
                        "ERROR_CODE", None
                    ),
                },
            )
            return
        elif not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "SEND", "ERROR_CODE": ask_return["ERROR_CODE"]}
            )
            return
        self.REPLY_TO_WAIT_FOR["SEND"]["Send_status"] = True
        self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = sender
        self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = bytes([self.cmd_id])
        if self.cmd_id == 255:
            self.cmd_id = 0
        else:
            self.cmd_id = self.cmd_id + 1
        ask_msg = {
            "CMD": "PUBLISH",
            "PAR": {
                "topic": self.allowed_sys_topics["CMD"],
                "payload": bytes([self.cmd_id]) + data,
                "qos": qos,
            },
        }
        ask_return = ActorSystem().ask(self.myClient, ask_msg, timeout=0.06)
        logger.info(ask_return)
        if ask_return is None:
            logger.error(
                "Got no reply to asking the client to publish a message with an ID '%s' under the topic '%s'",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_status"] = False
            self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = None
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
            if self.cmd_id == 0:
                self.cmd_id = 255
            else:
                self.cmd_id = self.cmd_id - 1
            self.send(
                sender,
                {
                    "RETURN": "SEND",
                    "ERROR_CODE": RETURN_MESSAGES.get("ASK_NO_REPLY", None).get(
                        "ERROR_CODE", None
                    ),
                },
            )
            return
        elif not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.error(
                "Failed to publish a message with an ID '%s' under the topic '%s'",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_status"] = False
            self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = None
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
            if self.cmd_id == 0:
                self.cmd_id = 255
            else:
                self.cmd_id = self.cmd_id - 1
            self.send(
                sender, {"RETURN": "SEND", "ERROR_CODE": ask_return["ERROR_CODE"]}
            )
            return

        return

    """
    @overrides
    def _reserve(self, msg: dict, sender) -> None:
        logger.info("Device actor received a RESERVE command with message: %s", msg)
        self.sender_api = sender
        try:
            self.app = msg["PAR"]["APP"]
        except LookupError:
            logger.error("ERROR: there is no APP name!")
            return
        try:
            self.host = msg["PAR"]["HOST"]
        except LookupError:
            logger.error("ERROR: there is no HOST name!")
            return
        try:
            self.user = msg["PAR"]["USER"]
        except LookupError:
            logger.error("ERROR: there is no USER name!")
            return
        if self._reserve_at_is(self.app, self.host, self.user):
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = True # if there be a reply to wait for, then it should be true
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Sender"] = sender # store the address of the sender
        return
    """

    def _reserve_at_is(self, app, host, user) -> bool:
        logger.info(
            f"[Reserve]\tThe MQTT actor '{self.globalName}' is to subscribe to the 'reserve' topic"
        )
        if not self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_status"]:
            ask_msg = {
                "CMD": "SUBSCRIBE",
                "PAR": {"INFO": (self.allowed_sys_topics["RESERVE"], 0)},
            }
            ask_return = ActorSystem().ask(self.myClient, ask_msg)

            if not ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
            ):
                logger.error(ask_return)
                return False
            ask_msg = {
                "CMD": "PUBLISH",
                "PAR": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": {
                        "Req": "reserve",
                        "App": app,
                        "Host": host,
                        "User": user,
                    },
                    "qos": 0,
                },
            }
            ask_return = ActorSystem().ask(self.myClient, ask_msg)

            if not ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
            ):
                logger.error(ask_return)
                return False
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_status"] = True

        if self.REPLY_TO_WAIT_FOR.get("RESERVE", None).get("Active", None) is None:
            pass
        elif self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] == True:
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
            return True
        else:
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
            return False

        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="RESERVE")

    def _free(self, msg, sender) -> None:
        logger.info("Free-Request")
        free_req_msg = {}
        if msg is None:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return
        free_req_msg["Req"] = msg.get("Req", None)
        if free_req_msg["Req"] is None:
            free_req_msg["Req"] = "free"
        ask_msg = {
            "CMD": "PUBLISH",
            "PAR": {
                "topic": self.allowed_sys_topics["CTRL"],
                "payload": free_req_msg,
                "qos": 0,
            },
        }
        ask_return = ActorSystem.ask(self.myClient, ask_msg)
        logger.info(ask_return)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "FREE", "ERROR_CODE": ask_return["ERROR_CODE"]}
            )
            return
        logger.info(
            f"[Free]\tThe MQTT actor '{self.globalName}' is to unsusbcribe to the 'reserve' and 'msg' topics"
        )
        ask_msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": [
                    self.allowed_sys_topics["RESERVE"],
                    self.allowed_sys_topics["MSG"],
                ]
            },
        }
        ask_return = ActorSystem.ask(self.myClient, ask_msg)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "FREE", "ERROR_CODE": ask_return["ERROR_CODE"]}
            )
            return
        super()._free(msg, sender)

    def _kill(self, msg: dict, sender):
        ask_msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": [
                    self.allowed_sys_topics["MSG"],
                    self.allowed_sys_topics["RESERVE"],
                ],
            },
        }
        self.send(self.myClient, ask_msg)
        time.sleep(1)
        self.send(self.myClient, ActorExitRequest())
        time.sleep(1)
        super()._kill(msg, sender)
        # TODO: clear the used memory space
        # TODO: let others like the other actors and this actor's IS MQTT know this actor is killed

    def _prepare(self, msg: dict, sender):
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
        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
        logger.infor("Using the mqtt broker: %s", self.mqtt_broker)
        if self.port is None:
            self.port = 1883
        logger.infor("Using the port: %s", self.port)
        self.myClient = self.createActor(
            MqttClientActor, globalName=self.globalName + ".client_actor"
        )
        lwt_msg = {
            "lwt_topic": self.allowed_sys_topics["CTRL"],
            "lwt_payload": {
                "Req": "free",
            },
            "lwt_qos": 0,
        }
        ask_msg = {
            "CMD": "SETUP",
            "PAR": {
                "client_id": self.mqtt_cid,
                "mqtt_broker": self.mqtt_broker,
                "port": self.port,
                "LWT": lwt_msg,
            },
        }
        ask_return = ActorSystem().ask(self.myClient, ask_msg)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.critical(
                "Failed to setup the client actor because of failed connection. Kill this client actor."
            )
            ActorSystem().tell(self.myClient, ActorExitRequest())
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
                },
            )
            return
        logger.info("[CONN]: The client '%s': %s", self.mqtt_cid, ask_return)
        """
        ask_msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": [self.allowed_sys_topics["MSG"], self.allowed_sys_topics["RESERVE"]],
            }
        }
        ask_return = ActorSystem().ask(self.myClient, ask_msg)
        if not ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor because of failed unsubscription. Kill this client actor.")
            ActorSystem().tell(self.myClient, ActorExitRequest())
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"]})
            return
        """
        self.send(
            sender,
            {
                "RETURN": "PREPARE",
                "ERROR_CODE": RETURN_MESSAGES.get("OK_SKIPPED", None).get(
                    "ERROR_CODE", None
                ),
            },
        )
        return

    def _parse(self, msg: dict, sender) -> None:
        if sender != self.myClient:
            logger.warning(
                "Received a MQTT message '%s' from an unknown sender '%s'", msg, sender
            )
            # self.send(sender, {"RETURN": "PARSE", "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_SENDER"]["ERROR_CODE"]})
            return
        topic = msg.get("PAR", None).get("topic", None)
        payload = msg.get("PAR", None).get("payload", None)
        if topic is None or payload is None:
            logger.warning(
                "The topic or payload is none; topic: %s, payload: %s", topic, payload
            )
            return
        if (
            topic != self.allowed_sys_topics["MSG"]
            and topic != self.allowed_sys_topics["RESERVE"]
        ):
            logger.warning(
                "The topic is not llegal; topic: %s, payload: %s", topic, payload
            )
            return
        if topic == self.allowed_sys_topics["RESERVE"]:
            if self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_status"]:
                instr_status = payload.get("Active", None)
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
                self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="RESERVE")
                return
            else:
                logger.warning(
                    "MQTT Actor '%s' receives a reply to an non-requested reservation on the instrument '%s'",
                    self.globalName,
                    self.instr_id,
                )
                return
        elif topic == self.allowed_sys_topics["MSG"]:
            if self.REPLY_TO_WAIT_FOR["SEND"]["Send_status"]:
                re_cmd_id = payload[0]
                if re_cmd_id == self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"]:
                    logger.info(
                        "MQTT Actor '%s' receives a binary reply '%s' from the instrument '%s'",
                        self.globalName,
                        payload[1:],
                        self.instr_id,
                    )
                    self.send(self.REPLY_TO_WAIT_FOR["SEND"]["Sender"], payload[1:])
                    return
                else:
                    logger.warning(
                        "MQTT Actor '%s' receives a binary reply '%s' with a unexpected CMD ID '%s' from the instrument '%s'",
                        self.globalName,
                        payload,
                        re_cmd_id,
                        self.instr_id,
                    )
                    return
            else:
                logger.warning(
                    "MQTT Actor '%s' receives an unknown binary reply '%s' from the instrument '%s'",
                    self.globalName,
                    payload,
                    self.instr_id,
                )
                return
        else:
            logger.warning(
                "MQTT Actor '%s' receives an unknown message '%s' from the instrument '%s'",
                self.globalName,
                payload,
                self.instr_id,
            )
            return
