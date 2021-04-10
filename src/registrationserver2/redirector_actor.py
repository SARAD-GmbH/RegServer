"""Creates a listening server socket and forwards pakets received over this
socket as actor messages to the device actor.


Created
    2020-12-01

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-redirector_actor.puml

"""
import datetime
import socket

import thespian.actors  # type: ignore
from overrides import overrides  # type: ignore
from thespian.actors import Actor, ActorSystem  # type: ignore

from registrationserver2 import logger
from registrationserver2.config import config
from registrationserver2.modules.messages import RETURN_MESSAGES

logger.info("%s -> %s", __package__, __file__)


class RedirectorActor(Actor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    ACCEPTED_COMMANDS = {
        "SETUP": "_setup",
        "CONNECT": "_connect_loop",
        "RECEIVE": "_receive_loop",
    }
    ACCEPTED_RETURNS = {}

    @overrides
    def __init__(self):
        super().__init__()
        self.stop = False
        self.requestor = None
        self._connected = False
        self._client_socket = None
        self._socket_info = None
        self._host = config["HOST"]
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for self._port in config["PORT_RANGE"]:
            try:
                self._socket.bind((self._host, self._port))
                break
            except OSError:
                pass
        self._socket.listen()
        self.my_parent = None
        logger.info("Socket listening on port %d", self._port)

    @overrides
    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, thespian.actors.ActorExitRequest):
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

    def _setup(self, msg, sender):
        logger.debug("Setup redirector actor")
        if self.my_parent is None:
            parent_name = msg["PAR"]["PARENT_NAME"]
            self.my_parent = self.createActor(Actor, globalName=parent_name)
            return_msg = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"IP": self._host, "PORT": self._port},
            }
            logger.debug("Setup finished with %s", return_msg)
            self.send(sender, return_msg)
            return
        return_message = {
            "RETURN": "SETUP",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        return

    def _kill(self, _, sender):
        self._socket.close()
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        logger.debug("Cleanup done before finally killing me.")

    def _connect_loop(self, _msg, _sender):
        """Listen to Port and redirect any messages"""
        logger.debug("Waiting for connect at %s port %s", self._host, self._port)
        self._client_socket, self._socket_info = self._socket.accept()
        if self._client_socket is not None:
            self._connected = True
            logger.debug("Connected to %s", self._socket_info)
            self.send(self.myAddress, {"CMD": "RECEIVE"})
        else:
            logger.debug("Going round and round")
            self.wakeupAfter(datetime.timedelta(seconds=1), payload="Connect")

    def _receive_loop(self, _msg, _sender):
        data = self._client_socket.recv(9002)
        logger.info("%s from %s", data, self._socket_info)
        if not data:
            return
        logger.debug("Ask device actor to SEND data...")
        send_response = ActorSystem().ask(
            self.my_parent, {"CMD": "SEND", "PAR": {"DATA": data}}
        )
        if not send_response["ERROR_CODE"]:
            response_data = send_response["RESULT"]["DATA"]
            logger.debug("%s to %s", response_data, self._socket_info)
        else:
            logger.error("Response error %s", send_response)
        logger.debug("Send RECEIVE command to redirector")
        self.send(self.myAddress, {"CMD": "RECEIVE"})
