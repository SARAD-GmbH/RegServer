"""Redirect data from a TCP/IP socket to the Device Actor and vice versa using
RFC 2217

Based on an example of Chris Liechti <cliechti@gmx.net>.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import datetime
import socket
import time
from typing import List

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (GetDeviceStatusMsg,
                                               SetupMdnsAdvertiserActorMsg,
                                               TxBinaryMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import mdns_frontend_config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.mdns_frontend.mdns_advertiser import \
    MdnsAdvertiserActor


class Rfc2217RedirectorActor(BaseActor):
    """Redirect binary messages from socket to Device Actor and vice versa"""

    PORT_RANGE = mdns_frontend_config["MDNS_PORT_RANGE"]
    _is_port_range_init = False
    _available_ports: List[int] = []

    @staticmethod
    def _advertiser(instr_id):
        return f"advertiser-{instr_id}"

    @staticmethod
    def create_socket(port):
        """Open listening TCP/IP socket and return its port number"""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", port))
        srv.listen(1)
        srv.setblocking(0)
        return srv

    @classmethod
    def set_port_range_initialised(cls):
        """The first created redirector initialises the port range."""
        cls._is_port_range_init = True

    def __init__(self):
        super().__init__()
        self.device_actor = None
        self._selected_port = None
        if not self._is_port_range_init:
            self.set_port_range_initialised()
            self._available_ports = list(self.PORT_RANGE)
            if not self._available_ports:
                logger.critical("No more available ports")
        self.s_socket = None
        self.conn = None
        self._socket_info = None

    def receiveMsg_SetupRfc2217RedirectorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for the initialisation message from MdnsScheduler"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_actor = msg.device_actor
        self.send(self.device_actor, GetDeviceStatusMsg())

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = short_id(msg.device_id)
        try:
            self._selected_port = self._available_ports.pop()
            self.s_socket = self.create_socket(self._selected_port)
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("Cannot create listening socket on %d", self._selected_port)
            logger.error(exception)
        if self.s_socket is not None:
            my_advertiser = self._create_actor(
                MdnsAdvertiserActor, self._advertiser(instr_id)
            )
            self.send(
                my_advertiser,
                SetupMdnsAdvertiserActorMsg(
                    device_actor=self.device_actor, tcp_port=self._selected_port
                ),
            )
            logger.debug("Starting the read loop")
            self._loop()

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "Connect" and not self.on_kill:
            self._loop()

    def _loop(self):
        """Listen to socket and redirect any message from the socket to the device actor"""
        # logger.debug("%s for %s from %s", msg, self.my_id, sender)
        # read_list = list of server sockets from which we expect to read
        try:
            self.conn, self._socket_info = self.s_socket.accept()
        except BlockingIOError as exception:
            logger.debug(exception)
            self.wakeupAfter(datetime.timedelta(seconds=0.5), payload="Connect")
            return
        logger.debug("Connected by %s:%s", self._socket_info[0], self._socket_info[1])
        self.conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self._cmd_handler()
        finally:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                logger.warning("socket shutdown error")
            self.conn.close()
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
            self.receiveMsg_KillMsg(None, self.parent)
        elif data == b"":
            logger.debug("The application closed the socket.")
            self.receiveMsg_KillMsg(None, self.parent)
        else:
            logger.debug(
                "Redirect %s from app, socket %s to device actor %s",
                data,
                self._socket_info,
                self.device_actor,
            )
            self.send(self.device_actor, TxBinaryMsg(data))

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
        logger.critical("Application software seems to be dead.")
        self.receiveMsg_KillMsg(None, self.parent)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self._is_port_range_init and self._selected_port is not None:
            self._available_ports.append(self._selected_port)
        try:
            self.s_socket.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError) as exception:
            logger.error("%s during socket.shutdown", exception)
        try:
            self.s_socket.close()
        except OSError as exception:
            logger.error("%s during socket.close", exception)
        super().receiveMsg_KillMsg(msg, sender)
