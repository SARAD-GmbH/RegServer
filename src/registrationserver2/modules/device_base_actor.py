"""Main actor of the Registration Server

Created
    2020-10-13

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-device_base_actor.puml
"""
import os
from builtins import staticmethod
from datetime import datetime

import registrationserver2
import thespian.actors  # type: ignore
from flask import json
from registrationserver2 import (FOLDER_AVAILABLE, FOLDER_HISTORY,
                                 actor_system, logger)
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import Actor  # type: ignore

logger.info("%s -> %s", __package__, __file__)


class DeviceBaseActor(Actor):
    """Base class for protocol specific device actors.

    Implements all methods that all device actors have in common.
    Handles the following actor messages:

    * SETUP: is used to initialize the actor right after its creation. This is
      needed because some parts of the initialization cannot be done in
      __init__() (because for instance self.globalName is not available yet in
      __init__()), other initialization steps require data from the
      MdnsListener/MqttSubscriber creating the device actor. The same method is
      used for updates of the device state comming from the
      MdnsListener/MqttSubscriber.

    * RESERVE: is being called when the end-user-application wants to
        reserve the directly or indirectly connected device for exclusive
        communication, should return if a reservation is currently possible

    * SEND: is being called when the end-user-application wants to send
        data, should return the direct or indirect response from the device,
        None in case the device is not reachable (so the end application can
        set the timeout itself)

    * FREE: is being called when the end-user-application is done requesting or
        sending data, should return true as soon the freeing process has been
        initialized

    * KILL: similar to SETUP, this is used to do everything that has to be done
      before performing the ActorExitRequest.

    * ECHO: should return what was sent, mainly used for testing.

    """

    ACCEPTED_COMMANDS = {
        "SEND": "_send",
        "RESERVE": "_reserve",
        "ECHO": "_echo",
        "FREE": "_free",
        "SETUP": "_setup",
        "KILL": "_kill",
    }

    @staticmethod
    def _echo(msg: dict) -> dict:
        msg.pop("CMD", None)
        msg.pop("RETURN", None)
        msg["RETURN"] = True
        return msg

    def __init__(self):
        super().__init__()
        self._config: dict = {}
        self._file: json
        self.link = None
        self.__folder_history: str = FOLDER_HISTORY + os.path.sep
        self.__folder_available: str = FOLDER_AVAILABLE + os.path.sep
        self.my_redirector = None
        logger.info("Device actor created.")

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

    def _setup(self, msg: dict) -> dict:
        filename = fr"{self.__folder_history}{self.globalName}"
        if self.link is None:
            self.link = fr"{self.__folder_available}{self.globalName}"
            if not os.path.exists(filename):
                os.mknod(filename)
            if not os.path.exists(self.link):
                logger.info("Linking %s to %s", self.link, filename)
                os.link(filename, self.link)
            self._file = msg["PAR"]
            with open(filename, "w+") as file_stream:
                file_stream.write(self._file)
            return RETURN_MESSAGES["OK"]
        with open(filename, "w+") as file_stream:
            file_stream.write(self._file)
        return RETURN_MESSAGES["OK_UPDATED"]

    def _kill(self, msg: dict):
        logger.info("Shutting down actor %s, Message: %s", self.globalName, msg)
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
            logger.info(kill_return)
        kill_return = registrationserver2.actor_system.ask(
            self.myAddress, thespian.actors.ActorExitRequest()
        )
        logger.info(kill_return)
        return RETURN_MESSAGES["OK"]

    def _reserve(self, msg: dict) -> dict:
        """Handler for RESERVE message from REST API."""
        logger.info("Device actor received a RESERVE command with message: %s", msg)
        try:
            app = msg["PAR"]["APP"]
        except LookupError:
            logger.error("ERROR: there is no APP name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        try:
            host = msg["PAR"]["HOST"]
        except LookupError:
            logger.error("ERROR: there is no HOST name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        try:
            user = msg["PAR"]["USER"]
        except LookupError:
            logger.error("ERROR: there is no USER name!")
            return RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
        if self._reserve_at_is(app, host, user):
            return self._create_redirector(app, host, user)
        return RETURN_MESSAGES["OCCUPIED"]

    def _reserve_at_is(self, app, host, user) -> bool:
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules."""
        return True

    def _create_redirector(self, app, host, user):
        """Create redirector actor"""
        if self.my_redirector is None:
            short_id = self.globalName.split(".")[0]
            self.my_redirector = self.createActor(RedirectorActor, globalName=short_id)
            redirector_result = actor_system.ask(
                self.my_redirector,
                {"CMD": "SETUP", "PAR": {"PARENT_NAME": self.globalName}},
            )
            logger.info("Redirector actor created.")
            # Write Reservation section into device file
            reservation = {
                "Active": True,
                "App": app,
                "Host": host,
                "User": user,
                "IP": redirector_result["RESULT"]["IP"],
                "Port": redirector_result["RESULT"]["PORT"],
                "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            logger.info("Reservation: %s", reservation)
            df_content = json.loads(self._file)
            df_content["Reservation"] = reservation
            self._file = json.dumps(df_content)
            logger.info("self._file: %s", self._file)
            with open(self.link, "w+") as file_stream:
                file_stream.write(self._file)
            return RETURN_MESSAGES["OK"]
        return RETURN_MESSAGES["OK_SKIPPED"]

    def _free(self, _: dict) -> dict:
        """Handler for FREE message from REST API."""
        logger.info("Device actor received a FREE command.")
        if self.my_redirector is not None:
            kill_return = registrationserver2.actor_system.ask(
                self.my_redirector, {"CMD": "KILL"}
            )
            logger.info(kill_return)
            # Write Free section into device file
            df_content = json.loads(self._file)
            free = {
                "Active": False,
                "App": df_content["Reservation"]["App"],
                "Host": df_content["Reservation"]["Host"],
                "User": df_content["Reservation"]["User"],
                "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            logger.info("Free: %s", free)
            df_content["Free"] = free
            # Remove Reservation section
            df_content.pop("Reservation", None)
            self._file = json.dumps(df_content)
            logger.info("self._file: %s", self._file)
            with open(self.link, "w+") as file_stream:
                file_stream.write(self._file)
            self.my_redirector = None
            return RETURN_MESSAGES["OK"]
        return RETURN_MESSAGES["OK_SKIPPED"]
