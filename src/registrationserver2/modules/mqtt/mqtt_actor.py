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
from registrationserver2.modules.mqtt.mqtt_client_actor import \
    SARAD_MQTT_CLIENT

# [???] Why? -- MS, 2021-03-16
# from pip._vendor.urllib3.contrib._securetransport.low_level import _is_identity
# logger = logging.getLogger()

# [???] Why? -- MS, 2021-03-16
# from pylint.checkers.strings import str_eval


logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    ACCEPTED_MESSAGES = {
        # Implemented in this class
        "SEND": "__send__",  # is being called when the end-user-application wants to send data, should return the direct or indirect response from the device, None in case the device is not reachable (so the end application can set the timeout itself)
        "SEND_RESERVE": "__send_reserve__",  # is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible
        "SEND_FREE": "__send_free__",  # called to free the reservation
        "MQTT_Message": "__mqtt_message__",  # called when receive a MQTT message
        "Property": "__property_store__",  # called to store the properties of this MQTT Actor, like its name and the ID of the IS MQTT that it takes care of
        # Those are implemented by the base class (DeviceBaseActor)
        "ECHO": "__echo__",  # should returns what is send, main use is for testing purpose at this point
        "FREE": "__free__",  # is being called when the end-user-application is done requesting / sending data, should return true as soon the freeing process has been initialized
        "SETUP": "__setup__",
        "RESERVE": "__reserve__",
        "KILL": "__kill__",
    }
    """
    The receiveMessage() is defined in the DeviceBaseActor class.
    """

    def __send__(self, msg: dict):
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.pub_req_msg["topic"] = msg.get("topic", None)
        if self.pub_req_msg["topic"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if self.pub_req_msg["topic"] != "CMD":
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.pub_req_msg["payload"] = msg.get("payload", None)
        if self.pub_req_msg["payload"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["qos"] = msg.get("qos", None)

        send_satus = registrationserver2.actor_system.ask(
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
        return send_satus

    def __send_reserve__(self, msg):
        theLogger.info("Reserve-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["App"] = msg.get("App", None)
        if self.reserve_req_msg["App"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["Host"] = msg.get("Host", None)
        if self.reserve_req_msg["Host"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["User"] = msg.get("User", None)
        if self.reserve_req_msg["User"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        send_reserve_satus = registrationserver2.actor_system.ask(
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
        return send_reserve_satus

    def __send_free__(self, msg):
        theLogger.info("Free-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["App"] = msg.get("App", None)
        if self.free_req_msg["App"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["Host"] = msg.get("Host", None)
        if self.free_req_msg["Host"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["User"] = msg.get("User", None)
        if self.free_req_msg["User"] is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        send_free_satus = registrationserver2.actor_system.ask(
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
        return send_free_satus

    def __kill__(self, msg: dict):
        super().__kill__(msg)
        # TODO: clear the used memory space

    def __property_store__(self):
        self.is_id = msg.get("Data", None).get("is_id", None)

        if self.is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.instr_id = msg.get("Data", None).get("instr_id", None)

        if self.instr_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def pre_work(self):
        """theLogger.info('Now, this actor would do some prepare work')
        for i in range(2, 4):
            theLogger.info('To subsribe this topic: %s\n', self.sys_topic[i])
            self.mqttc.subscribe(self.sys_topic[i])
            time.sleep(2)
        theLogger.info('The prepare work is done!')
        """
        # TODO: subscribe some necessary topics once a MQTT Actor is created
        pass

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

        self.free_req_msg = {
            "Req": "free",
            "App": None,
            "Host": None,
            "User": None,
        }  # default free-request
        self.is_id: str
        self.instr_id: str
        self.allowed_sys_topics = {
            "CMD": "/cmd",
            "META": "/meta",
            "CTRL": "/control",
            "MSG": "/msg",
        }
        self.pub_req_msg = {"topic": None, "payload": None, "qos": 0}
        self.sub_req_msg = {"topic": None, "qos": 0}
