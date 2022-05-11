"""Redirect data from a TCP/IP socket to the Device Actor and vice versa using
RFC 2217

Based on an example of Chris Liechti <cliechti@gmx.net>.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import datetime
import select
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
        srv.setblocking(0)
        srv.bind(("", port))
        srv.listen(5)
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
        self.read_list = []
        self._client_socket = None

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
            self.read_list = [self.create_socket(self._selected_port)]
            logger.debug(self.read_list[0].getsockname())
        except Exception as exception:  # pylint: disable=broad-except
            logger.error("Cannot create listening socket on %d", self._selected_port)
            logger.error(exception)
        if self.read_list:
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
                logger.error("Connection reset by RegServer.")
                data = None
                time.sleep(5)
        if data is None:
            logger.error("RegServer seems to be dead.")
        elif data == b"":
            pass
        else:
            logger.debug(
                "Redirect %s from RegServer, socket %s to device actor %s",
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
                logger.error("Connection reset by RegServer.")
                time.sleep(5)
        logger.error("RegServer seems to be dead.")

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self._is_port_range_init and self._selected_port is not None:
            self._available_ports.append(self._selected_port)
        try:
            self.read_list[0].shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError, IndexError) as exception:
            logger.error("%s during socket.shutdown", exception)
        try:
            self.read_list[0].close()
        except (OSError, IndexError) as exception:
            logger.error("%s during socket.close", exception)
        super().receiveMsg_KillMsg(msg, sender)
