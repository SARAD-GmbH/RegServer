"""Creates a listening server socket and forwards pakets received over this
socket as actor messages to the device actor.

:Created:
    2020-12-01

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-redirect_actor.puml

"""
import datetime
import select
import socket
import time

from overrides import overrides  # type: ignore
from thespian.actors import WakeupMessage  # type: ignore

from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES

logger.debug("%s -> %s", __package__, __file__)


class RedirectorActor(BaseActor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    @overrides
    def __init__(self):
        self.ACCEPTED_COMMANDS.update(
            {
                "CONNECT": "_on_connect_cmd",
            }
        )
        self.ACCEPTED_RETURNS.update(
            {
                "SEND": "_on_send_return",
            }
        )
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._host = config["HOST"]
        logger.debug("IP address of Registration Server: %s", self._host)
        for self._port in config["PORT_RANGE"]:
            try:
                server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                server_socket.bind((self._host, self._port))
                self._port = server_socket.getsockname()[1]
                break
            except OSError:
                try:
                    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    server_socket.bind((self._host, self._port))
                    self._port = server_socket.getsockname()[1]
                    break
                except OSError as exception:
                    logger.error("Cannot use port %d. %s", self._port, exception)
                    server_socket.close()
        try:
            server_socket.listen()  # listen(5) maybe???
        except OSError:
            self._port = None
        logger.debug("Server socket: %s", server_socket)
        self.read_list = [server_socket]
        if self._port is not None:
            logger.info("Socket listening on %s:%d", self._host, self._port)

    @overrides
    def receiveMessage(self, msg, sender):
        """Handles received Actor messages / verification of the message format"""
        if isinstance(msg, WakeupMessage):
            if msg.payload == "Connect":
                self._on_connect_cmd(msg, sender)
            return
        super().receiveMessage(msg, sender)

    @overrides
    def _on_setup_cmd(self, msg, sender):
        logger.debug("Setup redirector actor")
        super()._on_setup_cmd(msg, sender)
        if self._port is None:
            logger.critical(
                "Cannot open socket in the configured port range %s",
                config["PORT_RANGE"],
            )
            return_msg = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["UNKNOWN_PORT"]["ERROR_CODE"],
            }
        elif self.my_parent is None:
            self.my_parent = sender
            return_msg = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"IP": self._host, "PORT": self._port},
            }
        else:
            logger.debug("my_parent: %s", self.my_parent)
            return_msg = {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
        logger.debug("Setup finished with %s", return_msg)
        self.send(sender, return_msg)

    @overrides
    def _on_kill_cmd(self, msg, sender):
        """Handler to exit the redirector actor.

        Send a RETURN KILL message to the device actor (my_parent),
        then exit this redirector actor."""
        self.read_list[0].close()
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        logger.debug(
            "Confirm redirector actor exit to %s with %s",
            self.my_parent,
            return_message,
        )
        self.send(self.my_parent, return_message)
        super()._on_kill_cmd(msg, sender)

    def _on_connect_cmd(self, _msg, _sender):
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
        for _i in range(0, 5):
            try:
                data = self.conn.recv(1024)
                break
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by SARAD application software.")
                data = None
                time.sleep(5)
        if data is None:
            logger.critical("Application software seems to be dead.")
            self._on_kill_cmd({}, self.my_parent)
        elif data == b"":
            logger.debug("The application closed the socket.")
            self._on_kill_cmd({}, self.my_parent)
        else:
            logger.debug(
                "Redirect %s from app, socket %s to device actor %s",
                data,
                self._socket_info,
                self.my_parent,
            )
            self.send(self.my_parent, {"CMD": "SEND", "PAR": {"DATA": data}})

    def _on_send_return(self, msg, _sender):
        """Redirect any received reply to the socket."""
        data = msg["RESULT"]["DATA"]
        for _i in range(0, 5):
            try:
                self.conn.sendall(data)
                logger.debug(
                    "Redirect %s from instrument to socket %s", data, self._socket_info
                )
                return
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by SARAD application software.")
                time.sleep(5)
        logger.critical("Application software seems to be dead.")
        self._on_kill_cmd({}, self.my_parent)
