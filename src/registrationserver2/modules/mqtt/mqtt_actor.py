"""
Created on 2021-02-16

@author: Yixiang
"""
import json

from registrationserver2 import actor_system, theLogger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES

theLogger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    is_id: str

    instr_id: str

    mqtt_client_adr = None

    # The receiveMessage() is defined in the DeviceBaseActor class, as well as
    # the ACCEPTED_MESSAGES.

    def _send(self, msg: dict):
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

    def _reserve(self, msg):
        super()._reserve(msg)
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

    def _free(self, msg):
        theLogger.info("Free-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.free_req_msg["Req"] = msg.get("Req", None)
        if self.free_req_msg["Req"] is None:
            self.free_req_msg["Req"] = "free"

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

    def _kill(self, msg: dict):
        super()._kill(msg)
        # TODO: clear the used memory space
        # TODO: let sender know this actor is killed

    def _prepare(self, msg: dict):
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

        """self.actor_name = msg.get("Data", None).get("actor_name")
        if self.actor_name is None:
            theLogger.info("ERROR: No Actor N received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        self.actor_adr = msg.get("Data", None).get("actor_adr", None)
        if self.actor_adr is None:
            theLogger.info("ERROR: No Actor Address received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        """
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

    def _binary_reply(self, msg):
        # TODO: transfer the binary reply to app/redirector actor
        theLogger.info(
            f"The binary reply ({msg.get('Data').get('payload')}) from the instrument ({msg.get('Data').get('instr_id')}) connected to the IS MQTT ({msg.get('Data').get('is_id')})"
        )
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __init__(self):
        super().__init__()
        self.reserve_req_msg = {}
        self.free_req_msg = {}
        self.pub_req_msg = {}
        self.sub_req_msg = {}
