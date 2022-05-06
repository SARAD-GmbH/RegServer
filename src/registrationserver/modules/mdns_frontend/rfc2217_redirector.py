"""Redirect data from a TCP/IP socket to the Device Actor and vice versa using
RFC 2217

Based on an example of Chris Liechti <cliechti@gmx.net>.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import socket
import time
from typing import List

import serial.rfc2217
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (GetDeviceStatusMsg,
                                               SetupMdnsAdvertiserActorMsg)
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

    @classmethod
    def set_port_range_initialised(cls):
        """The first created redirector initialises the port range."""
        cls._isPortRangeInit = True

    def __init__(self):
        super().__init__()
        self.device_actor = None
        self._selected_port = None
        if not self._is_port_range_init:
            self.set_port_range_initialised()
            self._available_ports = list(self.PORT_RANGE)
            if not self._available_ports:
                logger.critical("No more available ports")

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
        if self.open_socket():
            my_advertiser = self._create_actor(
                MdnsAdvertiserActor, self._advertiser(instr_id)
            )
            self.send(
                my_advertiser,
                SetupMdnsAdvertiserActorMsg(
                    device_actor=self.device_actor, tcp_port=self._selected_port
                ),
            )

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self._isPortRangeInit:
            self._available_ports.append(self._selected_port)
        super().receiveMsg_KillMsg(msg, sender)

    def open_socket(self):
        """Open listening TCP/IP socket and return its port number"""
        self._selected_port = self._available_ports.pop()
        return True
