"""Main actor of the Registration Server

Created
    2020-10-13

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-device_base_actor.puml
"""
import os
from datetime import datetime

from flask import json
from overrides import overrides  # type: ignore
from registrationserver2 import FOLDER_AVAILABLE, FOLDER_HISTORY, logger
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import (Actor, ActorExitRequest,  # type: ignore
                             ActorSystem)

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
    """

    ACCEPTED_COMMANDS = {
        "SEND": "_send",
        "RESERVE": "_reserve",
        "FREE": "_free",
        "SETUP": "_setup",
    }
    ACCEPTED_RETURNS = {
        "SETUP": "_return_with_socket",
    }

    @overrides
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
        self.sender_api = None
        logger.info("Device actor created.")

    @overrides
    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, ActorExitRequest):
            self._kill(msg, sender)
            return
        if not isinstance(msg, dict):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return
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
            return_function = self.ACCEPTED_RETURNS.get(return_key, None)
            if return_function is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            if getattr(self, return_function, None) is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            getattr(self, return_function)(msg, sender)

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
            return_message = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            }
            self.send(sender, return_message)
            return
        with open(filename, "w+") as file_stream:
            file_stream.write(self._file)
        return_message = {
            "RETURN": "SETUP",
            "ERROR_CODE": RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
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
            kill_return = ActorSystem().ask(self.my_redirector, ActorExitRequest())
            if not kill_return["ERROR_CODE"]:
                logger.critical(
                    "Killing the redirector actor failed with %s", kill_return
                )
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        logger.debug("Cleanup done before finally killing me.")

    def _reserve(self, msg: dict, sender) -> None:
        """Handler for RESERVE message from REST API."""
        logger.info("Device actor received a RESERVE command with message: %s", msg)
        self.sender_api = sender
        try:
            self.app = msg["PAR"]["APP"]
        except LookupError:
            logger.error("ERROR: there is no APP name!")
            return
        try:
            self.host = msg["PAR"]["HOST"]
        except LookupError:
            logger.error("ERROR: there is no HOST name!")
            return
        try:
            self.user = msg["PAR"]["USER"]
        except LookupError:
            logger.error("ERROR: there is no USER name!")
            return
        if self._reserve_at_is(self.app, self.host, self.user):
            self._create_redirector(sender)
            return
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
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
            logger.debug("Send SETUP command to redirector with msg %s", msg)
            self.send(self.my_redirector, msg)
            return
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
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
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        logger.debug("Return %s to %s", return_message, sender)
        self.send(self.sender_api, return_message)

    def _free(self, msg, sender):
        """Handler for FREE message from REST API."""
        logger.info("Device actor received a FREE command. %s", msg)
        if self.my_redirector is not None:
            logger.debug("Ask to kill redirector %s", self.my_redirector)
            kill_return = ActorSystem().ask(self.my_redirector, ActorExitRequest())
            if not kill_return["ERROR_CODE"]:
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
                return_message = {
                    "RETURN": "FREE",
                    "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                }
                self.send(sender, return_message)
                return
            logger.critical("Killing the redirector actor failed with %s", kill_return)
        return_message = {
            "RETURN": "FREE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
