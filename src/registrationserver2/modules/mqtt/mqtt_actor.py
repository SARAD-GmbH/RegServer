"""
Created on 2021-02-16

@author: Yixiang
"""
import json
from enum import Enum, unique

import paho.mqtt.client as MQTT  # type: ignore
from registrationserver2 import actor_system, theLogger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES, is_JSON
from enum import Enum

mqtt_req_status = Enum(
    "REQ_STATUS",
    ("idle", "send_reserve", "reserve_sent", "reserve_accepted", "reserve_refused"),
)

mqtt_send_status = Enum("SEND_STATUS", ("idle", "to_send", "sent", "send_replied"))

theLogger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    is_id: str

    instr_id: str

    mqtt_client_adr = None

    # "copy" ACCEPTED_MESSAGES of the DeviceBaseActor 
    ACCEPTED_MESSAGES = DeviceBaseActor.ACCEPTED_MESSAGES
    # add some new accessible methods
    ACCEPTED_MESSAGES["PREPARE"] = "__prepare__"
    
    def __init__(self):
        super().__init__()
        self.rc_conn = 2
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        self.req_status = mqtt_req_status.idle
        self.send_status = mqtt_send_status.idle
        self.binary_reply = b""
        self.mqtt_cid = self.globalName + ".client"
        self.instr_id = self.globalName.split("/")[1]
 
    # The receiveMessage() is defined in the DeviceBaseActor class

    # Definition of callback functions for the MQTT client, namely the on_* functions
    # these callback functions are called in the new thread that is created through loo_start() of Client()
    def on_connect(
        self, client, userdata, flags, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        self.rc_conn = result_code
        if self.rc_conn == 1:
            theLogger.info(
                "Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
            )
        else:
            theLogger.info("Connected with MQTT self.mqtt_broker.")
        # return self.result_code

    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        self.rc_disc = result_code
        if self.rc_disc == 1:
            theLogger.info(
                "Disconnection from MQTT-broker failed. result_code=%s", result_code
            )
        else:
            theLogger.info("Gracefully disconnected from MQTT-broker.")

    def on_publish(self, client, userdata, mid):
        self.rc_pub = 0
        theLogger.info(
            "The message with Message-ID %d is published to the broker!\n", mid
        )

    def on_subscribe(self, client, userdata, mid, grant_qos):
        self.rc_sub = 0
        theLogger.info("Subscribed to the topic successfully!\n")

    def on_unsubscribe(self, client, userdata, mid):
        self.rc_uns = 0
        theLogger.info("Unsubscribed to the topic successfully!\n")

    def on_message(self, client, userdata, message):
        topic_buf = {}
        payload_str = str(message.payload.decode("utf-8", "ignore"))
        theLogger.info(f"message received: {payload_str}")
        theLogger.info(f"message topic: {message.topic}")
        theLogger.info(f"message qos: {message.qos}")
        theLogger.info(f"message retain flag: {message.retain}")
        topic_buf = message.split("/")
        if len(topic_buf) !=3:
            theLogger.warning(f"[MQTT_Message]\tReceived an illegal message whose topic length is illegal: topic is {message.topic} and payload is {message.payload}")
        else:
            if topic_buf[0] != self.is_id or topic_buf[1] != self.instr_id:
                theLogger.warning(
                    f"[MQTT_Message]\tReceived illegal message: topic is {message.topic} and payload is {message.payload}"
                )
            else:
                if topic_buf[2] != "meta" and topic_buf[2] != "msg":
                    pass
                elif topic_buf[2] == "meta":
                    if self.req_status == mqtt_req_status.reserve_sent:
                        payload_json = is_JSON(payload_str)
                        if payload_json is None:
                            theLogger.warning(f"[MQTT_Message]\tReceived an illegal MQTT message in non-JSON format: topic is {message.topic} and payload is {payload_str}")
                        elif payload_json.get("Reservation", None).get("Active", None) == True:
                            self.req_status = mqtt_req_status.reserve_accepted
                        else:
                            self.req_status = mqtt_req_status.reserve_refused
                elif topic_buf[2] == "msg":
                    self.binary_reply = message.payload
                    if not (self.binary_reply is None): 
                        self.send_status = mqtt_send_status.send_replied
                    else:
                        theLogger.warning(f"[MQTT_Message]\tReceived an illegal binary reply that is empty: topic is {message.topic}")
                else:
                    theLogger.warning(
                        f"[MQTT_Message]\tReceived illegal message: topic is {message.topic} and payload is {message.payload}"
                    )

    # Definition of methods accessible for the actor system and other actors -> referred to ACCEPTED_COMMANDS
    def _send(self, msg: dict):
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        pub_req_msg["topic"] = msg.get("topic", None)
        if pub_req_msg["topic"] is None:
            pub_req_msg["topic"] = "CMD"
        if pub_req_msg["topic"] != "CMD":
            pub_req_msg["topic"] = "CMD"

        pub_req_msg["payload"] = msg.get("payload", None)
        if pub_req_msg["payload"] is None:
            theLogger.info("ERROR: there is no payload of SARAD CMD!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        pub_req_msg["qos"] = msg.get("qos", None)
        if pub_req_msg["qos"] is None:
            pub_req_msg["qos"] = 0
        self.send_status = mqtt_send_status.to_send
        send_status = self.__publish(
            {
                # "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics[pub_req_msg["topic"]],
                    "payload": pub_req_msg["payload"],
                    "qos": pub_req_msg["qos"],
                },
            }
        )
        if send_status is RETURN_MESSAGES.get("PUBLISH_FAILURE"):
            self.req_status = mqtt_req_status.idle
            return RETURN_MESSAGES.get("SEND_RESERVE_FAILURE")
        self.send_status = mqtt_send_status.sent
        wait_cnt5 = 2000
        while (
            wait_cnt5 != 0
        ):  # Wait max. 2000*0.01s = 20s -> check the reply in on_message()
            if self.send_status == mqtt_send_status.send_replied:
                self.send_status = mqtt_send_status.idle
                break
            else:
                time.sleep(0.01) # check the send_status every 0.01s
                wait_cnt5 = wait_cnt5 - 1
        else:
            self.send_status = mqtt_send_status.idle
            return RETURN_MESSAGES.get("SEND_NO_REPLY")
        return {"RETURN": "OK", "DATA": self.binary_reply}

    def _reserve(self, msg):
        super()._reserve(msg)
        self.req_status = mqtt_req_status.send_reserve
        send_reserve_status = self.__publish(
            {
                # "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": json.dump(self.reserve_req_msg),
                    "qos": 0,
                },
            }
        )
        if send_reserve_status is RETURN_MESSAGES.get("PUBLISH_FAILURE"):
            self.req_status = mqtt_req_status.idle
            return RETURN_MESSAGES.get("SEND_RESERVE_FAILURE")
        self.req_status = mqtt_req_status.reserve_sent
        wait_cnt4 = 2000
        while (
            wait_cnt4 != 0
        ):  # Wait max. 2000*0.01s = 20s -> check the reply in on_message()
            if self.req_status == mqtt_req_status.reserve_accepted:
                self.req_status = mqtt_req_status.idle
                break
            elif self.req_status == mqtt_req_status.reserve_refused:
                self.rc_conn = 2
                self.req_status = mqtt_req_status.idle
                return RETURN_MESSAGES.get("RESERVE_REFUSED")
            else:
                time.sleep(0.01)
                wait_cnt4 = wait_cnt4 - 1
        else:
            self.req_status = mqtt_req_status.idle
            return RETURN_MESSAGES.get("RESERVE_NO_REPLY")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _free(self, msg):
        theLogger.info("Free-Request\n")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.free_req_msg["Req"] = msg.get("Req", None)
        if self.free_req_msg["Req"] is None:
            self.free_req_msg["Req"] = "free"
        send_free_status = self.__publish(
            {
                # "CMD": "PUBLISH",
                "Data": {
                    "topic": self.allowed_sys_topics["CTRL"],
                    "payload": json.dump(self.free_req_msg),
                    "qos": 0,
                },
            }
        )
        if not (
            send_free_status is RETURN_MESSAGES.get("OK")
            or send_free_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("SEND_FREE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _kill(self, msg: dict):
        super()._kill(msg)
        # TODO: clear the used memory space
        # TODO: let sender know this actor is killed

    def _prepare(self, msg: dict):
        self.is_id = msg.get("Data", None).get("is_id", None)
        if self.is_id is None:
            theLogger.info("ERROR: No Instrument Server ID received!\n")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        conn_re = self.__connect()
        theLogger.info(f"[CONN]\tThe client ({self.mqtt_cid}): {_re}")
        if conn_re is RETURN_MESSAGES.get("OK_SKIPPED"):
            self.mqttc.loop_start()
        else:
            return conn_re
        for k in self.allowed_sys_topics.keys():
            self.allowed_sys_topics[k] = (
                self.is_id + "/" + self.instr_id + self.allowed_sys_topics[k]
            )
        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "Data": {"topic": self.allowed_sys_topics["MSG"], "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "Data": {"topic": self.allowed_sys_topics["META"], "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    # Definition of methods, namely __*(), not accessible for the actor system and other actors
    def __connect(self) -> dict:
        if self.globalName is None:
            return RETURN_MESSAGES.get("ILLEGAL_STATE")
        self.mqtt_cid = self.globalName + ".client"
        self.instr_id = self.globalName.split(".")[0]
        self.mqtt_broker = 'localhost'
        self.mqttc = MQTT.Client(self.mqtt_cid)
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        self.mqttc.connect(self.mqtt_broker)
        wait_cnt0 = 3
        while wait_cnt0 != 0:  # Wait only 3*2s = 6s
            if self.rc_conn == 0:
                self.rc_conn = 2
                break
            elif self.rc_conn == 1:
                self.rc_conn = 2
                return RETURN_MESSAGES.get("CONNECTION_FAILURE")
            else:
                time.sleep(2)
                wait_cnt0 = wait_cnt0 - 1
        else:
            return RETURN_MESSAGES.get("CONNECTION_NO_RESPONSE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __publish(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("Data", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_payload = msg.get("Data", None).get("payload", None)
        self.mqtt_qos = msg.get("Data", None).get("qos", None)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)
        wait_cnt1 = 3
        while wait_cnt1 != 0:  # Wait only 3*2s = 6s
            if self.rc_pub == 1:
                time.sleep(2)
                wait_cnt1 = wait_cnt1 - 1
                theLogger.info("Waiting for the on_publish being called\n")
            else:
                self.rc_pub = 1
                break
        else:
            theLogger.info("on_publish not called: PUBLISH FAILURE!\n")
            return RETURN_MESSAGES.get("PUBLISH_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __subscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("Data", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_qos = msg.get("Data", None).get("qos", None)
        if self.mqtt_qos is None:
            self.mqtt_qos = 0
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)
        wait_cnt2 = 3
        while wait_cnt2 != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                wait_cnt2 = wait_cnt2 - 1
                theLogger.info("Waiting for the on_subscribe being called\n")
            else:
                self.rc_sub = 1
                break
        else:
            theLogger.info("on_subscribe not called: SUBSCRIBE FAILURE!\n")
            return RETURN_MESSAGES.get("SUBSCRIBE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __unsubscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("Data", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqttc.unsubscribe(self.mqtt_topic)
        wait_cnt3 = 3
        while wait_cnt3 != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                wait_cnt3 = wait_cnt3 - 1
                theLogger.info("Waiting for the on_unsubscribe being called\n")
            else:
                self.rc_uns = 1
                break
        else:
            theLogger.info("on_unsubscribe not called: UNSUBSCRIBE FAILURE!\n")
            return RETURN_MESSAGES.get("UNSUBSCRIBE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")
