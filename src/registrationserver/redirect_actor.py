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

from registrationserver.actor_messages import SocketMsg, Status, TxBinaryMsg
from registrationserver.base_actor import BaseActor
from registrationserver.config import config, rest_frontend_config
from registrationserver.logger import logger


class RedirectorActor(BaseActor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._host = config["MY_IP"]
        self._port = None
        self.read_list = None
        logger.info("Redirector Actor initialized")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "loop":
            self._loop()

    def _loop(self):
        if not self.on_kill:
            try:
                # Listen to socket and redirect any message from the socket to the device actor
                server_socket = self.read_list[0]
                timeout = 0.1
                readable, _writable, _errored = select.select(
                    self.read_list, [], [], timeout
                )
                for self.conn in readable:
                    if self.conn is server_socket:
                        self._client_socket, self._socket_info = server_socket.accept()
                        self.read_list.append(self._client_socket)
                        logger.debug("Connection from %s", self._socket_info)
                    else:
                        self._cmd_handler()
            except (ValueError, IOError) as exception:
                logger.error("%s in _loop function of redirector", exception)
            self.wakeupAfter(datetime.timedelta(seconds=0.055), payload="loop")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        logger.debug("Setup redirector actor")
        super().receiveMsg_SetupMsg(msg, sender)
        for self._port in rest_frontend_config["PORT_RANGE"]:
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.bind((self._host, self._port))
                self._port = server_socket.getsockname()[1]
                break
            except OSError:
                try:
                    server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
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
        if self._port is None:
            logger.critical(
                "Cannot open socket in the configured port range %s",
                rest_frontend_config["PORT_RANGE"],
            )
            return_msg = SocketMsg(ip_address="", port=0, status=Status.UNKNOWN_PORT)
        elif self.my_parent is None:
            self.my_parent = sender
            return_msg = SocketMsg(
                ip_address=self._host, port=self._port, status=Status.OK
            )
        else:
            logger.debug("my_parent: %s", self.my_parent)
            return_msg = SocketMsg(
                ip_address=self._host, port=self._port, status=Status.OK_SKIPPED
            )
        logger.debug("Setup finished with %s", return_msg)
        self.send(sender, return_msg)
        logger.debug("Start socket loop")
        self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="loop")

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        try:
            self.read_list[0].close()
        except (ValueError, IOError) as exception:
            logger.error("%s in KillMsg handler of redirector", exception)
        super()._kill_myself(register)

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
            except (ValueError, IOError) as exception:
                logger.error("%s in _sendall function", exception)
        if data is None:
            logger.critical("Application software seems to be dead.")
            self._kill_myself()
        elif data == b"":
            logger.debug("The application closed the socket.")
            self._kill_myself()
        else:
            logger.debug(
                "Redirect %s from app, socket %s to device actor %s",
                data,
                self._socket_info,
                self.my_parent,
            )
            self.send(self.my_parent, TxBinaryMsg(data))

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Redirect any received reply to the socket."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for _i in range(0, 5):
            try:
                self.conn.sendall(msg.data)
                return
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by SARAD application software.")
                time.sleep(5)
            except (ValueError, IOError) as exception:
                logger.error("%s in RxBinaryMsg handler", exception)
        logger.critical("Application software seems to be dead.")
        self._kill_myself()
