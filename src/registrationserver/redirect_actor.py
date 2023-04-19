"""Creates a listening server socket and forwards pakets received over this
socket as actor messages to the device actor.

:Created:
    2020-12-01

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-redirect_actor.puml

"""
import select
import socket
import time
from threading import Thread

from overrides import overrides  # type: ignore

from registrationserver.actor_messages import (KillMsg, SocketMsg, Status,
                                               TxBinaryMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config, rest_frontend_config
from registrationserver.logger import logger


class RedirectorActor(BaseActor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self.conn = None
        self.read_list = None
        self.socket_loop_thread = Thread(
            target=self._loop,
            daemon=True,
        )
        self.send_thread = Thread(
            target=self._sendall,
            kwargs={"data": None},
            daemon=True,
        )
        logger.debug("Redirector Actor initialized")

    def _loop(self):
        while self.read_list:
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
                            client_socket, socket_info = server_socket.accept()
                            self.read_list.append(client_socket)
                            logger.debug("Connection from %s", socket_info)
                        else:
                            self._cmd_handler()
                except ValueError as exception:
                    logger.error("%s in _loop function of redirector", exception)

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        logger.debug("Setup redirector actor")
        super().receiveMsg_SetupMsg(msg, sender)
        for port in rest_frontend_config["PORT_RANGE"]:
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.bind((config["MY_IP"], port))
                port = server_socket.getsockname()[1]
                break
            except OSError:
                try:
                    server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    server_socket.bind((config["MY_IP"], port))
                    port = server_socket.getsockname()[1]
                    break
                except OSError as exception:
                    logger.error("Cannot use port %d. %s", port, exception)
                    server_socket.close()
        try:
            server_socket.listen()  # listen(5) maybe???
        except OSError:
            port = None
        logger.debug("Server socket: %s", server_socket)
        self.read_list = [server_socket]
        if port is None:
            logger.critical(
                "Cannot open socket in the configured port range %s",
                rest_frontend_config["PORT_RANGE"],
            )
            return_msg = SocketMsg(ip_address="", port=0, status=Status.UNKNOWN_PORT)
        elif self.my_parent is None:
            self.my_parent = sender
            return_msg = SocketMsg(
                ip_address=config["MY_IP"], port=port, status=Status.OK
            )
        else:
            logger.debug("my_parent: %s", self.my_parent)
            return_msg = SocketMsg(
                ip_address=config["MY_IP"], port=port, status=Status.OK_SKIPPED
            )
        logger.debug("Setup finished with %s", return_msg)
        self.send(sender, return_msg)
        logger.debug("Start socket loop")
        self.socket_loop_thread.start()

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        """Handler to exit the redirector actor."""
        try:
            self.read_list[0].close()
        except ValueError as exception:
            logger.error("%s in KillMsg handler of redirector", exception)
        super().receiveMsg_KillMsg(msg, sender)

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
            except ValueError as exception:
                logger.error("%s in _cmd_handler function", exception)
                data = None
        if data is None:
            logger.critical("Application software seems to be dead.")
            self.send(self.myAddress, KillMsg())
        elif data == b"":
            logger.debug("The application closed the socket.")
            self.send(self.myAddress, KillMsg())
        else:
            logger.debug(
                "Redirect %s from app to device actor %s",
                data,
                self.my_parent,
            )
            self.send(self.my_parent, TxBinaryMsg(data))

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Redirect any received reply to the socket."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send_thread = Thread(
            target=self._sendall,
            kwargs={"data": msg.data},
            daemon=True,
        )
        self.send_thread.start()

    def _sendall(self, data):
        for _i in range(0, 5):
            try:
                self.conn.sendall(data)
                return
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by SARAD application software.")
                time.sleep(5)
            except ValueError as exception:
                logger.error("%s in _sendall function", exception)
        logger.critical("Application software seems to be dead.")
        self.send(self.myAddress, KillMsg())
