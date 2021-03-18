"""
Created on 13.10.2020

@author: rfoerster
"""
import os
import traceback
from builtins import staticmethod
from json.decoder import JSONDecodeError

import registrationserver2
import thespian.actors  # type: ignore
from flask import json
from registrationserver2 import FOLDER_HISTORY, theLogger
from registrationserver2.modules.messages import RETURN_MESSAGES
from thespian.actors import Actor  # type: ignore

theLogger.info("%s -> %s", __package__, __file__)


class DeviceBaseActor(Actor):
    """
    .. uml :: uml-device_base_actor.puml
    """

    # Defines magic methods that are called when the specific message is
    # received by the actor
    ACCEPTED_MESSAGES = {  # Those needs implementing
        # SEND is being called when the end-user-application wants to send data,
        # should return the direct or indirect response from the device, None in
        # case the device is not reachable (so the end application can set the
        # timeout itself)
        "SEND": "__send__",
        # SEND_RESERVE is being called when the end-user-application wants to reserve the
        # directly or indirectly connected device for exclusive communication,
        # should return if a reservation is currently possible
        "SEND_RESERVE": "__send_reserve__",
        "SEND_FREE": "__send_free__",
        # Those are implemented by the base class (this class)
        # ECHO should return what is send, main use is for testing purpose at this point
        "ECHO": "__echo__",
        # is being called when the end-user-application is done requesting /
        # sending data, should return true as soon the freeing process has been
        # initialized
        "FREE": "__free__",
        "SETUP": "__setup__",
        "RESERVE": "__reserve__",
        "KILL": "__kill__",
    }

    def __init__(self):
        super().__init__()
        self._config: dict = {}
        self._file: json
        self.setup_done: bool = False

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

        if not isinstance(msg, dict):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGTYPE"))
            return

        cmd_string = msg.get("CMD", None)

        if not cmd_string:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return

        cmd = self.ACCEPTED_MESSAGES.get(cmd_string, None)

        if not cmd:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_UNKNOWN_COMMAND"))
            return

        if not getattr(self, cmd, None):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_NOTIMPLEMENTED"))
            return

        self.send(sender, getattr(self, cmd)(msg))

    @staticmethod
    def __echo__(msg: dict) -> dict:
        msg.pop("CMD", None)
        msg.pop("RETURN", None)
        msg["RETURN"] = True
        return msg

    def __setup__(self, msg: dict) -> dict:
        if not self.setup_done:
            self._config = msg
            filename = fr"{FOLDER_HISTORY}{os.path.sep}{self.globalName}"
            theLogger.info("Setting up Actor %s", self.globalName)
            if os.path.isfile(filename):
                try:
                    file = open(filename)
                    self._file = json.load(file)
                    self.setup_done = True
                    return RETURN_MESSAGES.get("OK")
                except JSONDecodeError as error:
                    theLogger.error("Failed to parse %s", filename)
                    return RETURN_MESSAGES.get("ILLEGAL_STATE")
                except Exception as error:  # pylint: disable=broad-except
                    theLogger.error(
                        "! %s\t%s\t%s\t%s",
                        type(error),
                        error,
                        vars(error) if isinstance(error, dict) else "-",
                        traceback.format_exc(),
                    )
                    return RETURN_MESSAGES.get("ILLEGAL_STATE")
            else:
                return RETURN_MESSAGES.get("ILLEGAL_STATE")
        else:
            theLogger.info("Actor already set up with %s", self._config)
            return RETURN_MESSAGES.get("OK_SKIPPED")

    def __kill__(self, msg: dict):  # TODO move to Actor Manager
        theLogger.info("Shutting down actor %s, Message: %s", self.globalName, msg)
        theLogger.info(
            registrationserver2.actor_system.ask(
                self.myAddress, thespian.actors.ActorExitRequest()
            )
        )
        # self.setup_done = False

    def __reserve__(self, msg: dict) -> dict:
        pass
