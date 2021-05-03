'''
Created on 2021-04-27

@author: Yixiang
'''

import os
import socket
import time
from overrides import overrides  # type: ignore

import registrationserver2
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from registrationserver2.modules.mqtt.mqtt_subscriber import SaradMqttSubscriber
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem
from _ast import In

class MqttTestActor(Actor):
    '''
    classdocs
    '''
    
    ACCEPTED_COMMANDS = {
        "TEST": "_test",
        "SETUP": "_setup",
        "PREPARE": "_prepare",
    }
    ACCEPTED_RETURNS = [
        "SEND",
        "RESERVE",
        "FREE",
    ]
    
    @overrides
    def __init__(self):
        self.target_name = None
        self.target_actor = None
        self.test_requester = None
        self.switcher = [
            b"B\x80\x7f\xe0\xe0\x00E",
            b"B\x80\x7f\xe1\xe1\x00E",
            b"B\x81\x7e\xe2\x0c\xee\x00E",
            b"B\x80\x7f\x0c\x0c\x00E",
        ]
        self.test_cmd_amount = 4
        self.test_step = 0
        super().__init__()
    
    @overrides
    def receiveMessage(self, msg, sender):
        """ Handles received Actor messages / verification of the message format"""
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
                if return_key not in self.ACCEPTED_RETURNS:
                    logger.debug("Received unknown return %s from %s.", msg, sender)
                    return
                if return_key == "RESERVE":
                    logger.info("Step: %s", self.test_step)
                    if not msg["ERROR_CODE"] in (
                        RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]
                    ):
                        logger.info("Failed to send reserve; error code is: %s", msg["ERROR_CODE"])
                        self.send(self.test_requester, {"RETURN": "TEST", "ERROR_CODE": msg["ERROR_CODE"]})
                        return 
                    else:
                        self.test_step = 1
                        self._test(self.myAddress, {"CMD": "TEST", "PAR":None})
                        return
                elif return_key == "SEND":
                    logger.info("Step: %s", self.test_step)
                    if not msg["ERROR_CODE"] in (
                        RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]
                    ):
                        logger.info("Failed to send cmd '%s'; error code is: %s", self.switcher[self.test_step-1], msg["ERROR_CODE"])
                        self.send(self.test_requester, {"RETURN": "TEST", "ERROR_CODE": msg["ERROR_CODE"]})
                        return 
                    elif self.test_step <= self.test_cmd_amount:
                        self.test_step = self.test_step + 1
                        self._test(self.myAddress, {"CMD": "TEST", "PAR":None})
                        return
                elif return_key == "FREE":
                    logger.info("Step: %s", self.test_step)
                    self.send(self.test_requester, {"RETURN": "TEST", "ERROR_CODE": msg["ERROR_CODE"]})
                    return
                    
        else:
            if isinstance(msg, ActorExitRequest):
                self._kill(msg, sender)
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return
    
    def _setup(self, msg:dict, sender):
        subscriber_name = msg.get("PAR", None).get("Subscriber_Name", None)
        self.sarad_mqtt_subscriber = ActorSystem().createActor(
            SaradMqttSubscriber, globalName=subscriber_name
        )
        ask_return = ActorSystem().ask(
            self.sarad_mqtt_subscriber,
            {
                "CMD": "SETUP",
                "PAR": {
                    "client_id": "sarad-mqtt_subscriber-client",
                    "mqtt_broker": "127.0.0.1",
                    "port": 1883,
                },
            },
        )
        if ask_return is None:
            logger.error("[test_actor/setup]: No reply from the subscriber")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": RETURN_MESSAGES["ASK_NO_REPLY"]["ERROR_CODE"]})
        elif ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.info("SARAD MQTT Subscriber is setup correctly!")
            self.send(sender, ask_return)
        else:
            logger.warning("SARAD MQTT Subscriber is not setup!")
            logger.error(ask_return)
            logger.info("!!")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"]})
    
    def _prepare(self, msg:dict, sender) -> None:
        logger.info("To prepare for testing")
        self.test_requester = sender
        self.target_name = msg.get("PAR", None).get("mqtt_actor_name", None)
        self.target_actor = ActorSystem().createActor(MqttActor, globalName=self.target_name)
        self.send(sender, {"RETURN": "PREPARE", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
    
    '''
    def _test(self, msg:dict, sender) -> None: 
        test_switcher = {
            0: self._send_reserve,
            1: self._send_cmd,
            2: self._send_cmd,
            3: self._send_cmd,
            4: self._send_cmd,
            5: self._send_free,
        }
        self.test_step = 0
        while self.test_step <= self.test_cmd_amount + 1:
            _re = test_switcher[self.test_step]()
            logger.info("show return")
            logger.info(_re)
            if _re is None:
                logger.info("Step %s test got no reply", self.test_step)
                self.send(sender, {"RETURN": "TEST", "ERROR_CODE": _re["ERROR_CODE"]})
                return
            if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.error("Step %s test failed!", self.test_step)
                self.send(sender, {"RETURN": "TEST", "ERROR_CODE": _re["ERROR_CODE"]})
                return
            self.test_step = self.test_step + 1
        logger.info("Test completed!")
        self.send(sender, {"RETURN": "TEST", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
        return
    '''
    def _test(self, msg:dict, sender) -> None:       
        if self.test_step == 0:
            #self.target_name = msg.get("PAR", None).get("mqtt_actor_name", None)
            #self.target_actor = ActorSystem().createActor(MqttActor, globalName=self.target_name)
            self._send_reserve()
        elif self.test_step == self.test_cmd_amount+1:
            self._send_free()
        else:
            logger.info("To let the mqtt actor '%s' to send the command '%s'", self.target_name, self.switcher[self.test_step-1])
            #_msg = {"PAR": {"DATA": self.switcher[self.test_step-1]}}
            #self._send_cmd(_msg)
            self._send_cmd()
        """
        _re = self._send_reserve()
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error("failed to send reserve -> test failed   error code: %s", _re["ERROR_CODE"])
            self.send(sender, {"RETURN": "TEST", "ERROR_CODE": _re["ERROR_CODE"]})
            return
        for data in self.switcher:
            _msg = {"PAR": {"DATA": data}}
            _re = self._send_cmd(_msg)
            if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.error("failed to send cmd '%s' -> test failed   error code: %s", data, _re["ERROR_CODE"])
                self.send(sender, {"RETURN": "TEST", "ERROR_CODE": _re["ERROR_CODE"]})
                return
        _re = self._send_free()
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error("failed to send free -> test failed   error code: %s", _re["ERROR_CODE"])
            self.send(sender, {"RETURN": "TEST", "ERROR_CODE": _re["ERROR_CODE"]})
            return
        logger.info("Test finished!")
        self.send(sender, {"RETURN": "TEST", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]})
        return
        """
    
    def _send_reserve(self) -> dict:
        _msg = {
            "CMD": "RESERVE", 
            "PAR": {
                "APP": "RadonVision",
                "HOST": socket.gethostname(),
                "USER": "yixiang",
            }
        }
        self.send(self.target_actor, _msg)
        '''
        _re = ActorSystem().ask(self.target_actor, _msg, timeout=1)
        if _re is None:
            logger.error("Got no reply from the mqtt actor '%s'", self.target_name)
            return {"RETURN": "SEND_RESERVE", "ERROR_CODE": RETURN_MESSAGES["SEND_RESERVE_FAILURE"]["ERROR_CODE"]}
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error("Failed to send reserve")
            return {"RETURN": "SEND_RESERVE", "ERROR_CODE": _re["ERROR_CODE"]}
        logger.info("Sent reserve successfully!")
        return {"RETURN": "SEND_RESERVE", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]}
        '''
    
    def _send_free(self) -> dict:
        _msg = {"CMD": "FREE"}
        self.send(self.target_actor, _msg)
        '''
        time.sleep(0.01)
        self.test_step = self.test_step + 1
        self._test(None, None)
        '''
        """
        _re = ActorSystem().ask(self.target_actor, _msg, timeout=1)
        if _re is None:
            logger.error("Got no reply from the mqtt actor '%s'", self.target_name)
            return {"RETURN": "SEND_FREE", "ERROR_CODE": RETURN_MESSAGES["SEND_FREE_FAILURE"]["ERROR_CODE"]} 
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error("Failed to send free")
            return {"RETURN": "SEND_FREE", "ERROR_CODE": _re["ERROR_CODE"]}
        logger.info("Sent free successfully!")
        return {"RETURN": "SEND_FREE", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]}
        """
    
    def _send_cmd(self) -> dict:
        #data = msg.get("PAR", None).get("DATA", None)
        data = self.switcher[self.test_step - 1]
        _msg = {
            "CMD": "SEND", 
            "PAR": {
                "DATA": data, 
            }
        }
        self.send(self.target_actor, _msg)
        '''
        _re = ActorSystem().ask(self.target_actor, _msg, timeout=5)
        if _re is None:
            logger.error("Got no reply from the mqtt actor '%s'", self.target_name)
            return {"RETURN": "SEND_CMD", "ERROR_CODE": RETURN_MESSAGES["SEND_FAILURE"]["ERROR_CODE"]} 
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.error("Failed to send cmd")
            return {"RETURN": "SEND_CMD", "ERROR_CODE": _re["ERROR_CODE"]}
        else:
            logger.info("Received a reply")
            logger.info(_re["RESULT"])
            return {"RETURN": "SEND_CMD", "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"]}
        '''
    
    def _kill(self, msg, sender):
        self.send(self.sarad_mqtt_subscriber, ActorExitRequest())
        logger.info("Test actor is killed")

def __test__():
    # ActorSystem(
    #    systemBase=config["systemBase"],
    #    capabilities=config["capabilities"],
    # )
    logger.info("Subscriber")
    test_actor = ActorSystem().createActor(
        MqttTestActor, globalName="test_actor_001"
    )
    ask_return = ActorSystem().ask(
        test_actor,
        {
            "CMD": "SETUP",
            "PAR": {
                "Subscriber_Name": "SARAD_Subscriber",
            },
        },
    )
    if ask_return["ERROR_CODE"] in (
        RETURN_MESSAGES["OK"]["ERROR_CODE"],
        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
    ):
        logger.info("Test actor is setup correctly!")
        folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
        folder_available = f"{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}"
        while True:
            if os.listdir(folder_history) == []:
                logger.info("No files found in the directory.")
                time.sleep(1)
            else:
                f = os.listdir(folder_history)
                logger.info("Some files found in the directory.")
                break
        avail_f = []
        while True:
            for filename in f:
                logger.info("File '%s' exists", filename)
                link = fr"{folder_available}{filename}"
                if os.path.exists(link):
                    logger.info("Link '%s' exists", link)
                    avail_f.append(filename)
            if avail_f != []:
                logger.info("There are some available instruments")
                logger.info(avail_f)
                break
            time.sleep(1)
        for filename in avail_f:
            logger.info("File '%s' exists", filename)
            link = fr"{folder_available}{filename}"
            ask_msg = {
                "CMD": "PREPARE",
                "PAR": {
                    "mqtt_actor_name": filename, 
                },
            }
            ask_return = ActorSystem().ask(test_actor, ask_msg)
            if ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.info("To test")
                ask_msg = {"CMD": "TEST"}
                ActorSystem().tell(test_actor, ask_msg)
                time.sleep(30)
                logger.info("It's time to kill the test actor")
                '''
                ask_return = ActorSystem().ask(test_actor, ask_msg)
                logger.info(ask_return)
                '''
            else:
                logger.error("Test actor failed to prepare")
            
    else:
        logger.warning("SARAD MQTT Subscriber is not setup!")
        logger.error(ask_return)
        #input("Press Enter to End")
        logger.info("!!")
    ActorSystem().tell(test_actor, ActorExitRequest())
    time.sleep(10)
    ActorSystem().shutdown()


if __name__ == "__main__":
    __test__()
        