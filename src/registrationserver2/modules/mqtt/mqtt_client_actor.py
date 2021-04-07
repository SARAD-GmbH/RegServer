'''
import logging
import time
import os
import sys
# import queue
import json
#import yaml
import signal
import threading
import traceback
import paho.mqtt.client  as MQTT# type: ignore

import registrationserver2
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from registrationserver2.modules.mqtt import MQTT_ACTOR_ADRs
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from registrationserver2.modules.mqtt.mqtt_subscriber import SaradMqttSubscriber
from thespian.actors import ActorSystem  # type: ignore

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


class SaradMqttClient(object):

    mqtt_topic: str

    mqtt_payload: str

    mqtt_qos = 0

    mqtt_broker: str  # MQTT Broker, here: localhost

    mqtt_cid: str  # MQTT Client ID

    __folder_history: str

    __folder_available: str

    __lock = threading.Lock()

    def on_connect(
        self, client, userdata, flags, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        self.rc_conn = result_code
        if self.rc_conn == 1:
            logger.info(
                "Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
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
            logger.info(
                "Disconnection from MQTT-broker failed. result_code=%s", result_code
            )
        else:
            logger.info("Gracefully disconnected from MQTT-broker.")

    def on_publish(self, client, userdata, mid):
        self.rc_pub = 0
        logger.info(
            "The message with Message-ID %d is published to the broker!\n", mid
        )

    def on_subscribe(self, client, userdata, mid, grant_qos):
        self.rc_sub = 0
        logger.info("Subscribed to the topic successfully!\n")

    def on_unsubscribe(self, client, userdata, mid):
        self.rc_uns = 0
        logger.info("Unsubscribed to the topic successfully!\n")

    def on_message(self, client, userdata, message):
        self.topic_parts = []

        print("message received " ,str(message.payload.decode("utf-8")))
        print("message topic=",message.topic)
        print("message qos=",message.qos)
        print("message retain flag=",message.retain)

        self.topic_parts = message.topic.split("/")

        self.len = len(self.topic_parts)

        if self.len == 2:
            self.send(
                SARAD_MQTT_CLIENT,
                {
                    "CMD": "MQTT_Message",
                    "Data": {
                        "msg_type": self.topic_parts[1],
                        "payload": str(message.payload.decode("utf-8")),
                        "qos": str(message.qos.decode("utf-8")),
                    },
                },
            )
        elif self.len == 3:
            if self.topic_parts[2] == "connected":
                self.send(
                    SARAD_MQTT_CLIENT,
                    {
                        "CMD": "MQTT_Message",
                        "Data": {
                            "msg_type": self.topic_parts[2],
                            "payload": str(message.payload.decode("utf-8")),
                            "qos": str(message.qos.decode("utf-8")),
                        },
                    },
                )
            elif self.topic_parts[2] == "msg" or self.topic_parts[2] == "meta":
                self.send(
                    MQTT_ACTOR_ADRs.get(self.topic_parts[1]),
                    {
                        "CMD": "MQTT_Message",
                        "Data": {
                            "msg_type": self.topic_parts[2],
                            "payload": str(
                                message.payload.decode("utf-8")
                            ),  # byte-string or a string???
                            "qos": str(message.qos.decode("utf-8")),
                        },
                    },
                )
                # TODO: regarding how the byte-string is sent via MQTT;
                # in another word, for example, if the IS MQTT sends a byte-string,
                # would this MQTT Client Actor receives a byte-string or a string?
            else:
                logger.info(
                    'Receive unknown message "%s" under the topic "%"',
                    str(message.payload.decode("utf-8")),
                    str(message.topic.decode("utf-8")),
                )
        else:
            logger.info(
                'Receive unknown message "%s" under the topic "%"',
                str(message.payload.decode("utf-8")),
                str(message.topic.decode("utf-8")),
            )

    def _add_instr(self, instr_id : str, msg)->dict:
        with self.__lock:
            logger.info(f"[Add]:\tFound: A new connected instrument with instrument ID : {instr_id}")
            filename = fr"{self.__folder_history}{instr_id}"
            link = fr"{self.__folder_available}{instr_id}"
            try:
                data = msg
                if data:
                    with open(filename, "w+") as file_stream:
                        file_stream.write(data) if data else logger.error(
                            f"[Add]:\tFailed to get Properties from {msg}, {instr_id}"
                        )  # pylint: disable=W0106
                    if not os.path.exists(link):
                        logger.info(f"Linking {link} to {filename}")
                        os.link(filename, link)
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    f'[Add]:\t {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
                )
            except:  # pylint: disable=W0702
                logger.error(
                    f"[Add]:\tCould not write properties of device with ID: {instr_id}"
                )
            # if an actor already exists this will return
            # the address of the excisting one, else it will create a new one
            if data:
                this_actor = ActorSystem().createActor(
                    MqttActor, globalName=instr_id
                )
                setup_return = ActorSystem().ask(
                    this_actor, {"CMD": "SETUP"}
                )
                logger.info(setup_return)
                if setup_return is RETURN_MESSAGES.get("OK"):
                    logger.info(
                        ActorSystem().ask(
                            this_actor,
                            {"CMD": "SEND", "DATA": b"\x42\x80\x7f\x0c\x0c\x00\x45"},
                        )
                    )
                if not (
                    setup_return is RETURN_MESSAGES.get("OK")
                    or setup_return is RETURN_MESSAGES.get("OK_SKIPPED")
                ):
                    ActorSystem().ask(this_actor, {"CMD": "KILL"})

    def _connect(self, msg: dict) -> dict:
        self.mqtt_cid = msg.get("Data", None).get("client_id", None)

        if self.mqtt_cid is None:
            return RETURN_MESSAGES.get("ILLEGAL_STATE")

        self.mqtt_broker = msg.get("Data", None).get("mqtt_broker", None)

        if self.mqtt_broker is None:
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

        self.wait_cnt = 3

        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_conn == 0:
                self.rc_conn = 2
                break
            elif self.rc_conn == 1:
                self.rc_conn = 2
                return RETURN_MESSAGES.get("CONNECTION_FAILURE")
            else:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
        else:
            return RETURN_MESSAGES.get("CONNECTION_NO_RESPONSE")

        self.mqttc.loop_start()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _disconnect(self, msg: dict) -> dict:
        logger.info("To disconnect from the MQTT-broker!\n")
        self.mqttc.disconnect()
        logger.info("To stop the MQTT thread!\n")
        self.mqttc.loop_stop()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _publish(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("Data", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_payload = msg.get("Data", None).get("payload", None)
        self.mqtt_qos = msg.get("Data", None).get("qos", None)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)
        self.wait_cnt = 3

        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_pub == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
                logger.info("Waiting for the on_publish being called\n")
            else:
                self.rc_pub = 1
                break
        else:
            logger.info("on_publish not called: PUBLISH FAILURE!\n")
            return RETURN_MESSAGES.get("PUBLISH_FAILURE")

        self.mqttc.loop_start()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _subscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_qos = msg.get("qos", None)
        if self.mqtt_qos is None:
            self.mqtt_qos = 0
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)
        self.wait_cnt = 3

        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
                logger.info("Waiting for the on_subscribe being called\n")
            else:
                self.rc_sub = 1
                break
        else:
            logger.info("on_subscribe not called: SUBSCRIBE FAILURE!\n")
            return RETURN_MESSAGES.get("SUBSCRIBE_FAILURE")

        self.mqttc.loop_start()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _unsubscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqttc.unsubscribe(self.mqtt_topic)
        self.wait_cnt = 3

        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
                logger.info("Waiting for the on_unsubscribe being called\n")
            else:
                self.rc_uns = 1
                break
        else:
            logger.info("on_unsubscribe not called: UNSUBSCRIBE FAILURE!\n")
            return RETURN_MESSAGES.get("UNSUBSCRIBE_FAILURE")

        self.mqttc.loop_start()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    # * Handling of Ctrl+C:
    def signal_handler(self, sig, frame):  # pylint: disable=unused-argument
        """On Ctrl+C:
        - stop all cycles
        - disconnect from MQTT self.mqtt_broker"""
        logger.info("You pressed Ctrl+C!\n")
        self.mqttc.disconnect()
        self.mqttc.loop_stop()
        sys.exit(0)

    signal.signal(
        signal.SIGINT, signal_handler
    )  # SIGINT: By default, interrupt is Ctrl+C

    def __init__(self):
        self.rc_conn = 2
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        self.SARAD_MQTT_SUBSCRIBER = ActorSystem().createActor(
            SaradMqttSubscriber, globalName="MQTT_SUBSCRIBER"
        )
        with self.__lock:
            self.__folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
            self.__folder_available = (
                f"{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}"
            )
            if not os.path.exists(self.__folder_history):
                os.makedirs(self.__folder_history)
            if not os.path.exists(self.__folder_available):
                os.makedirs(self.__folder_available)

            logger.debug(f"Output to: {self.__folder_history}")
        setup_return = ActorSystem().ask(self.SARAD_MQTT_SUBSCRIBER, "SETUP")
        if setup_return == RETURN_MESSAGES.get("OK"):
            logger.info("SARAD MQTT Subscriber is setup correctly!\n")
        else:
            logger.warning("SARAD MQTT Subscriber is not setup!\n")
#SARAD_MQTT_CLIENT: ActorAddress = ActorSystem().createActor(
#    SaradMqttClient, type(SaradMqttClient).__name__
#)
'''
# Plan A:
# SARAD_MQTT_CLIENT = ActorSystem().createActor(SaradMqttClient, globalName="sarad_mqtt_client")
# Plan B:
# SARAD_MQTT_CLIENT: ActorAddress = ActorSystem().createActor(
#    SaradMqttClient, globalName=type(SaradMqttClient).__name__
# )
"""
def test():
    connect_status = ActorSystem().ask(SARAD_MQTT_CLIENT, {"CMD" : "CONNECT", "Data" : {"client_id" : "Test_client1", "mqtt_broker" : "localhost"}})
    print (connect_status)
    input("Press Enter to End\n")
    logger.info("!")

if __name__ == "__main__":
    test()
"""
