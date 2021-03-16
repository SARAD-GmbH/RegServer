"""
Created on 2021-02-16

@author: Yixiang
"""
import json
import logging

import os
import queue
import signal
import socket
import sys
import time
import traceback
from locale import str

import paho.mqtt.client  # type: ignore
import thespian

import yaml

# [???] Why? -- MS, 2021-03-16
# from curses.textpad import str
from _testmultiphase import Str, str_const
from appdirs import AppDirs  # type: ignore

# from builtins import None
from pip._internal.utils.compat import str_to_display
from registrationserver2 import theLogger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from registrationserver2.modules.mqtt.mqtt_client_actor import SARAD_MQTT_CLIENT

# [???] Why? -- MS, 2021-03-16
# from pip._vendor.urllib3.contrib._securetransport.low_level import _is_identity
# logger = logging.getLogger()

# [???] Why? -- MS, 2021-03-16
# from pylint.checkers.strings import str_eval
from thespian.actors import ActorAddress

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    self.ACCEPTED_MESSAGES[
        "MQTT_Message"
    ] = "__mqtt_message__"  # called when receive a MQTT message
    self.ACCEPTED_MESSAGES[
        "Property"
    ] = "__property_store__"  # called to store the properties of this MQTT Actor, like its name and the ID of the IS MQTT that it takes care of
    self.ACCEPTED_MESSAGES[
        "PREPARE"
    ] = "__prepare__"  # called after the Subscriber successfully sends the properties to this MQTT Actor

    """
    The receiveMessage() is defined in the DeviceBaseActor class.
    """

    def __send__(self, msg: dict):
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.pub_req_msg["topic"] = msg.get("topic", None)
        if self.pub_req_msg["topic"] is None:
            self.pub_req_msg["topic"] = "CMD"
        if self.pub_req_msg["topic"] != "CMD":
            self.pub_req_msg["topic"] = "CMD"

        self.pub_req_msg["payload"] = msg.get("payload", None)
        if self.pub_req_msg["payload"] is None:
            theLogger.info("ERROR: there is no payload of SARAD CMD!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["qos"] = msg.get("qos", None)
        if self.reserve_req_msg["qos"] is None:
            self.reserve_req_msg["qos"] = 0

        send_status = registrationserver2.actor_system.ask(
            SARAD_MQTT_CLIENT,
            {
                "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics[self.pub_req_msg["topic"]],
                    "payload": self.pub_req_msg["payload"],
                    "qos": self.reserve_req_msg["qos"],
                },
            },
        )

        return send_status

    def __send_reserve__(self, msg):
        theLogger.info("Reserve-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["Req"] = msg.get("Req", None)
        if self.free_req_msg["Req"] is None:
            self.free_req_msg["Req"] = "reserve"

        self.reserve_req_msg["App"] = msg.get("App", None)
        if self.reserve_req_msg["App"] is None:
            theLogger.info("ERROR: there is no App name!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["Host"] = msg.get("Host", None)
        if self.reserve_req_msg["Host"] is None:
            theLogger.info("ERROR: there is no host name!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["User"] = msg.get("User", None)
        if self.reserve_req_msg["User"] is None:
            theLogger.info("ERROR: there is no user name!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        send_reserve_status = registrationserver2.actor_system.ask(
            SARAD_MQTT_CLIENT,
            {
                "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": json.dump(self.reserve_req_msg),
                    "qos": 0,
                },
            },
        )
        return send_reserve_status

    def __send_free__(self, msg):
        theLogger.info("Free-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["Req"] = msg.get("Req", None)
        if self.free_req_msg["Req"] is None:
            self.free_req_msg["Req"] = "free"

        send_free_status = registrationserver2.actor_system.ask(
            SARAD_MQTT_CLIENT,
            {
                "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": json.dump(self.free_req_msg),
                    "qos": 0,
                },
            },
        )
        return send_free_status

    def __kill__(self, msg: dict):
        super().__kill__(msg)
        # TODO: clear the used memory space
        # TODO: let sender know this actor is killed

    def __property_store__(self):
        self.is_id = msg.get("Data", None).get("is_id", None)

        if self.is_id is None:
            theLogger.info("ERROR: No Instrument Server ID received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.instr_id = msg.get("Data", None).get("instr_id", None)

        if self.instr_id is None:
            theLogger.info("ERROR: No Instrument ID received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.actor_name = msg.get("Data", None).get("actor_name")
        if self.actor_name is None:
            theLogger.info("ERROR: No Actor N received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.actor_adr = msg.get("Data", None).get("actor_adr", None)
        if self.actor_adr is None:
            theLogger.info("ERROR: No Actor Address received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __prepare__(self):
        """theLogger.info('Now, this actor would do some prepare work')
        for i in range(2, 4):
            theLogger.info('To subsribe this topic: %s\n', self.sys_topic[i])
            self.mqttc.subscribe(self.sys_topic[i])
            time.sleep(2)
        theLogger.info('The prepare work is done!')
        """
        # Think Again: subscribe some necessary topics once a MQTT Actor is created
        subscribe_status = registrationserver2.actor_system.ask(
            SARAD_MQTT_CLIENT,
            {
                "CMD": "SUBSCRIBE",
                "Data": {"topic": self.allowed_sys_topics["MSG"], "qos": 0},
            },
        )
        if subscribe_status != RETURN_MESSAGES.get(
            "OK"
        ) and subscribe_status != RETURN_MESSAGES.get("OK_SKIPPED"):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        subscribe_status = registrationserver2.actor_system.ask(
            SARAD_MQTT_CLIENT,
            {
                "CMD": "SUBSCRIBE",
                "Data": {"topic": self.allowed_sys_topics["META"], "qos": 0},
            },
        )
        if subscribe_status != RETURN_MESSAGES.get(
            "OK"
        ) and subscribe_status != RETURN_MESSAGES.get("OK_SKIPPED"):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __mqtt_message__(self, msg):
        # TODO: handling MQTT messages
        pass

    def __init__(self):
        super.__init__()
        self.reserve_req_msg = (
            {  # how to get these information: App name, Host, User name???
                "Req": "reserve",
                "App": None,
                "Host": None,
                "User": None,
            }
        )  # default reserve-request
        self.free_req_msg = {"Req": "free"}  # default free-request
        self.is_id: str
        self.instr_id: str
        self.actor_name: str
        self.actor_adr: ActorAddress
        self.allowed_sys_topics = {
            "CMD": "/cmd",
            "META": "/meta",
            "CTRL": "/control",
            "MSG": "/msg",
        }
        self.pub_req_msg = {"topic": None, "payload": None, "qos": 0}
        self.sub_req_msg = {"topic": None, "qos": 0}
