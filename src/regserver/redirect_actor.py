"""Creates a listening server socket and forwards pakets received over this
socket as actor messages to the device actor.

:Created:
    2020-12-01

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import select
import socket
from threading import Thread
from time import sleep

from overrides import overrides  # type: ignore

from regserver.actor_messages import SocketMsg, Status, TxBinaryMsg
from regserver.base_actor import BaseActor
from regserver.config import config, rest_frontend_config
from regserver.logger import logger


class RedirectorActor(BaseActor):
    """Create listening server socket for binary pakets from a SARAD© Application"""

    @overrides
    def __init__(self):
        super().__init__()
        self.my_parent = None
        self._client_socket = None
        self._socket_info = None
        self.conn = None
        self._address = (config["MY_IP"], None)
        self.read_list = None
        self.socket_loop_thread = Thread(
            target=self._loop,
        )

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "loop":
            self._loop()

    def _loop(self):
        logger.info("Redirector thread in %s initialized", self.my_id)
        while not self.on_kill:
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
        self.read_list[0].close()
        logger.info("Socket at port %d closed.", self._address[1])
        logger.info("Finish socket_loop_thread")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        logger.debug("Setup redirector actor")
        super().receiveMsg_SetupMsg(msg, sender)
        for port in rest_frontend_config["PORT_RANGE"]:
            self._address = (self._address[0], port)
            for res in socket.getaddrinfo(
                self._address[0],
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
                socket.AI_PASSIVE,
            ):
                af, socktype, proto, _canonname, sa = res
                try:
                    server_socket = socket.socket(af, socktype, proto)
                    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                except OSError as exception:
                    logger.error("Cannot use port %d. %s", self._address[1], exception)
                    server_socket = None
                    self._address = (self._address[0], None)
                    continue
                try:
                    server_socket.bind(sa)
                    server_socket.listen(1)
                except OSError as exception:
                    logger.error(
                        "Cannot listen on port %d. %s", self._address[1], exception
                    )
                    server_socket.close()
                    server_socket = None
                    self._address = (self._address[0], None)
                    continue
                break
            if server_socket is not None:
                break
        logger.debug("Server socket: %s", server_socket)
        self.read_list = [server_socket]
        if self._address[1] is None:
            logger.critical(
                "Cannot open socket in the configured port range %s",
                rest_frontend_config["PORT_RANGE"],
            )
            return_msg = SocketMsg(ip_address="", port=0, status=Status.UNKNOWN_PORT)
        elif self.my_parent is None:
            self.my_parent = sender
            return_msg = SocketMsg(
                ip_address=self._address[0], port=self._address[1], status=Status.OK
            )
        else:
            logger.debug("my_parent: %s", self.my_parent)
            return_msg = SocketMsg(
                ip_address=self._address[0],
                port=self._address[1],
                status=Status.OK_SKIPPED,
            )
        logger.debug("Setup finished with %s", return_msg)
        self.send(sender, return_msg)
        logger.debug("Start socket loop")
        self.socket_loop_thread.start()

    def _cmd_handler(self):
        """Handle a binary SARAD command received via the socket."""
        for _i in range(0, 5):
            try:
                data = self.conn.recv(1024)
                break
            except (ConnectionResetError, BrokenPipeError):
                logger.error("Connection reset by SARAD application software.")
                data = None
                sleep(0.1)
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
                sleep(0.1)
            except (ValueError, IOError) as exception:
                logger.error("%s in RxBinaryMsg handler", exception)
        logger.critical("Application software seems to be dead.")
        self._kill_myself()
