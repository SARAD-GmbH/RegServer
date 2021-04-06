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
import json
from enum import Enum, unique

import paho.mqtt.client as MQTT  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES, is_JSON

mqtt_req_status = Enum(
    "REQ_STATUS",
    (
        "idle",
        "send_reserve",
        "reserve_sent",
        "reserve_accepted",
        "reserve_refused",
        "illegal_reply",
    ),
)

mqtt_send_status = Enum(
    "SEND_STATUS", ("idle", "to_send", "sent", "send_replied", "illegal_reply")
)

logger.info("%s -> %s", __package__, __file__)


class MqttActor(DeviceBaseActor):
    """
    classdocs:
    Actor interacting with a new device
    """

    is_id: str

    instr_id: str

    mqtt_client_adr = None

    # "copy" ACCEPTED_COMMANDS of the DeviceBaseActor
    ACCEPTED_COMMANDS = DeviceBaseActor.ACCEPTED_COMMANDS
    # add some new accessible methods
    ACCEPTED_COMMANDS["PREPARE"] = "_prepare"

    def __init__(self):
        super().__init__()
        self.rc_conn = 2
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        self.allowed_sys_topics = {
            "CMD": "/cmd",
            "META": "/meta",
            "MSG": "/msg",
        }
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
            logger.info(
                f"Connection to MQTT self.mqtt_broker failed. result_code={result_code}"
            )
        else:
            logger.info("Connected with MQTT self.mqtt_broker.")
        # return self.result_code

    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        self.rc_disc = result_code
        if self.rc_disc == 1:
            logger.error(
                f"Disconnection from MQTT-broker failed. result_code={result_code}"
            )
        else:
            logger.info("Gracefully disconnected from MQTT-broker.")

    def on_publish(self, client, userdata, mid):
        self.rc_pub = 0
        logger.info(f"The message with Message-ID {mid} is published to the broker!")

    def on_subscribe(self, client, userdata, mid, grant_qos):
        self.rc_sub = 0
        logger.info("Subscribed to the topic successfully!")

    def on_unsubscribe(self, client, userdata, mid):
        self.rc_uns = 0
        logger.info("Unsubscribed to the topic successfully!")

    def on_message(self, client, userdata, message):
        topic_buf = {}
        payload_str = str(message.payload.decode("utf-8", "ignore"))
        logger.info(f"message received: {payload_str}")
        logger.info(f"message topic: {message.topic}")
        logger.info(f"message qos: {message.qos}")
        logger.info(f"message retain flag: {message.retain}")
        topic_buf = message.split("/")
        if (
            message.topic != self.allowed_sys_topics["META"]
            and message.topic != self.allowed_sys_topics["MSG"]
        ):
            logger.warning(
                f"[MQTT_Message]\tReceived an illegal message whose topic is illegal: topic is {message.topic} and payload is {message.payload}"
            )
        elif message.payload is None:
            logger.warning(
                f"[MQTT_Message]\tReceived an illegal message whose payload is none: topic is {message.topic} and payload is {message.payload}"
            )
            if (
                self.req_status == mqtt_req_status.reserve_sent
                and message.topic == self.allowed_sys_topics["META"]
            ):
                self.req_status = mqtt_req_status.illegal_reply
            if (
                self.send_status == mqtt_send_status.sent
                and message.topic == self.allowed_sys_topics["MSG"]
            ):
                self.send_status = mqtt_send_status.illegal_reply
        else:
            if topic_buf[2] == "meta":
                if self.req_status == mqtt_req_status.reserve_sent:
                    if (
                        message.payload.get("Reservation", None).get("Active", None)
                        == True
                    ):
                        self.req_status = mqtt_req_status.reserve_accepted
                    elif (
                        message.payload.get("Reservation", None).get("Active", None)
                        == False
                    ):
                        self.req_status = mqtt_req_status.reserve_refused
                    else:
                        logger.warning(
                            f"[MQTT_Message]\tReceived an illegal reply for the reservation request"
                        )
                        self.req_status = mqtt_req_status.illegal_reply
            elif topic_buf[2] == "msg":
                self.binary_reply = message.payload
                self.send_status = mqtt_send_status.send_replied
                logger.info(
                    f"[MQTT_Message]\tReceived a binary reply: {self.binary_reply}"
                )

    # Definition of methods accessible for the actor system and other actors -> referred to ACCEPTED_COMMANDS
    def _send(self, msg: dict):
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if (
            msg.get("PAR", None) is None
            or msg.get("PAR", None).get("Data", None) is None
            or msg.get("PAR", None).get("Host", None)
        ):
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        pub_req_msg["payload"] = {}
        pub_req_msg["payload"]["Data"] = msg.get("PAR", None).get("Data", None)
        pub_req_msg["payload"]["Host"] = msg.get("PAR", None).get("Host", None)
        pub_req_msg["qos"] = msg.get("PAR", None).get("qos", None)
        if pub_req_msg["qos"] is None:
            pub_req_msg["qos"] = 0
        self.send_status = mqtt_send_status.to_send
        send_status = self.__publish(
            {
                # "CMD": "PUBLISH",
                "PAR": {
                    "topic": self.allowed_sys_topics["CMD"],
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
            elif self.send_status == mqtt_send_status.illegal_reply:
                self.send_status = mqtt_send_status.idle
                return RETURN_MESSAGES.get("ILLEGAL_REPLY")
            else:
                time.sleep(0.01)  # check the send_status every 0.01s
                wait_cnt5 = wait_cnt5 - 1
        else:
            self.send_status = mqtt_send_status.idle
            return RETURN_MESSAGES.get("SEND_NO_REPLY")
        return {"RETURN": "OK", "PAR": self.binary_reply}

    def _reserve_at_is(self, msg):
        self.req_status = mqtt_req_status.send_reserve
        send_reserve_status = self.__publish(
            {
                # "CMD": "PUBLISH",
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
            elif self.req_status == mqtt_req_status.illegal_reply:
                self.req_status = mqtt_req_status.idle
                return RETURN_MESSAGES.get("ILLEGAL_REPLY")
            else:
                time.sleep(0.01)
                wait_cnt4 = wait_cnt4 - 1
        else:
            self.req_status = mqtt_req_status.idle
            return RETURN_MESSAGES.get("RESERVE_NO_REPLY")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _free(self, msg):
        logger.info("Free-Request")
        if msg is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.free_req_msg["Req"] = msg.get("Req", None)
        if self.free_req_msg["Req"] is None:
            self.free_req_msg["Req"] = "free"
        send_free_status = self.__publish(
            {
                # "CMD": "PUBLISH",
                "PAR": {
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
        self.__disconnect()
        super()._kill(msg)
        # TODO: clear the used memory space
        # TODO: let sender know this actor is killed

    def _prepare(self, msg: dict):
        self.is_id = msg.get("PAR", None).get("is_id", None)
        if self.is_id is None:
            logger.info("ERROR: No Instrument Server ID received!")
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        conn_re = self.__connect()
        logger.info(f"[CONN]\tThe client ({self.mqtt_cid}): {conn_re}")
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
            "PAR": {"topic": self.allowed_sys_topics["MSG"], "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": self.allowed_sys_topics["META"], "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("PREPARE_FAILURE")

        # TODO: set LWT message

        return RETURN_MESSAGES.get("OK_SKIPPED")

    # Definition of methods, namely __*(), not accessible for the actor system and other actors
    def __connect(self) -> dict:
        if self.globalName is None:
            return RETURN_MESSAGES.get("ILLEGAL_STATE")
        self.mqtt_cid = self.globalName + ".client"
        self.instr_id = self.globalName.split(".")[0]
        self.mqtt_broker = "localhost"
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

    def __disconnect(self) -> dict:
        logger.info("To disconnect from the MQTT-broker!")
        self.mqttc.disconnect()
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __publish(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        split_buf = self.mqtt_topic.split("/")
        if len(split_buf) != 3:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_payload = msg.get("PAR", None).get("payload", None)
        self.mqtt_qos = msg.get("PAR", None).get("qos", None)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)
        wait_cnt1 = 3
        while wait_cnt1 != 0:  # Wait only 3*2s = 6s
            if self.rc_pub == 1:
                time.sleep(2)
                wait_cnt1 = wait_cnt1 - 1
                logger.info("Waiting for the on_publish being called")
            else:
                self.rc_pub = 1
                break
        else:
            logger.info("on_publish not called: PUBLISH FAILURE!")
            return RETURN_MESSAGES.get("PUBLISH_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __subscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_qos = msg.get("PAR", None).get("qos", None)
        if self.mqtt_qos is None:
            self.mqtt_qos = 0
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)
        wait_cnt2 = 3
        while wait_cnt2 != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                wait_cnt2 = wait_cnt2 - 1
                logger.info("Waiting for the on_subscribe being called")
            else:
                self.rc_sub = 1
                break
        else:
            logger.info("on_subscribe not called: SUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("SUBSCRIBE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __unsubscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqttc.unsubscribe(self.mqtt_topic)
        wait_cnt3 = 3
        while wait_cnt3 != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                wait_cnt3 = wait_cnt3 - 1
                logger.info("Waiting for the on_unsubscribe being called")
            else:
                self.rc_uns = 1
                break
        else:
            logger.info("on_unsubscribe not called: UNSUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("UNSUBSCRIBE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")
