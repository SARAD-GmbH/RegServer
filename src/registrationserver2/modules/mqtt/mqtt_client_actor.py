import time
import os
import sys
import json
import queue
import datetime
import paho.mqtt.client  as MQTT# type: ignore
from overrides import overrides  # type: ignore
from thespian.actors import Actor, ActorSystem, ActorExitRequest, WakeupMessage  # type: ignore
#import registrationserver2
from registrationserver2 import logger
#from registrationserver2.config import config
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES
from pickle import TRUE

logger.info("%s -> %s", __package__, __file__)

#mqtt_msg_queue = queue.Queue()

class MqttClientActor(Actor):
    ACCEPTED_COMMANDS = {
        "KILL": "_kill",
        "SETUP": "_setup",
        #"CONNECT": "_connect",
        "PUBLISH": "_publish",
        "SUBSCRIBE": "_subscribe",
        "UNSUBSCRIBE": "_unsubscribe",
    }
    ACCEPTED_RETURNS = {
        #"SEND": "_receive_loop",
    }

    mqtt_topic: str

    mqtt_payload: str

    mqtt_qos = 0
    
    retain = False

    mqtt_broker = None  # MQTT Broker, here: localhost
    
    port = None

    mqtt_cid: str  # MQTT Client ID
    
    queue_to_parse = queue.Queue() # An queue to parse would store the mqtt messages when the client actor is at setup state
    
    @overrides
    def __init__(self):
        super().__init__()
        self.myParent = None
        self.work_state = "IDLE"
        self.ungr_disconn = 2
        self.task_start_time = {
            #"CONNECT": None,
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }
        self.error_code_switcher = {
            "SETUP": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
            "CONNECT": RETURN_MESSAGES["CONNECT_FAILURE"]["ERROR_CODE"],
            "PUBLISH": RETURN_MESSAGES["PUBLISH_FAILURE"]["ERROR_CODE"],
            "SUBSCRIBE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"]["ERROR_CODE"],
            "UNSUBSCRIBE": RETURN_MESSAGES["UNSUBSCRIBE_FAILURE"]["ERROR_CODE"],
        }
        self.flag_switcher = {
            "CONNECT": None,
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }
        self.mid = {
            "PUBLISH": None,
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }
    
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
                if self.work_state == "IDLE" and cmd_key == "SETUP":
                    self.myParent = sender
                else:
                    #if self.myParent is None:
                    #    logger.info("The client actor is not setup because there is no parent actor for it. Then it will kill itself.")
                    #    self.send(sender, {"RETURN":"UNKNOWN_STATE", "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_STATE"]["ERROR_CODE"]})
                    #    return
                    #if sender != self.myAddress and sender != self.myParent:
                    #    logger.warning("Received a message for an illegal sender (address is %s)", sender)
                    #    self.send(sender, {"RETURN":"NOT_ALLOWED", "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_SENDER"]["ERROR_CODE"]})
                    #    return
                    if self.work_state != "IDLE" and self.work_state != "STANDBY":
                        logger.warning("The client is busy. Please send the message later")
                        self.send(sender, {"RETURN":"REFUSED", "ERROR_CODE": RETURN_MESSAGES["BLOCKED"]["ERROR_CODE"]})
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
                if msg.payload == "STANDBY":
                    self._standby(msg, sender)
                else:
                    logger.debug("Received an unknown wakeup message")
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

    def on_connect(
        self, client, userdata, flags, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        if result_code == 0:
            logger.info("Connected with MQTT %s.", self.mqtt_broker)
            #if self.work_state == "CONNECT":
            #    self.flag_switcher[self.work_state] = True
            self.flag_switcher[self.work_state] = True
        else:
            logger.info(
                f"Connection to MQTT self.mqtt_broker failed. result_code={result_code}"
            )
            #if self.work_state == "CONNECT":
            #    self.flag_switcher[self.work_state] = False
            self.flag_switcher[self.work_state] = False
            #self.send(self.myAddress, ActorExitRequest())
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")

    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.info(
                f"Disconnection from MQTT-broker ungracefully. result_code={result_code}"
            )
            self._connect(None, None)
        else:
            self.ungr_disconn = 0
            logger.info("Gracefully disconnected from MQTT-broker.")
        self.flag_switcher["CONNECT"] = False
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        #logger.info("[Subscriber]\tTo kill the subscriber")
        #self.send(self.myAddress, ActorExitRequest())

    def on_publish(self, client, userdata, mid):
        #self.rc_pub = 0
        logger.info(
            "The message with Message-ID %d is published to the broker!\n", mid
        )
        if self.work_state == "PUBLISH" and mid == self.mid[self.work_state]:
            self.flag_switcher[self.work_state] = True

    def on_subscribe(self, client, userdata, mid, grant_qos):
        #self.rc_sub = 0
        logger.info("Subscribed to the topic successfully!\n")
        if self.work_state == "PUBLISH" and mid == self.mid[self.work_state]:
            self.flag_switcher[self.work_state] = True

    def on_unsubscribe(self, client, userdata, mid):
        #self.rc_uns = 0
        logger.info("Unsubscribed to the topic successfully!\n")
        if self.work_state == "PUBLISH" and mid == self.mid[self.work_state]:
            self.flag_switcher[self.work_state] = True

    def on_message(self, client, userdata, message):
        logger.info(f"message received: {str(message.payload.decode('utf-8'))}")
        logger.info(f"message topic: {message.topic}")
        logger.info(f"message qos: {message.qos}")
        logger.info(f"message retain flag: {message.retain}")
        msg_buf = {
            "topic": message.topic,
            "payload": message.payload,
        }
        self.queue_to_parse.put(msg_buf)
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
    
    def _standby(self):
        if self.work_state == "IDLE":
            pass
        elif self.work_state == "STANDBY":
            if not self.queue_to_parse.empty():
                self.send(self.myParent, {"CMD": "PARSE", "PAR": self.queue_to_parse.get()})
        elif self.work_state not in self.task_start_time.keys():
            logger.error("Client is working at an unknow state: %s", self.work_state)
        elif (time.time() - self.task_start_time[self.work_state])>= 0.05:
            if self.flag_switcher[self.work_state] is None or self.flag_switcher[self.work_state] == False:
                logger.warning("[%s]: The wait time is so long that this task is aborted", self.work_state)
                self.send(self.requester, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher[self.work_state]})
            else:
                logger.info("[%s]: Received the result: successful", self.work_state)
                self.send(self.requester, {"RETURN": "OK_SKIPPED", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
            self.work_state = "STANDBY"
        #elif self.work_state not in self.flag_switcher.keys():
        #    logger.info("Waiting...")
        elif self.flag_switcher[self.work_state] is None:
            logger.info("Waiting...")
        elif self.flag_switcher[self.work_state] == True:
            logger.info("[%s]: Received the result: successful", self.work_state)
            self.send(self.requester, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
            self.flag_switcher[self.work_state] = None
            self.work_state = "STANDBY"
        elif self.flag_switcher[self.work_state] == False:
            logger.info("[%s]: Received the result: failed", self.work_state)
            self.send(self.requester, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher[self.work_state]})
            self.flag_switcher[self.work_state] = None
            self.work_state = "STANDBY"
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")

    def _setup(self, msg: dict, sender) -> None:
        self.work_state = "SETUP"
        self.mqtt_cid = msg.get("PAR", None).get("client_id", None)
        self.mqtt_broker = msg.get("PAR", None).get("mqtt_broker", None)
        self.port = msg.get("PAR", None).get("port", None)
        self.lwt_payload = msg.get("PAR", None).get("LWT", None).get("lwt_payload", None)
        self.lwt_topic = msg.get("PAR", None).get("LWT", None).get("lwt_topic", None)
        self.lwt_qos = msg.get("PAR", None).get("LWT", None).get("lwt_qos", None)
        if self.mqtt_cid is None:
            logger.error("[SETUP]: The client ID is not given")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
            self.work_state = "IDLE"
            return
        lwt_set = False
        if (self.lwt_payload is not None) and (self.lwt_topic is not None):
            logger.info("Received the payload and topic for setting a LWT message")
            lwt_set = True
            if self.lwt_qos is None:
                self.lwt_qos = 0
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
            logger.infor("Using the local host: 127.0.0.1")
        if self.port is None:
            self.port = 1883
            logger.infor("Using the ddefault port: 1883")
        if self._connect(lwt_set):
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
        else:
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": self.error_code_switcher["CONNECT"]})
        self.work_state = "STANDBY"
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        return
        '''
        if not self._connect():
            logger.warning("Connection failed")
            self.send(sender, {"RETURN":"SETUP", "ERROR_CODE": RETURN_MESSAGES.get("SETUP_FAILURE", None).get("ERROR_CODE", None)})
            return
        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": "test0", "qos": 0},
        }
        _re = self._subscribe(sub_req_msg, sender)
        if not (
            _re is RETURN_MESSAGES.get("OK") or _re is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            self.send(sender, RETURN_MESSAGES.get("SETUP_FAILURE"))
            return
        
        self.send(sender, RETURN_MESSAGES.get("OK_SKIPPED"))
        return
        '''
    
    def _connect(self, lwt_set:bool)->bool:
        #self.work_state = "CONNECT"
        #logger.info("Work state: connect")
        self.mqttc = MQTT.Client(self.mqtt_cid)

        self.mqttc.reinitialise()

        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        try:
            logger.info("Try to connect to the mqtt broker")
            if lwt_set:
                self.mqttc.will_set(self.lwt_topic, payload=self.lwt_payload, qos=self.lwt_qos, retain=True)
            self.mqttc.connect(self.mqtt_broker, port=self.port)
            #self.task_start_time[self.work_state] = time.time()
        except:
            logger.error("Failed to connect to the given broker and port")
            #self.send(self.myParent, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher[self.work_state]})
            #self.work = "STANDBY"
            #self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return False
        self.mqttc.loop_forever()
        #self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        return True
        '''wait_cnt0 = 100
        logger.info("wait for Flag set")
        while wait_cnt0 >0:
            if self.connected_flag:
                logger.info("Flag set")
                return True
            else:
                wait_cnt0 = wait_cnt0 - 1
                time.sleep(1)
        return False
        '''
    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.info("Already disconnected")
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("Disconnection gracefully: "+RETURN_MESSAGES.get("OK_SKIPPED"))

    def _publish(self, msg: dict, sender)->None:
        self.work_state = "PUBLISH"
        logger.info("Work state: publish")
        if not self.flag_switcher["CONNECT"]:
            logger.warning("Failed to publish the message because of disconnection")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["PUBLISH"]})
            self._connect()
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if (self.mqtt_topic is None) or not(isinstance(self.mqtt_topic, str)):
            logger.warning("the topic is none or not a string")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
            self.work_state = "STANDBY"
        else:
            self.mqtt_payload = msg.get("PAR", None).get("payload", None)
            self.mqtt_qos = msg.get("PAR", None).get("qos", None)
            self.retain = msg.get("PAR", None).get("retain", None)
            if self.retain is None:
                self.retain = False
            logger.info("To publish")
            self.flag_switcher[self.work_state] = False
            info = self.mqttc.publish(self.mqtt_topic, payload=self.mqtt_payload, qos=self.mqtt_qos, retain=self.retain)
            if info.rc != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Publish failed; result code is: %s", info.rc)
                self.send(sender, {"RETURN": self.work_state, "ERROR_CODE":  self.error_code_switcher["PUBLISH"]})
                self.work_state = "STANDBY"
            else:
                self.task_start_time[self.work_state] = time.time()
                self.mid[self.work_state] = info.mid
                self.requester = sender
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        return
        
        '''
        info = self.mqttc.publish(self.mqtt_topic, payload=self.mqtt_payload, qos=self.mqtt_qos, retain=self.retain)
        info.wait_for_publish()
        if info.rc != 0:
            return RETURN_MESSAGES.get("PUBLISH_FAILURE")
        else:
            return RETURN_MESSAGES.get("OK_SKIPPED")
        '''

    def _subscribe(self, msg: dict, sender)->None:
        self.work_state = "SUBSCRIBE"
        logger.info("Work state: subscribe")
        if not self.flag_switcher["CONNECT"]:
            logger.warning("Failed to subscribe to the topic(s) because of disconnection")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["SUBSCRIBE"]})
            self._connect()
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        sub_info = msg.get("PAR", None).get("INFO", None)
        if sub_info is None:
            logger.warning("[Subscribe]: the INFO for subscribe is none")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        elif isinstance(sub_info, list):
            for ele in sub_info:
                if not isinstance(ele, tuple):
                    logger.warning("[Subscribe]: the INFO for subscribe is a list while it contains a non-tuple element")
                    self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
                    self.work_state = "STANDBY"
                    self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return
                elif len(ele) != 2:
                    logger.warning("[Subscribe]: the INFO for subscribe is a list while it contains a tuple elemnt whose length is not equal to 2")
                    self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
                    self.work_state = "STANDBY"
                    self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return
                elif len(ele) == 2 and ele[0] is None:
                    logger.warning("[Subscribe]: the first element of one tuple namely the 'topic' is None")
                    self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"]})
                    self.work_state = "STANDBY"
                    self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
                    return
            info = self.mqttc.subscribe(sub_info)
            if info.rc != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Subscribe failed; result code is: %s", info.rc)
                self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"]["ERROR_CODE"]})
                self.work_state = "STANDBY"
            else:
                self.task_start_time[self.work_state] = time.time()
                self.mid[self.work_state] = info.mid
                self.requester = sender
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        '''
        self.wait_cnt2 = 10
        while self.wait_cnt2 != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                self.wait_cnt2 = self.wait_cnt2 - 1
                logger.info("Waiting for the on_subscribe being called")
            else:
                self.rc_sub = 1
                return RETURN_MESSAGES.get("OK_SKIPPED")
        else:
            logger.info("on_subscribe not called: SUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("SUBSCRIBE_FAILURE")
        '''

    def _unsubscribe(self, msg: dict, sender) -> dict:
        self.mqtt_topic = msg.get("PAR", None).get("INFO", None)
        if not self.flag_switcher["CONNECT"]:
            logger.warning("Failed to unsubscribe to the topic(s) because of disconnection")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"]})
            self._connect()
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        if self.mqtt_topic is None or not isinstance(self.mqtt_topic, list) or not isinstance(self.mqtt_topic, str):
            logger.warning("[Unsubscribe]: The topic is none or it is neither a string nor a list ")
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"]})
            self.work_state = "STANDBY"
            self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
            return
        info = self.mqttc.unsubscribe(self.mqtt_topic)
        if info.rc != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Unsubscribe failed; result code is: %s", info.rc)
            self.send(sender, {"RETURN": self.work_state, "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"]})
            self.work_state = "STANDBY"
        else:
            self.task_start_time[self.work_state] = time.time()
            self.mid[self.work_state] = info.mid
            self.requester = sender
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        return
        '''
        self.wait_cnt3 = 3

        while self.wait_cnt3 != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                self.wait_cnt3 = self.wait_cnt3 - 1
                logger.info("Waiting for the on_unsubscribe being called")
            else:
                self.rc_uns = 1
                break
        else:
            logger.info("on_unsubscribe not called: UNSUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("UNSUBSCRIBE_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")
        '''
    
    def _kill(self, msg, sender):
        self._disconnect()
        self.mqttc.loop_stop()
        self.myParent = None
        self.work_state = "IDLE"
        self.task_start_time = None
        self.error_code_switcher = None
        self.flag_switcher = None
        self.mid = None
        logger.info("Already killed the subscriber")
    '''
    def _parser(self, msg, sender):
        if not mqtt_msg_queue.empty():
            logger.info("Parser: topic is: %s", msg.get("topic"))
            logger.info("Parser: payload is: %s", msg.get("payload"))
        else:
            logger.info("No message to parse now")

        self.wakeupAfter(datetime.timedelta(seconds=1), payload="Parser")
    '''
'''
def test():
    """
    ActorSystem(
        systemBase=config["systemBase"],
        capabilities=config["capabilities"],
    )
    """
    print(MqttClientActor)
    mqtt_client_actor = ActorSystem().createActor(
        MqttClientActor, globalName="SARAD_MQTT_Client"
    )
    ask_re = ActorSystem().ask(mqtt_client_actor,  {"CMD": "SETUP", "PAR": {"client_id": "sarad-mqtt_subscriber-client", "mqtt_broker": "127.0.0.1"}})
    logger.info(ask_re)
    ask_re = ActorSystem().ask(mqtt_client_actor,  {"CMD": "SUBSCRIBE", "PAR": {"topic": "test1", "qos": 0}})
    logger.info(ask_re)
    ask_re = ActorSystem().ask(mqtt_client_actor,  {"CMD": "PUBLISH", "PAR": {"topic": "test2", "payload": "it's a test", "qos": 0}})
    logger.info(ask_re)
    input("Press Enter to End\n")
    logger.info("!")

if __name__ == "__main__":
    test()
'''
