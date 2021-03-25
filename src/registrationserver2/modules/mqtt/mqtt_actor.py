"""
Created on 2021-02-16

@author: Yixiang
"""
import json
import logging
# import sys
# import time
# import traceback
from locale import str
#import thespian
#import yaml

from registrationserver2 import theLogger, actor_system
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
#from _testmultiphase import Str, str_const

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    ACCEPTED_MESSAGES = {
        # Those needs implementing
        "SEND": "__send__",  # is being called when the end-user-application wants to send data, should return the direct or indirect response from the device, None in case the device is not reachable (so the end application can set the timeout itself)
        "SEND_RESERVE": "__send_reserve__",  # is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible
        "SEND_FREE": "__send_free__", # called to send free request to a reserved instrument
        "BINARY_REPLY": "__binary_reply__", # called when receive a MQTT message
        "PREPARE": "__prepare__",  # called after this actor has successfully setup
        # implemented by the base class (DeviceBaseActor class)
        "ECHO": "__echo__",  # should returns what is send, main use is for testing purpose at this point
        "FREE": "__free__",  # is being called when the end-user-application is done requesting / sending data, should return true as soon the freeing process has been initialized
        "SETUP": "__setup__",
        "RESERVE": "__reserve__",
        "KILL": "__kill__",
    }
    
    is_id : str
    
    instr_id : str
    
    mqtt_client_adr = None

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

        send_status = actor_system.ask(
            self.mqtt_client_adr,
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

    def __send_reserve__(self, msg:dict)->dict:
        super().__send_reserve__(msg)
        theLogger.info("Reserve-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["Req"] = msg.get("Req", None)
        #if self.reserve_req_msg["Req"] is None:
        #    self.reserve_req_msg["Req"] = "reserve"

        self.reserve_req_msg["App"] = msg.get("App", None)
        #if self.reserve_req_msg["App"] is None:
        #    theLogger.info("ERROR: there is no App name!\n")
        #    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["Host"] = msg.get("Host", None)
        #if self.reserve_req_msg["Host"] is None:
        #    theLogger.info("ERROR: there is no host name!\n")
        #    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.reserve_req_msg["User"] = msg.get("User", None)
        #if self.reserve_req_msg["User"] is None:
        #    theLogger.info("ERROR: there is no user name!\n")
        #    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        send_reserve_status = actor_system.ask(
            self.mqtt_client_adr,
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
        #if msg is None:
        #    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["Req"] = msg.get("Req", None)
        #if self.free_req_msg["Req"] is None:
        #    self.free_req_msg["Req"] = "free"

        send_free_status = actor_system.ask(
            self.mqtt_client_adr,
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

    def __prepare__(self, msg:dict):
        self.is_id = msg.get("Data", None).get("is_id", None)
        if self.is_id is None:
            theLogger.info("ERROR: No Instrument Server ID received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.instr_id = msg.get("Data", None).get("instr_id", None)
        if self.instr_id is None:
            theLogger.info("ERROR: No Instrument ID received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        
        self.mqtt_client_adr = msg.get("Data", None).get("mqtt_client_adr", None)
        if self.mqtt_client_adr is None:
            theLogger.info("ERROR: No MQTT client address received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        '''self.actor_name = msg.get("Data", None).get("actor_name")
        if self.actor_name is None:
            theLogger.info("ERROR: No Actor N received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        
        self.actor_adr = msg.get("Data", None).get("actor_adr", None)
        if self.actor_adr is None:
            theLogger.info("ERROR: No Actor Address received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        '''
        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )
        self.sub_req_msg = {
            "CMD": "SUBSCRIBE",
            "Data": {"topic": self.allowed_sys_topics["MSG"], "qos": 0},
        }
        subscribe_status = actor_system.ask(self.mqtt_client_adr, self.sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK") 
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")
        
        self.sub_req_msg = {
            "CMD": "SUBSCRIBE",
            "Data": {"topic": self.allowed_sys_topics["META"], "qos": 0},
        }
        subscribe_status = actor_system.ask(self.mqtt_client_adr, self.sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK") 
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __binary_reply__(self, msg):
        # TODO: transfer the binary reply to app/redirector actor
        theLogger.info(f"The binary reply ({msg.get('Data').get('payload')}) from the instrument ({msg.get('Data').get('instr_id')}) connected to the IS MQTT ({msg.get('Data').get('is_id')})")
        return RETURN_MESSAGES.get("OK_SKIPPED")
    
    def __init__(self):
        super().__init__()
        self.reserve_req_msg = {}
        self.free_req_msg = {}
        self.pub_req_msg = {}
        self.sub_req_msg = {}
