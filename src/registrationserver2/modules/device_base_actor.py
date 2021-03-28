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
from registrationserver2 import (FOLDER_AVAILABLE, FOLDER_HISTORY,
                                 actor_system, theLogger)
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import Actor  # type: ignore

theLogger.info("%s -> %s", __package__, __file__)


class DeviceBaseActor(Actor):
    """
    .. uml :: uml-device_base_actor.puml
    """

    # Defines magic methods that are called when the specific message is
    # received by the actor
    ACCEPTED_COMMANDS = {  # Those needs implementing
        # SEND is being called when the end-user-application wants to send data,
        # should return the direct or indirect response from the device, None in
        # case the device is not reachable (so the end application can set the
        # timeout itself)
        "SEND": "_send",
        # RESERVE is being called when the end-user-application wants to reserve the
        # directly or indirectly connected device for exclusive communication,
        # should return if a reservation is currently possible
        "RESERVE": "_reserve",
        # Those are implemented by the base class (this class)
        # ECHO should return what is send, main use is for testing purpose at this point
        "ECHO": "_echo",
        # is being called when the end-user-application is done requesting /
        # sending data, should return true as soon the freeing process has been
        # initialized
        "FREE": "_free",
        "SETUP": "_setup",
        "KILL": "_kill",
    }

    def __init__(self):
        super().__init__()
        self._config: dict = {}
        self._file: json
        self.link = None
        self.__folder_history: str = FOLDER_HISTORY + os.path.sep
        self.__folder_available: str = FOLDER_AVAILABLE + os.path.sep
        self.my_redirector = None
        theLogger.info("Device actor created.")

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

        if not isinstance(msg, dict):
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGTYPE"])
            return

        cmd_key = msg.get("CMD", None)

        if cmd_key is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"])
            return

        cmd = self.ACCEPTED_COMMANDS.get(cmd_key, None)
        if cmd is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"])
            return

        if getattr(self, cmd, None) is None:
            self.send(sender, RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"])
            return

        self.send(sender, getattr(self, cmd)(msg))

    @staticmethod
    def _echo(msg: dict) -> dict:
        msg.pop("CMD", None)
        msg.pop("RETURN", None)
        msg["RETURN"] = True
        return msg

    def _setup(self, msg: dict) -> dict:
        if self.link is None:
            filename = fr"{self.__folder_history}{self.globalName}"
            self.link = fr"{self.__folder_available}{self.globalName}"
            if not os.path.exists(filename):
                os.mknod(filename)
            if not os.path.exists(self.link):
                theLogger.info("Linking %s to %s", self.link, filename)
                os.link(filename, self.link)
            self._file = msg["PAR"]
            with open(filename, "w+") as file_stream:
                file_stream.write(self._file)
            return RETURN_MESSAGES["OK"]
        return RETURN_MESSAGES["OK_SKIPPED"]

    def _kill(self, msg: dict):
        theLogger.info("Shutting down actor %s, Message: %s", self.globalName, msg)
        filename = fr"{self.__folder_history}{self.globalName}"
        self.link = fr"{self.__folder_available}{self.globalName}"
        if os.path.exists(self.link):
            os.unlink(self.link)
        if os.path.exists(filename):
            os.remove(filename)
        if self.my_redirector is not None:
            kill_return = registrationserver2.actor_system.ask(
                self.my_redirector, thespian.actors.ActorExitRequest()
            )
            theLogger.info(kill_return)
        kill_return = registrationserver2.actor_system.ask(
            self.myAddress, thespian.actors.ActorExitRequest()
        )
        theLogger.info(kill_return)
        return RETURN_MESSAGES["OK"]

    def _reserve(self, msg: dict) -> dict:
        """Handler for RESERVE message from REST API."""
        theLogger.info("Device actor received a RESERVE command with message: %s", msg)
        if msg["APP"] is None:
            theLogger.error("ERROR: there is no APP name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        if msg["HOST"] is None:
            theLogger.error("ERROR: there is no HOST name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        if msg["USER"] is None:
            theLogger.error("ERROR: there is no USER name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        # TODO: Check instrument server for availability of requested instrument
        # Create redirector actor
        if self.my_redirector is None:
            short_id = self.globalName.split(".")[0]
            self.my_redirector = self.createActor(RedirectorActor, globalName=short_id)
            actor_system.ask(
                self.my_redirector,
                {"CMD": "SETUP", "PAR": {"PARENT_NAME": self.globalName}},
            )
            theLogger.info("Redirector actor created.")
            # Write into device file

            return RETURN_MESSAGES["OK"]
        return RETURN_MESSAGES["OK_SKIPPED"]
