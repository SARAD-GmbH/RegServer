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
import time
import json
import queue
import paho.mqtt.client as MQTT  # type: ignore
#from _datetime import datetime
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
#from registrationserver2.modules.mqtt.mqtt_client_actor import MqttClientActor
from thespian.actors import (ActorExitRequest, ActorSystem,  # type: ignore
                             WakeupMessage)

logger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    
    @startuml
    actor "Service Employee" as user
    entity "Device with Instrument Server" as is_mqtt
    entity "MQTT Broker" as broker
    box "RegistrationServer MQTT"
    entity "SaradMqttSubscriber" as subscriber
    entity "MQTT Actor" as mqtt_actor
    entity "REST API" as rest_api
    entity "Redirector actor" as redirector
    database "Device List" as d_list
    end box
    
    group SETUP & PREPARE
        subscriber -> mqtt_actor : create a device actor to receive commands / data if the instrument server is_id is already added
        subscriber -> mqtt_actor : ask the mqtt actor to setup itself
        mqtt_actor -> d_list : create a description file for the instrument_id.SARAD_Type.mqtt and make a link to the file
        subscriber -> mqtt_actor : ask the mqtt actor to prepare itself for the future works
        mqtt_actor -> broker : prepare itself and connect to the broker
        mqtt_actor -> broker : unsubscribe to the topics "<is_id>/<instrument_id>/meta" and "<is_id>/<instrument_id>/reservation"
    end 
    
    group RESERVE
        is_mqtt -> broker : subscribe to topic "+/+/control"
        rest_api -> mqtt_actor : ask the mqtt actor to send a reservation request
        mqtt_actor -> broker : subscribe to the topic "<is_id>/<instrument_id>/reservation"
        mqtt_actor -> broker : publish "<is_id>/<instrument_id>/control = {"Req": "reserve", ...}"
        broker -> is_mqtt : rely the reservation request
        is_mqtt -> broker : publish "<is_id>/<instrument_id>/reservation = {"Active": True, ...}"
        is_mqtt -> broker : subscribe to the topic "<is_id>/<instrument_id>/cmd"
        broker -> mqtt_actor : rely the answer to the request
        mqtt_actor -> redirector : create a redirector and ask it to setup itself
    end 
    
    group SEND
        redirector -> mqtt_actor : ask the mqtt actor to send a binary command
        mqtt_actor -> broker : subscribe to topic "<is_id>/<instrument_id>/msg"
        mqtt_actor -> broker : publish "<is_id>/<instrument_id>/cmd = cmd_id + binary command"
        broker -> is_mqtt : rely the cmd
        is_mqtt -> broker : publish "<is_id>/<instrument_id>/msg = cmd_id + binary reply from the instrument"
        broker -> mqtt_actor : rely the reply
        mqtt_actor -> redirector : check the cmd_id and if right then send the binary reply to the redirector
    end 
    
    group FREE
        rest_api -> mqtt_actor : ask the mqtt actor to send free request
        mqtt_actor -> broker : publish "<is_id>/<instrument_id>/control = {"Req": "free"}"
        mqtt_actor -> broker : unsubscribe to the topics "<is_id>/<instrument_id>/reservation" and "<is_id>/<instrument_id>/msg"
        mqtt_actor -> redirector : destroy
        mqtt_actor -> rest_api : send "OK_SKIPPED" to the REST API
        broker -> is_mqtt : rely the request
        is_mqtt -> broker : unsubscribe to the topic "<is_id>/<instrument_id>/cmd"
    end 
    
    @enduml
    """

    # "copy" ACCEPTED_COMMANDS of the DeviceBaseActor
    ACCEPTED_COMMANDS = DeviceBaseActor.ACCEPTED_COMMANDS
    # add some new accessible methods
    ACCEPTED_COMMANDS["PREPARE"] = "_prepare"
    #ACCEPTED_COMMANDS["RESERVATION_CANCEL"] = "_reserve_cancel"
    ACCEPTED_COMMANDS["PARSE"] = "_parse"
    REPLY_TO_WAIT_FOR = {}

    @overrides
    def __init__(self):
        super().__init__()
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
        #self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"] = False # if matched, it is true
        self.REPLY_TO_WAIT_FOR["SEND"]["Reply"] =  None
        self.REPLY_TO_WAIT_FOR["SEND"][
            "Sender"
        ] = None  # store the address of the sender
        self.binary_reply = b""
        self.mqtt_broker = None
        self.port = None
        
        self.subscriber_addr = None
        self.cmd_id = 0
        
        self.mqtt_topic: str = ""
        self.mqtt_payload: str = ""
        self.lwt_payload = None
        self.lwt_topic = None
        self.lwt_qos = None
        self.mqtt_qos = 0
        self.retain = False

        # An queue to parse would store the mqtt messages when the client actor is at setup state
        self.queue_to_parse = queue.Queue()
        #self.work_state = "IDLE"
        self.ungr_disconn = 2
        #self.task_start_time = None
        self.error_code_switcher = {
            "SETUP": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
            "CONNECT": RETURN_MESSAGES["CONNECTION_FAILURE"]["ERROR_CODE"],
            "PUBLISH": RETURN_MESSAGES["PUBLISH_FAILURE"]["ERROR_CODE"],
            "SUBSCRIBE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"]["ERROR_CODE"],
            "UNSUBSCRIBE": RETURN_MESSAGES["UNSUBSCRIBE_FAILURE"]["ERROR_CODE"],
        } 
        """
        self.flag_switcher = {
            "CONNECT": None,
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "DISCONNECT": None,
            "UNSUBSCRIBE": None,
        } # store the flags that indicates whether its corresponding client activity is completed successfully or not
        """
        self.Is_Disconnected = None
        self.Is_Connected = None
        self.mid = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        } # store the current message ID to check

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
                    self.__mqtt_parser(msg, sender)
                #elif msg.payload == "Reserve":
                #    self._reserve_at_is(None, None, None)
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

        _msg = {
            "CMD": "SUBSCRIBE",
            "PAR": {"INFO": [(self.allowed_sys_topics["MSG"], 0)]},
        }
        _re = self._subscribe(_msg)
        logger.info(_re)
        if _re is None:
            logger.error(
                "Got no reply to subscription to the topic '%s'",
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
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "SEND", "ERROR_CODE": _re["ERROR_CODE"]}
            )
            return
        self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = True
        self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = bytes([self.cmd_id])
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
        if _re is None:
            logger.error(
                "Got no reply to publishing a message with an ID '%s' under the topic '%s'",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
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
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error(
                "Failed to publish a message with an ID '%s' under the topic '%s'",
                self.cmd_id,
                self.allowed_sys_topics["CMD"],
            )
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
            self.send(
                sender, {"RETURN": "SEND", "ERROR_CODE": _re["ERROR_CODE"]}
            )
            return
        '''
        wait_cnt = 70
        while wait_cnt >0:
            if self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"]:
                self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"] = False
                self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
                self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
                _re = {
                    "RETURN": "SEND",
                    "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                    "RESULT": {"DATA": self.REPLY_TO_WAIT_FOR["SEND"]["Reply"]},
                }
                self.send(sender, _re)
                return 
            time.sleep(0.01)
            wait_cnt = wait_cnt - 1
        else:
            logger.error("No reply to the command with ID = %s", self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"])
            self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
            self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
            return
        '''

    def _reserve_at_is(self, app, host, user) -> bool:
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
            if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.error(_re)
                return False
            _msg = {
                "CMD": "PUBLISH",
                "PAR": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": json.dumps({
                        "Req": "reserve",
                        "App": app,
                        "Host": host,
                        "User": user,
                    }),
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
                return False
            
        wait_cnt = 60
        while wait_cnt > 0:
            if self.REPLY_TO_WAIT_FOR.get("RESERVE", None).get("Active", None) is not None:
                if self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"]:
                    logger.info("Reservation allowed")
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = False
                    return True
                else:
                    logger.info("Reservation refused")
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
                    self.REPLY_TO_WAIT_FOR["RESERVE"]["Send_Status"] = False
                    return False
            wait_cnt = wait_cnt - 1
            time.sleep(0.01)
        else:
            logger.info("No reply to reservation request")
            self.REPLY_TO_WAIT_FOR["RESERVE"]["Active"] = None
            return False

    @overrides
    def _free(self, msg, sender) -> None:
        logger.info("Free-Request")
        if msg is None:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return
        free_req_msg = {}
        free_req_msg["Req"] = "free"
        _msg = {
            "CMD": "PUBLISH",
            "PAR": {
                "topic": self.allowed_sys_topics["CTRL"],
                "payload": free_req_msg,
                "qos": 0,
            },
        }
        _re = self._publish(_msg)
        logger.info(_re)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "FREE", "ERROR_CODE": _re["ERROR_CODE"]}
            )
            return
        logger.info(
            "[Free]\tThe MQTT actor '%s' is to unsusbcribe to the 'reserve' and 'msg' topics",
            self.globalName,
        )
        _msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": [
                    self.allowed_sys_topics["RESERVE"],
                    self.allowed_sys_topics["MSG"],
                ]
            },
        }
        _re = self._unsubscribe(_msg)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            self.send(
                sender, {"RETURN": "FREE", "ERROR_CODE": _re["ERROR_CODE"]}
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
        self._unsubscribe(ask_msg)
        time.sleep(1)
        super()._kill(msg, sender)
        # TODO: clear the used memory space
        # TODO: let others like the other actors and this actor's IS MQTT know this actor is killed

    def _prepare(self, msg: dict, sender):
        logger.info("Actor name = %s", self.globalName)
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
        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )
        logger.info(self.allowed_sys_topics)
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
        logger.info("Using the mqtt broker: %s", self.mqtt_broker)
        if self.port is None:
            self.port = 1883
        logger.info("Using the port: %s", self.port)
        self.lwt_topic = self.allowed_sys_topics["CTRL"]
        logger.info("LWT topic = %s", self.lwt_topic)
        self.lwt_payload = json.dumps({
                "Req": "free",
        })
        self.lwt_qos = 0
        _re = self._connect(True)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical(
                "Failed to setup the client actor because of failed connection. "
            )
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": _re["ERROR_CODE"],
                },
            )
            return
        logger.info("[CONN]: The client '%s': %s", self.mqtt_cid, _re)
        
        uns_msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": [self.allowed_sys_topics["MSG"], self.allowed_sys_topics["RESERVE"]],
            }
        }
        _re = self._unsubscribe(uns_msg)
        if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor because of failed unsubscription. Kill this client actor.")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": _re["ERROR_CODE"]})
            return
        
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
    
    def _parse(self, msg: dict, Sender) -> None:
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
                return
            logger.warning(
                "MQTT Actor '%s' receives a reply to an non-requested reservation on the instrument '%s'",
                self.globalName,
                self.instr_id,
            )
            return
        if topic == self.allowed_sys_topics["MSG"]:
            if self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"]:
                re_cmd_id = payload[0]
                if re_cmd_id == self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"]:
                    logger.info(
                        "MQTT Actor '%s' receives a binary reply '%s' from the instrument '%s'",
                        self.globalName,
                        payload[1:],
                        self.instr_id,
                    )
                    self.REPLY_TO_WAIT_FOR["SEND"]["Reply"] = payload[1:]
                    #self.REPLY_TO_WAIT_FOR["SEND"]["Reply_Status"] = True
                    _re = {
                        "RETURN": "SEND",
                        "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        "RESULT": {"DATA": self.REPLY_TO_WAIT_FOR["SEND"]["Reply"]},
                    }
                    self.send(self.REPLY_TO_WAIT_FOR["SEND"]["Sender"], _re)
                    self.REPLY_TO_WAIT_FOR["SEND"]["Send_Status"] = False
                    self.REPLY_TO_WAIT_FOR["SEND"]["Sender"] = None
                    self.REPLY_TO_WAIT_FOR["SEND"]["CMD_ID"] = None
                    self.REPLY_TO_WAIT_FOR["SEND"]["Reply"] = None
                    return
                logger.warning(
                    "MQTT Actor '%s' receives a binary reply '%s' with a unexpected CMD ID '%s' from the instrument '%s'",
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
    
    def on_connect(
        self, client, userdata, flags, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        logger.info("on_connect")
        #logger.info("work state = %s", self.work_state)
        if result_code == 0:
            logger.info("Connected with MQTT %s.", self.mqtt_broker)
            #self.flag_switcher["CONNECT"] = True
            #self.flag_switcher["DISCONNECT"] = False
            self.Is_Connected = True
            self.Is_Disconnected = False
        else:
            logger.info(
                "Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
            )
            #self.flag_switcher["CONNECT"] = False
            self.Is_Connected = False
    
    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
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
        #self.flag_switcher["DISCONNECT"] = True
        self.Is_Disconnected = True

    def on_publish(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_pub = 0
        logger.info("The message with Message-ID %d is published to the broker!\n", mid)
        """
        logger.info("work state = %s", self.work_state)
        if self.work_state == "PUBLISH":
            logger.info("Publish: check the mid")
            if mid == self.mid[self.work_state]:
                logger.info("Publish: mid is matched")
                self.flag_switcher[self.work_state] = True
        """
        logger.info("Publish: check the mid")
        if mid == self.mid["PUBLISH"]:
            logger.info("Publish: mid is matched")

    def on_subscribe(self, _client, _userdata, mid, _grant_qos):
        """Here should be a docstring."""
        # self.rc_sub = 0
        logger.info("on_subscribe")
        logger.info("mid is %s", mid)
        #logger.info("work state = %s", self.work_state)
        logger.info("stored mid is %s", self.mid["SUBSCRIBE"])
        if mid == self.mid["SUBSCRIBE"]:#if self.work_state == "SUBSCRIBE" and mid == self.mid["SUBSCRIBE"]:
            logger.info("Subscribed to the topic successfully!\n")
            #self.flag_switcher[self.work_state] = True

    def on_unsubscribe(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_uns = 0
        logger.info("on_unsubscribe")
        logger.info("mid is %s", mid)
        #logger.info("work state = %s", self.work_state)
        logger.info("stored mid is %s", self.mid["UNSUBSCRIBE"])
        if mid == self.mid["UNSUBSCRIBE"]: #if self.work_state == "UNSUBSCRIBE" and mid == self.mid["UNSUBSCRIBE"]:
            logger.info("Unsubscribed to the topic successfully!\n")
            #self.flag_switcher[self.work_state] = True

    def on_message(self, _client, _userdata, message):
        """Here should be a docstring."""
        logger.info("message received: %s", str(message.payload.decode("utf-8")))
        logger.info("message topic: %s", message.topic)
        logger.info("message qos: %s", message.qos)
        logger.info("message retain flag: %s", message.retain)
        msg_buf = {
            "CMD": "PARSE",
            "PAR": {
                "topic": message.topic,
                "payload": message.payload,
            }
        }
        self._parse(msg_buf, None)
        #ActorSystem().tell(self.myAddress, msg_buf)

                    
    def _connect(self, lwt_set: bool) -> dict:
        #self.work_state = "CONNECT"
        # logger.info("Work state: connect")
        self.mqttc = MQTT.Client(self.mqtt_cid)

        self.mqttc.reinitialise()

        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        """
        try:
            logger.info("Try to connect to the mqtt broker")
            if lwt_set:
                logger.info("Set will")
                self.mqttc.will_set(self.lwt_topic, payload=self.lwt_payload, qos=self.lwt_qos, retain=True)
            self.mqttc.connect(self.mqtt_broker, port=self.port)
            self.mqttc.loop_start()
            while True:
                if self.flag_switcher[self.work_state]:
                    self.send(self.ask_sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
                else:
                    self.send(self.ask_sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["CONNECT"]})
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
            #self.task_start_time = time.time()
        except:
            logger.error("Failed to connect to the given broker and port")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": self.error_code_switcher["CONNECT"]})
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        """
        logger.info("Try to connect to the mqtt broker")
        if lwt_set:
            logger.info("Set will")
            self.mqttc.will_set(
                self.lwt_topic, payload=self.lwt_payload, qos=self.lwt_qos, retain=True
            )
        self.mqttc.connect(self.mqtt_broker, port=self.port)
        self.mqttc.loop_start()
        while True:
            if self.Is_Connected is not None:
                if self.Is_Connected:
                    _re = {
                        "RETURN": "CONNECT",
                        "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                    }
                    break
                elif not self.Is_Connected:
                    _re = {
                        "RETURN": "CONNECT",
                        "ERROR_CODE": self.error_code_switcher["CONNECT"],
                    }
                    break
        #self.work_state = "STANDBY"
        return _re

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.info("Already disconnected")
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("Disconnection gracefully: %s", RETURN_MESSAGES.get("OK_SKIPPED"))

    def _publish(self, msg: dict) -> dict:
        #self.work_state = "PUBLISH"
        logger.info("Work state: publish")
        if self.Is_Disconnected:
            logger.warning("Failed to publish the message because of disconnection")
            _re = {
                "RETURN": "PUBLISH",
                "ERROR_CODE": self.error_code_switcher["PUBLISH"],
            }
            self._connect(True)
            #self.work_state = "STANDBY"
            return _re
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if (self.mqtt_topic is None) or not isinstance(self.mqtt_topic, str):
            logger.warning("the topic is none or not a string")
            _re = {
                "RETURN": "PUBLISH",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
        else:
            self.mqtt_payload = msg.get("PAR", None).get("payload", None)
            self.mqtt_qos = msg.get("PAR", None).get("qos", None)
            self.retain = msg.get("PAR", None).get("retain", None)
            if self.retain is None:
                self.retain = False
            logger.info("To publish")
            rc, self.mid["PUBLISH"] = self.mqttc.publish(
                self.mqtt_topic,
                payload=self.mqtt_payload,
                qos=self.mqtt_qos,
                retain=self.retain,
            )
            if rc != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Publish failed; result code is: %s", rc)
                _re = {
                    "RETURN": "PUBLISH",
                    "ERROR_CODE": self.error_code_switcher["PUBLISH"],
                }
            else:
                _re = {
                    "RETURN": "PUBLISH",
                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                }
                """
                self.task_start_time = time.monotonic()
                while True:
                    # logger.info("while-loop: work state = %s", self.work_state)
                    # logger.info("while-loop: %s's flag = %s", self.work_state, self.flag_switcher[self.work_state])
                    if time.monotonic() - self.task_start_time <= 0.3:
                        if self.flag_switcher[self.work_state] is not None:
                            if self.flag_switcher[self.work_state]:
                                _re = {
                                    "RETURN": self.work_state,
                                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                                        "ERROR_CODE"
                                        ],
                                }
                                self.flag_switcher[self.work_state] = None
                                break
                            if not self.flag_switcher[self.work_state]:
                                _re = {
                                    "RETURN": self.work_state,
                                    "ERROR_CODE": self.error_code_switcher[self.work_state],
                                }
                                self.flag_switcher[self.work_state] = None
                                break
                    else:
                        _re = {
                            "RETURN": self.work_state,
                            "ERROR_CODE": self.error_code_switcher[self.work_state],
                        }
                        self.flag_switcher[self.work_state] = None
                        break
                """

        #self.work_state = "STANDBY"
        return _re

    def _subscribe(self, msg: dict) -> None:
        #self.work_state = "SUBSCRIBE"
        logger.info("Work state: subscribe")
        if self.Is_Disconnected:
            logger.warning(
                "Failed to subscribe to the topic(s) because of disconnection"
            )
            _re = {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["SUBSCRIBE"],
            }
            self._connect(True)
            #self.work_state = "STANDBY"
            # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return _re
        sub_info = msg.get("PAR", None).get("INFO", None)
        if sub_info is None:
            logger.warning("[Subscribe]: the INFO for subscribe is none")
            _re = {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
            #self.work_state = "STANDBY"
            # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return _re
        if isinstance(sub_info, list):
            for ele in sub_info:
                if not isinstance(ele, tuple):
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list "
                        "while it contains a non-tuple element"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    #self.work_state = "STANDBY"
                    # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return _re
                if len(ele) != 2:
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list while it contains "
                        "a tuple elemnt whose length is not equal to 2"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    #self.work_state = "STANDBY"
                    # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return _re
                if len(ele) == 2 and ele[0] is None:
                    logger.warning(
                        "[Subscribe]: the first element of one tuple namely the 'topic' is None"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    #self.work_state = "STANDBY"
                    # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return _re
            rc, self.mid["SUBSCRIBE"] = self.mqttc.subscribe(sub_info)
            if rc != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Subscribe failed; result code is: %s", rc)
                _re = {
                    "RETURN": "SUBCRIBE",
                    "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"][
                        "ERROR_CODE"
                        ],
                }
            else:
                _re = {
                    "RETURN": "SUBSCRIBE",
                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                        "ERROR_CODE"
                        ],
                }
                """
                self.task_start_time = time.monotonic()
                while True:
                    if time.monotonic() - self.task_start_time <= 0.3:
                        if self.flag_switcher[self.work_state] is not None:
                            if self.flag_switcher[self.work_state]:
                                _re = {
                                    "RETURN": self.work_state,
                                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                                        "ERROR_CODE"
                                        ],
                                }
                                self.flag_switcher[self.work_state] = None
                                break
                            if not self.flag_switcher[self.work_state]:
                                _re = {
                                    "RETURN": self.work_state,
                                    "ERROR_CODE": self.error_code_switcher[self.work_state],
                                }
                                self.flag_switcher[self.work_state] = None
                                break
                    else:
                        _re = {
                            "RETURN": self.work_state,
                            "ERROR_CODE": self.error_code_switcher[self.work_state],
                        }
                        self.flag_switcher[self.work_state] = None
                        break
                """
            #self.work_state = "STANDBY"
            return _re

    def _unsubscribe(self, msg: dict) -> dict:
        #self.work_state = "UNSUBSCRIBE"
        self.mqtt_topic = msg.get("PAR", None).get("INFO", None)
        logger.info(self.mqtt_topic)
        if self.Is_Disconnected:
            logger.warning(
                "Failed to unsubscribe to the topic(s) because of disconnection"
            )
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
            self._connect(True)
            #self.work_state = "STANDBY"
            # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return _re
        if (
            self.mqtt_topic is None
            and not isinstance(self.mqtt_topic, list)
            and not isinstance(self.mqtt_topic, str)
        ):
            logger.warning(
                "[Unsubscribe]: The topic is none or it is neither a string nor a list "
            )
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
            #self.work_state = "STANDBY"
            # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return _re
        rc, self.mid["UNSUBSCRIBE"] = self.mqttc.unsubscribe(self.mqtt_topic)
        if rc != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Unsubscribe failed; result code is: %s", rc)
            _re = {
                "RETURN": "UNSUBCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
            #self.work_state = "STANDBY"
        else:
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                    "ERROR_CODE"
                    ],
            }
            """
            self.task_start_time = time.monotonic()
            while True:
                if time.monotonic() - self.task_start_time <= 0.3:
                    if self.flag_switcher[self.work_state] is not None:
                        if self.flag_switcher[self.work_state]:
                            _re = {
                                "RETURN": self.work_state,
                                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                                "ERROR_CODE"
                                ],
                            }
                            self.flag_switcher[self.work_state] = None
                            break
                        if not self.flag_switcher[self.work_state]:
                            _re = {
                                "RETURN": self.work_state,
                                "ERROR_CODE": self.error_code_switcher[self.work_state],
                            }
                            self.flag_switcher[self.work_state] = None
                            break
                else:
                    _re = {
                        "RETURN": self.work_state,
                        "ERROR_CODE": self.error_code_switcher[self.work_state],
                    }
                    self.flag_switcher[self.work_state] = None
                    break
            """
        #self.work_state = "STANDBY"
        # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        return _re
        
