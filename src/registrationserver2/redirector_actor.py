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
        "KILL": "_kill",
        "CONNECT": "_connect_loop",
        "RECEIVE": "_receive_loop",
    }

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
        if str(msg) == "WakeupMessage(0:00:01, Connect)":
            logger.debug("Connect loop.")
            self._connect_loop()
            return
        if str(msg) == "WakeupMessage(0:00:01, Receive)":
            logger.debug("Receive loop.")
            self._receive_loop()
            return
        if isinstance(msg, thespian.actors.ActorExitRequest):
            self._socket.close()
            return
        if not isinstance(msg, dict):
            return_msg = RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        if msg.get("RETURN", None) is not None:
            return
        cmd_key = msg.get("CMD", None)
        logger.debug("%s command received", cmd_key)
        if cmd_key is None:
            return_msg = RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]
            logger.debug("Send %s back to %s", return_msg, sender)
            self.send(sender, return_msg)
            return
        if cmd_key == "CONNECT":
            logger.debug("Start _connect_loop")
            self._connect_loop()
            return
        if cmd_key == "RECEIVE":
            logger.debug("Start _receive_loop")
            self._receive_loop()
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

    def _setup(self, msg, sender):
        logger.debug("Setup redirector actor")
        if self.my_parent is None:
            parent_name = msg["PAR"]["PARENT_NAME"]
            self.my_parent = self.createActor(Actor, globalName=parent_name)
            return_msg = {"CMD": "RETURN"}
            return_msg["RESULT"] = {"IP": self._host, "PORT": self._port}
            logger.debug("Setup finished with %s", return_msg)
            self.send(sender, return_msg)
            return
        self.send(sender, RETURN_MESSAGES["OK_SKIPPED"])

    def _kill(self, _, sender):
        self._socket.close()
        logger.debug("Ask myself to exit...")
        self.send(self.myAddress, thespian.actors.ActorExitRequest())
        self.send(sender, RETURN_MESSAGES["OK"])

    def _connect_loop(self):
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

    def _receive_loop(self):
        data = self._client_socket.recv(9002)
        logger.info("%s from %s", data, self._socket_info)
        if not data:
            return
        logger.debug("Ask device actor to SEND data...")
        send_response = ActorSystem().ask(
            self.my_parent, {"CMD": "SEND", "PAR": {"DATA": data}}
        )
        logger.debug("returned with %s", send_response)
        if not send_response["ERROR_CODE"]:
            response_data = send_response["RESULT"]["DATA"]
            logger.debug("%s to %s", response_data, self._socket_info)
        else:
            logger.error("Response error %s", send_response)
        logger.debug("Send RECEIVE command to redirector")
        self.send(self.myAddress, {"CMD": "RECEIVE"})
