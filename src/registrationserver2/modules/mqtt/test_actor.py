'''
Created on 2021-04-27

@author: Yixiang
'''

import socket
import time
from overrides import overrides  # type: ignore

import registrationserver2
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem

class MqttTestActor(Actor):
    '''
    classdocs
    '''
    
    ACCEPTED_COMMANDS = {
        "TEST": "_test",
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
        self.switcher = [
            b"B\x80\x7f\xe0\xe0\x00E",
            b"B\x80\x7f\xe1\xe1\x00E",
            b"B\x81\x7e\xe2\x0c\xee\x00E",
            b"B\x80\x7f\x0c\x0c\x00\x00E",
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
                        logger.debug("Failed to send reserve; error code is: %s", msg["ERROR_CODE"])
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
                        logger.debug("Failed to send cmd '%s'; error code is: %s", self.switcher[self.test_step-1], msg["ERROR_CODE"])
                        self._test(self.myAddress, ActorExitRequest())
                        return 
                    elif self.test_step < self.test_cmd_amount:
                        self.test_step = self.test_step + 1
                        self._test(self.myAddress, {"CMD": "TEST", "PAR":None})
                        return
                    else:
                        self._test(self.myAddress, {"CMD": "TEST", "PAR":None})
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
    
    def _test(self, msg:dict, sender) -> None:
        if self.test_step == 0:
            self.target_name = msg.get("PAR", None).get("mqtt_actor_name", None)
            self.target_actor = ActorSystem().createActor(MqttActor, globalName=self.target_name)
            self._send_reserve()
        elif self.test_step == self.test_cmd_amount:
            self._send_free()
        elif self.test_step == self.test_cmd_amount+1:
            self._kill(self.myAddress, ActorExitRequest())
        else:
            logger.info("To let the mqtt actor '%s' to send the command '%s'", self.target_name, self.switcher[self.test_step-1])
            _msg = {"PAR": {"DATA": self.switcher[self.test_step-1]}}
            self._send_cmd(_msg)
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
    
    def _send_reserve(self): #-> dict:
        _msg = {
            "CMD": "RESERVE", 
            "PAR": {
                "APP": "RadonVision",
                "HOST": socket.gethostname(),
                "USER": "yixiang",
            }
        }
        self.send(self.target_actor, _msg)
        """
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
        """
    
    def _send_free(self):# -> dict:
        _msg = {"CMD": "FREE"}
        self.send(self.target_actor, _msg)
        time.sleep(0.01)
        self.test_step = self.test_step + 1
        self._test(None, None)
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
    
    def _send_cmd(self, msg:dict):# -> dict:
        data = msg.get("PAR", None).get("DATA", None)
        _msg = {
            "CMD": "SEND", 
            "PAR": {
                "DATA": data, 
            }
        }
        self.send(self.target_actor, _msg)
        """
        _re = ActorSystem().ask(self.target_actor, _msg)
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
        """
    
    def _kill(self, msg, sender):
        logger.info("Test actor is killed")
        