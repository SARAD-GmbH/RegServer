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
from registrationserver2 import logger
from registrationserver2.config import config
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.redirector_actor import RedirectorActor
from thespian.actors import (Actor, ActorExitRequest,  # type: ignore
                             ChildActorExited)

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
        "KILL": "_return_from_kill",
    }

    @overrides
    def __init__(self):
        logger.debug("Initialize a new device actor.")
        super().__init__()
        self._config: dict = {}
        self._file: json = None
        self.df_content = {}
        self.dev_file = None
        self.__dev_folder: str = config["DEV_FOLDER"] + os.path.sep
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
        if isinstance(msg, ChildActorExited):
            # Error handling code could be placed here
            # The child actor is the redirector actor.
            # It will be killed by the _free handler.
            logger.debug("Redirector actor exited.")
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
        if self.dev_file is None:
            self.dev_file = fr"{self.__dev_folder}{self.globalName}"
            if not os.path.exists(self.dev_file):
                open(self.dev_file, "a").close()
                logger.info("Device file %s created", self.dev_file)
            self._file = msg["PAR"]
            with open(self.dev_file, "w+") as file_stream:
                file_stream.write(self._file)
            return_message = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            }
            self.send(sender, return_message)
            return
        with open(self.dev_file, "w+") as file_stream:
            file_stream.write(self._file)
        return_message = {
            "RETURN": "SETUP",
            "ERROR_CODE": RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        return

    def _kill(self, msg: dict, sender):
        logger.info("Shutting down actor %s, Message: %s", self.globalName, msg)
        self.dev_file = fr"{self.__dev_folder}{self.globalName}"
        if os.path.exists(self.dev_file):
            os.remove(self.dev_file)
        if self.my_redirector is not None:
            logger.debug("Send KILL to redirector %s", self.my_redirector)
            self.send(self.my_redirector, ActorExitRequest())
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
        self._reserve_at_is()
        return

    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        :param self.app: String identifying the requesting app.
        :param self.host: String identifying the host running the app.
        :param self.user: String identifying the user of the app.
        :param self.sender_api: The actor object asking for reservation.
        """

    def _forward_reservation(self, success: bool):
        # pylint: disable=unused-argument, no-self-use
        """Forward the reply from the Instrument Server to the redirector actor.
        This function has to be called in the protocol specific modules.
        """
        if success:
            if self._create_redirector():
                return
            return_message = {
                "RETURN": "RESERVE",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
            self.send(self.sender_api, return_message)
            return
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"],
        }
        self.send(self.sender_api, return_message)
        return

    def _create_redirector(self) -> bool:
        """Create redirector actor"""
        logger.info(self.my_redirector)
        if self.my_redirector is None:
            short_id = self.globalName.split(".")[0]
            logger.debug(
                "Trying to create a redirector actor with globalName %s", short_id
            )
            self.my_redirector = self.createActor(RedirectorActor, globalName=short_id)
            msg = {"CMD": "SETUP", "PAR": {"PARENT_NAME": self.globalName}}
            logger.debug("Send SETUP command to redirector with msg %s", msg)
            self.send(self.my_redirector, msg)
            return True
        return False

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
        self.df_content = json.loads(self._file)
        self.df_content["Reservation"] = reservation
        self._file = json.dumps(self.df_content)
        logger.info("self._file: %s", self._file)
        with open(self.dev_file, "w+") as file_stream:
            file_stream.write(self._file)
        logger.debug("Send CONNECT command to redirector %s", self.my_redirector)
        self.send(self.my_redirector, {"CMD": "CONNECT"})
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        logger.debug("Return %s to %s", return_message, sender)
        self.send(self.sender_api, return_message)

    def _free(self, msg: dict, sender):
        """Handler for FREE message from REST API."""
        logger.info("Device actor received a FREE command. %s", msg)
        self.sender_api = sender
        if self.my_redirector is not None:
            logger.debug("Send KILL to redirector %s", self.my_redirector)
            self.send(self.my_redirector, ActorExitRequest())
            return
        return_message = {
            "RETURN": "FREE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        return

    def _return_from_kill(self, msg, _sender):
        """Completes the _free function with the reply from the redirector actor after
        it received the KILL command."""
        if not msg["ERROR_CODE"]:
            # Write Free section into device file
            self.df_content = json.loads(self._file)
            free = {
                "Active": False,
                "App": self.df_content["Reservation"]["App"],
                "Host": self.df_content["Reservation"]["Host"],
                "User": self.df_content["Reservation"]["User"],
                "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            logger.info("Free: %s", free)
            self.df_content["Free"] = free
            # Remove Reservation section
            self.df_content.pop("Reservation", None)
            self._file = json.dumps(self.df_content)
            logger.info("self._file: %s", self._file)
            with open(self.dev_file, "w+") as file_stream:
                file_stream.write(self._file)
            self.my_redirector = None
            return_message = {
                "RETURN": "FREE",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            }
            self.send(self.sender_api, return_message)
            return
        logger.critical("Killing the redirector actor failed with %s", msg)
        return_message = {
            "RETURN": "FREE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
        self.send(self.sender_api, return_message)
        return
