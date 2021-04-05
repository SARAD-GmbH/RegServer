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
from datetime import datetime, timedelta

import thespian.actors  # type: ignore
from flask import json
from registrationserver2 import FOLDER_AVAILABLE, FOLDER_HISTORY, logger
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import Actor, ActorSystem  # type: ignore

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
        "RETURN": "_return_with_socket",
    }

    @staticmethod
    def _echo(msg: dict) -> dict:
        msg.pop("CMD", None)
        msg.pop("RETURN", None)
        msg["RETURN"] = True
        return msg

    def __init__(self):
        logger.debug("Initialize a new device actor.")
        super().__init__()
        self._config: dict = {}
        self._file: json
        self.link = None
        self.__folder_history: str = FOLDER_HISTORY + os.path.sep
        self.__folder_available: str = FOLDER_AVAILABLE + os.path.sep
        self.my_redirector = None
        self.app = None
        self.user = None
        self.host = None
        logger.info("Device actor created.")

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return
        if not isinstance(msg, dict):
            return_msg = RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        if msg.get("RETURN", None) is not None:
            return
        cmd_key = msg.get("CMD", None)
        if cmd_key is None:
            return_msg = RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        cmd = self.ACCEPTED_COMMANDS.get(cmd_key, None)
        if cmd is None:
            return_msg = RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        if getattr(self, cmd, None) is None:
            return_msg = RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        getattr(self, cmd)(msg, sender)

    def _setup(self, msg: dict, sender) -> None:
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
            self.send(sender, RETURN_MESSAGES["OK"])
            return
        with open(filename, "w+") as file_stream:
            file_stream.write(self._file)
        self.send(sender, RETURN_MESSAGES["OK_UPDATED"])
        return

    def _kill(self, msg: dict, sender):
        logger.info("Shutting down actor %s, Message: %s", self.globalName, msg)
        filename = fr"{self.__folder_history}{self.globalName}"
        self.link = fr"{self.__folder_available}{self.globalName}"
        if os.path.exists(self.link):
            os.unlink(self.link)
        if os.path.exists(filename):
            os.remove(filename)
        if self.my_redirector is not None:
            logger.debug("Ask to kill redirector...")
            kill_return = ActorSystem().ask(
                self.my_redirector, thespian.actors.ActorExitRequest()
            )
            logger.info("returned with %s", kill_return)
        logger.debug("Ask to kill myself...")
        self.send(self.myAddress, thespian.actors.ActorExitRequest())
        self.send(sender, RETURN_MESSAGES["OK"])

    def _reserve(self, msg: dict, sender) -> None:
        """Handler for RESERVE message from REST API."""
        logger.info("Device actor received a RESERVE command with message: %s", msg)
        try:
            self.app = msg["PAR"]["APP"]
        except LookupError:
            logger.error("ERROR: there is no APP name!")
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"])
            return
        try:
            self.host = msg["PAR"]["HOST"]
        except LookupError:
            logger.error("ERROR: there is no HOST name!")
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"])
            return
        try:
            self.user = msg["PAR"]["USER"]
        except LookupError:
            logger.error("ERROR: there is no USER name!")
            self.send(sender, RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"])
            return
        if self._reserve_at_is(self.app, self.host, self.user):
            self._create_redirector(sender)
            return
        self.send(sender, RETURN_MESSAGES["OCCUPIED"])
        return

    def _reserve_at_is(self, app, host, user) -> bool:
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules."""
        return True

    def _create_redirector(self, sender):
        """Create redirector actor"""
        if self.my_redirector is None:
            short_id = self.globalName.split(".")[0]
            logger.debug(
                "Trying to create a redirector actor with globalName %s", short_id
            )
            self.my_redirector = self.createActor(RedirectorActor, globalName=short_id)
            msg = {"CMD": "SETUP", "PAR": {"PARENT_NAME": self.globalName}}
            logger.debug("Ask to setup redirector with msg %s", msg)
            self.send(self.my_redirector, msg)
            return
        self.send(sender, RETURN_MESSAGES["OK_SKIPPED"])
        return

    def _return_with_socket(self, msg, sender):
        logger.debug("returned with %s", msg)
        # Write Reservation section into device file
        ip_address = msg["RESULT"]["IP"]
        port = msg["RESULT"]["PORT"]
        reservation = {
            "Active": True,
            "App": self.app,
            "Host": self.host,
            "User": self.user,
            "IP": ip_address,
            "Port": port,
            "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        logger.info("Reservation: %s", reservation)
        df_content = json.loads(self._file)
        df_content["Reservation"] = reservation
        self._file = json.dumps(df_content)
        logger.info("self._file: %s", self._file)
        with open(self.link, "w+") as file_stream:
            file_stream.write(self._file)
        logger.debug("Send CONNECT command to redirector")
        self.send(self.my_redirector, {"CMD": "CONNECT"})
        self.send(sender, RETURN_MESSAGES["OK"])

    def _free(self, msg, sender) -> None:
        """Handler for FREE message from REST API."""
        logger.info("Device actor received a FREE command.")
        if self.my_redirector is not None:
            logger.debug("Ask to kill redirecot...")
            kill_return = ActorSystem().ask(self.my_redirector, {"CMD": "KILL"})
            logger.debug("returned with %s", kill_return)
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
            self.send(sender, RETURN_MESSAGES["OK"])
            return
        self.send(sender, RETURN_MESSAGES["OK_SKIPPED"])
        return
