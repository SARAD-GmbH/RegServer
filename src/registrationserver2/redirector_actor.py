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
import select
import socket

from overrides import overrides  # type: ignore
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem, WakeupMessage

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
        self.my_parent = None
        self._connected = False
        self._client_socket = None
        self._socket_info = None
        self._host = config["HOST"]
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for self._port in config["PORT_RANGE"]:
            try:
                server_socket.bind((self._host, self._port))
                break
            except OSError:
                pass
        server_socket.listen()  # listen(5) maybe???
        self.read_list = [server_socket]
        logger.info("Socket listening on port %d", self._port)

    @overrides
    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
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
                return_function = self.ACCEPTED_RETURNS.get(return_key, None)
                if return_function is None:
                    logger.debug("Ask received the return %s from %s.", msg, sender)
                    return
                if getattr(self, return_function, None) is None:
                    logger.debug("Ask received the return %s from %s.", msg, sender)
                    return
                getattr(self, return_function)(msg, sender)
        else:
            if isinstance(msg, ActorExitRequest):
                self._kill(msg, sender)
                return
            if isinstance(msg, WakeupMessage):
                if msg.payload == "Connect":
                    self._connect_loop(msg, sender)
                elif msg.payload == "Receive":
                    self._receive_loop(msg, sender)
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

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
        self.read_list[0].close()
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        logger.debug("Cleanup done before finally killing me.")

    def _connect_loop(self, _msg, _sender):
        """Listen to Port and redirect any messages"""
        logger.debug("Waiting for connect at %s port %s", self._host, self._port)
        server_socket = self.read_list[0]
        timeout = 1
        readable, writable, errored = select.select(self.read_list, [], [], timeout)
        for s in readable:
            if s is server_socket:
                self._client_socket, self._socket_info = server_socket.accept()
                self.read_list.append(self._client_socket)
                self._connected = True
                logger.debug("Connection from %s", self._socket_info)
                self.send(self.myAddress, {"CMD": "RECEIVE"})
            else:
                data = s.recv(1024)
                if data:
                    s.send(data)
                else:
                    s.close()
                    self.read_list.remove(s)
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
