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
from thespian.actors import Actor, ActorExitRequest, WakeupMessage  # type: ignore

from registrationserver2 import logger
from registrationserver2.config import config
from registrationserver2.modules.messages import RETURN_MESSAGES

logger.info("%s -> %s", __package__, __file__)


class RedirectorActor(Actor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    ACCEPTED_COMMANDS = {
        "SETUP": "_setup",
        "CONNECT": "_connect_loop",
    }
    ACCEPTED_RETURNS = {
        "SEND": "_send_to_app",
    }

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._host = config["HOST"]
        logger.debug("IP address of Registration Server: %s", self._host)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for self._port in config["PORT_RANGE"]:
            try:
                server_socket.bind((self._host, self._port))
                self._port = server_socket.getsockname()[1]
                break
            except OSError:
                logger.critical("Cannot use port %d.", self._port)
        server_socket.listen()  # listen(5) maybe???
        self.read_list = [server_socket]
        logger.info("Socket listening on %s:%d", self._host, self._port)

    @overrides
    def receiveMessage(self, msg, sender):
        """Handles received Actor messages / verification of the message format"""
        if isinstance(msg, dict):
            logger.debug("Msg: %s, Sender: %s", msg, sender)
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
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                if getattr(self, return_function, None) is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                getattr(self, return_function)(msg, sender)
        else:
            if isinstance(msg, ActorExitRequest):
                self._kill(msg, sender)
                return
            if isinstance(msg, WakeupMessage):
                if msg.payload == "Connect":
                    self._connect_loop(msg, sender)
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
        else:
            return_msg = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
        logger.debug("Setup finished with %s", return_msg)
        self.send(sender, return_msg)

    def _kill(self, _, sender):
        self.read_list[0].close()
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        logger.debug("Cleanup done before finally killing me.")

    def _connect_loop(self, _msg, _sender):
        """Listen to socket and redirect any message from the socket to the device actor"""
        # logger.debug("Waiting for connect at %s port %s", self._host, self._port)
        # read_list = list of server sockets from which we expect to read
        server_socket = self.read_list[0]
        timeout = 0.1
        readable, _writable, _errored = select.select(self.read_list, [], [], timeout)
        for self.conn in readable:
            if self.conn is server_socket:
                self._client_socket, self._socket_info = server_socket.accept()
                self.read_list.append(self._client_socket)
                logger.debug("Connection from %s", self._socket_info)
            else:
                self._cmd_handler()
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="Connect")

    def _cmd_handler(self):
        """Handle a binary SARAD command received via the socket."""
        switcher = {
            b"B\x80\x7f\xe0\xe0\x00E": b"B\xa6\x59\xe3\x0c\x09\x09\x13\x03\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x19\x01E",
            b"B\x80\x7f\xe1\xe1\x00E": b"B\x80\x7f\xe4\xe4\x00E",
            b"B\x81\x7e\xe2\x0c\xee\x00E": b"B\x80\x7f\xe5\xe5\x00E",
        }
        data = self.conn.recv(1024)
        if data:
            logger.info("%s from %s", data, self._socket_info)
            try:
                reply = switcher[data]
                self.conn.sendall(reply)
            except KeyError:
                self.send(self.my_parent, {"CMD": "SEND", "PAR": {"DATA": data}})
        else:
            self.conn.close()
            self.read_list.remove(self.conn)

    def _send_to_app(self, msg, _sender):
        """Redirect any received reply to the socket."""
        data = msg["RESULT"]["DATA"]
        self.conn.sendall(data)
        logger.debug("Redirect %s to %s", data, self._socket_info)
