"""Actor to manage the local cluster of connected SARAD instruments.
Covers as well USB ports as native RS-232 ports, addressed RS-485 as ZigBee.

:Created:
    2021-07-10

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import os
from typing import Set

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, RescanFinishedMsg,
                                               ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg,
                                               SetupComActorMsg, Status)
from registrationserver.base_actor import BaseActor
from registrationserver.config import rs485_backend_config, usb_backend_config
from registrationserver.logger import logger
from registrationserver.modules.backend.usb.com_actor import ComActor
from sarad.sari import Route  # type: ignore
from serial.tools.list_ports import comports, grep  # type: ignore


class ClusterActor(BaseActor):
    """Actor to manage all local instruments connected via USB, RS-232,
    addressed RS-485 or ZigBee"""

    @staticmethod
    def _route_id(route):
        return f"{route.port}-{route.rs485_address}-{route.zigbee_address}"

    @staticmethod
    def _route(route_id):
        split_list = route_id.split("-")
        port = split_list[0]
        rs485_address = None if split_list[1] == "None" else split_list[1]
        zigbee_address = None if split_list[2] == "None" else split_list[2]
        return Route(
            port=port, rs485_address=rs485_address, zigbee_address=zigbee_address
        )

    @staticmethod
    def _old_ports(child_actors):
        """child_actors is of form
        {actor_id: {"actor_address": <address>}}
        where actor_id is of form port-rs485_address-zigbee_address.
        This function converts this dictionary into a list of ports

        Args:
            child_actors (dict): child actors dictionary

        Returns:
            set: set of ports
        """
        result = set()
        for actor_id in child_actors:
            result.add(actor_id.split("-")[0])
        return result

    @overrides
    def __init__(self):
        self.poll_ports = {
            self._normalize(port) for port in usb_backend_config["POLL_SERIAL_PORTS"]
        }
        self.ignore_ports = {
            self._normalize(port) for port in usb_backend_config["IGNORED_SERIAL_PORTS"]
        }
        self.loop_ports: Set[str] = self.poll_ports.difference(self.ignore_ports)
        self.rs485_ports = rs485_backend_config
        # self.zigbee_ports = zigbee_backend_config
        self.zigbee_ports = []
        super().__init__()
        logger.debug("ClusterActor initialized")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._rescan()

    def receiveMsg_AddPortToLoopMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for AddPortToLoopMsg from REST API.
        Adds a port or list of ports to the list of serial interfaces that shall be polled.
        Sends the complete list back to the REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        success = False
        if isinstance(msg.ports, list):
            for port_orig in msg.ports:
                port = self._normalize(port_orig)
                success = self._add_to_loop(port)
        if isinstance(msg.ports, str):
            port = self._normalize(msg.ports)
            success = self._add_to_loop(port)
        self.send(sender, ReturnLoopPortsMsg(list(self.loop_ports)))
        if success:
            self._update()

    def receiveMsg_RemovePortFromLoopMsg(self, msg, sender) -> None:
        # pylint: disable=invalid-name
        """Handler for RemovePortFromLoopMsg from REST API.
        Removes a port or a list of ports from the list of serial interfaces
        that shall be polled.
        Sends the complete list back to the REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        success = False
        if isinstance(msg.ports, list):
            for port_orig in msg.ports:
                port = self._normalize(port_orig)
                success = self._remove_from_loop(port)
        if isinstance(msg.ports, str):
            port = self._normalize(msg.ports)
            success = self._remove_from_loop(port)
        self.send(sender, ReturnLoopPortsMsg(list(self.loop_ports)))
        if success:
            self._update()

    @staticmethod
    def _normalize(serial: str):
        """Bring the port id into a normalized form"""
        if os.name == "posix":
            return os.path.realpath(serial)
        return serial

    def active_ports(self) -> Set[str]:
        """SARAD instruments can be connected:
        1. by RS232 on a native RS232 interface at the computer
        2. via their built in FT232R USB-serial converter
        3. via an external USB-serial converter (Prolific, Prolific fake, FTDI, QinHeng Electronics)
        4. via the SARAD ZigBee coordinator with FT232R"""
        # Get the list of accessible native RS-232 ports
        active_ports = comports()
        logger.debug("RS-232 or UART ports: %s", [port.device for port in active_ports])
        toxic_ports = []
        for hwid_filter in usb_backend_config["IGNORED_HWIDS"]:
            toxic_ports.extend(grep(hwid_filter))
        for port in toxic_ports:
            self.ignore_ports.add(port.device)
        # Actually we don't want the ports but the port devices.
        set_of_ports = set()
        for port in active_ports:
            set_of_ports.add(port.device)
        result = set()
        for port in set_of_ports:
            if port not in self.ignore_ports:
                result.add(self._normalize(port))
        logger.debug("Ignored ports: %s", self.ignore_ports)
        logger.debug("Active ports: %s", result)
        return result

    def _remove_from_loop(self, port: str) -> bool:
        logger.debug("[_remove_from_loop] %s", port)
        normalized_port = self._normalize(port)
        if normalized_port in self.loop_ports:
            self.loop_ports.remove(normalized_port)
            return True
        return False

    def _add_to_loop(self, port: str) -> bool:
        """Adds a port to the list of serial interfaces that shall be polled."""
        logger.debug("[_add_to_loop] %s", port)
        if port in self.active_ports():
            if port not in self.loop_ports:
                self.loop_ports.add(port)
            return True
        return False

    def receiveMsg_GetLocalPortsMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetLocalPortsMsg request from REST API"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        ports = [
            {"PORT": port.device, "PID": port.pid, "VID": port.vid}
            for port in comports()
        ]
        self.send(sender, ReturnLocalPortsMsg(ports))

    def receiveMsg_GetUsbPortsMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetUsbPortsMsg request from REST API"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        ports = [port.device for port in comports() if port.vid and port.pid]
        self.send(sender, ReturnUsbPortsMsg(ports))

    def receiveMsg_GetNativePortsMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetNativePortsMsg request from REST API"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        ports = [port.device for port in comports() if not port.pid]
        self.send(sender, ReturnNativePortsMsg(ports))

    def _create_and_setup_actor(self, route, loop_interval):
        logger.debug("[_create_and_setup_actor]")
        com_actor = self._create_actor(ComActor, self._route_id(route), None)
        self.send(com_actor, SetupComActorMsg(route, loop_interval))

    def _remove_actor(self, route):
        route_id = self._route_id(route)
        logger.debug("[_remove_actor] %s", route_id)
        try:
            self.send(self.child_actors[route_id]["actor_address"], KillMsg())
        except IndexError:
            logger.error("Tried to remove %s, that never was added properly.", route_id)

    def _rescan(self):
        """Look for new resp. gone serial devices."""
        current_ports = self.active_ports()
        old_ports = self._old_ports(self.child_actors)
        new_ports = current_ports.difference(old_ports)
        gone_ports = old_ports.difference(current_ports)
        for port in new_ports:
            loop_interval = 0
            if port in self.rs485_ports:
                for address in self.rs485_ports[port]:
                    route = Route(port=port, rs485_address=address, zigbee_address=None)
                    self._create_and_setup_actor(route, loop_interval)
            elif port in self.zigbee_ports:
                pass
                # TODO: zigbee
            else:
                route = Route(port=port, rs485_address=None, zigbee_address=None)
                if port in self.loop_ports:
                    loop_interval = usb_backend_config["LOCAL_RETRY_INTERVAL"]
                self._create_and_setup_actor(route, loop_interval)
        for port in gone_ports:
            if port in self.rs485_ports:
                for address in self.rs485_ports[port]:
                    route = Route(port=port, rs485_address=address, zigbee_address=None)
                    self._remove_actor(route)
            elif port in self.zigbee_ports:
                pass
                # TODO: zigbee
            else:
                route = Route(port=port, rs485_address=None, zigbee_address=None)
                self._remove_actor(route)

    def _update(self):
        """Trigger all Child Actors to update their instruments."""
        for child_id, value in self.child_actors.items():
            route = self._route(child_id)
            child_address = value["actor_address"]
            loop_interval = 0
            if route.port in self.loop_ports:
                loop_interval = usb_backend_config["LOCAL_RETRY_INTERVAL"]
            self.send(child_address, SetupComActorMsg(route, loop_interval))

    def receiveMsg_InstrAddedMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Create ComActors for newly detected serial devices."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._rescan()

    def receiveMsg_InstrRemovedMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Kill ComActors for instruments that have been unplugged from
        the serial ports given in the argument list."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._rescan()

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Rescan for serial devices and create or remove ComActors
        accordingly."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._rescan()
        self._update()
        self.send(sender, RescanFinishedMsg(Status.OK))
