"""Actor to manage the local cluster of connected SARAD instruments.
Covers as well USB ports as native RS-232 ports.

:Created:
    2021-07-10

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from typing import List

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ReturnLocalPortsMsg,
                                               ReturnLoopPortsMsg,
                                               ReturnNativePortsMsg,
                                               ReturnUsbPortsMsg, RxBinaryMsg,
                                               SetDeviceStatusMsg, SetupMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster  # type: ignore
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore
from serial.tools.list_ports import comports  # type: ignore
from thespian.actors import ActorExitRequest  # type: ignore


class ClusterActor(BaseActor):
    """Actor to manage all local instruments connected via USB or RS-232"""

    @staticmethod
    def _switch_to_port_key(child_actors):
        """child_actors is of form
        {actor_id: {"actor_address": <address>, "port": <port>}}
        This function converts this dictionary into
        {port: actor_address}

        Args:
            child_actors (dict): child actors dictionary

        Returns:
            dict: dictionary of form {port: actor_address}
        """
        result = {}
        try:
            for _actor_id, value in child_actors.items():
                result[value["port"]] = value["actor_address"]
        except KeyError:
            return {}
        return result

    @overrides
    def __init__(self):
        self._loop_started: bool = False
        self.native_ports = set(config.get("NATIVE_SERIAL_PORTS", []))
        self.ignore_ports = set(config.get("IGNORED_SERIAL_PORTS", []))
        self._looplist: List[str] = list(
            self.native_ports.difference(self.ignore_ports)
        )
        self._cluster: SaradCluster = SaradCluster(
            native_ports=list(self.native_ports), ignore_ports=list(self.ignore_ports)
        )
        self._actor_system = None
        super().__init__()
        logger.debug("ClusterActor initialized")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        logger.debug("Start polling RS-232 ports.")
        self._do_loop()

    def receiveMsg_AddPortToLoopMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for AddPortToLoopMsg from REST API.
        Adds a port or list of ports to the list of serial interfaces that shall be polled.
        Sends the complete list back to the REST API."""
        logger.info("Adding %s to loop", msg.port)
        ports_ok: List[str] = []
        if isinstance(msg.ports, list):
            for port in msg.ports:
                if self._add_to_loop(port):
                    ports_ok.append(port)
        if isinstance(msg.ports, str):
            if self._add_to_loop(msg.ports):
                ports_ok.append(msg.ports)
        if not self._loop_started:
            self._do_loop()
        self.send(sender, ReturnLoopPortsMsg(ports_ok))

    def receiveMsg_RemovePortFromLoopMsg(self, msg, sender) -> None:
        # pylint: disable=invalid-name
        """Handler for RemovePortFromLoopMsg from REST API.
        Removes a port or a list of ports from the list of serial interfaces
        that shall be polled.
        Sends the complete list back to the REST API."""
        logger.info("Removing %s from loop", msg.ports)
        ports_ok: List[str] = []
        if isinstance(msg.ports, list):
            for port in msg.ports:
                if self._remove_from_loop(port):
                    ports_ok.append(port)
        if isinstance(msg.ports, str):
            if self._remove_from_loop(msg.ports):
                ports_ok.append(msg.ports)
        if not self._looplist:
            self._loop_started = False
        self.send(sender, ReturnLoopPortsMsg(ports_ok))

    def _do_loop(self) -> None:
        logger.debug("[_do_loop]")
        logger.info("Started polling: %s", self._looplist)
        self._cluster.update_connected_instruments()
        for instrument in self._cluster.connected_instruments:
            self._create_and_setup_actor(instrument)
        if not self._loop_started:
            self._loop_started = True
            self.wakeupAfter(config["LOCAL_RETRY_INTERVAL"])
        else:
            logger.info("Stopped Polling")

    def _verified_ports(self) -> List[str]:
        logger.debug("[_verified_ports]")
        active_ports = [port.device for port in comports()]
        return [port for port in self._looplist if port in active_ports]

    def _continue_loop(self):
        logger.debug("[_continue_loop] Check for instruments on RS-232")
        if self._looplist:
            verified_rs232_list = self._verified_ports()
            verified_rs232 = set(verified_rs232_list)
            port_actors = self._switch_to_port_key(self.child_actors)
            active_ports = set(port_actors.keys())
            active_rs232_ports = verified_rs232.intersection(active_ports)
            logger.debug("Looping over %s of %s", verified_rs232_list, self._looplist)
            self._cluster.update_connected_instruments(
                ports_to_test=verified_rs232_list
            )
            current_active_ports = set(
                instr.port for instr in self._cluster.connected_instruments
            )
            current_active_rs232 = current_active_ports.intersection(verified_rs232)
            new_ports = list(current_active_rs232.difference(active_rs232_ports))
            if not new_ports:
                gone_ports = list(active_rs232_ports.difference(current_active_rs232))
                if gone_ports:
                    logger.info("Remove instruments from ports %s", gone_ports)
                    for gone_port in gone_ports:
                        self._remove_actor(gone_port)
            else:
                logger.info("Add instruments connected to ports %s", new_ports)
                for instrument in self._cluster.connected_instruments:
                    if instrument.port in new_ports:
                        self._create_and_setup_actor(instrument)
        else:
            logger.debug("List of native RS-232 interfaces empty. Stop the loop.")
        if self._loop_started and self._looplist:
            self.wakeupAfter(config["LOCAL_RETRY_INTERVAL"])
            return
        self._loop_started = False

    def _remove_from_loop(self, port: str) -> bool:
        logger.debug("[_remove_from_loop]")
        if port in self._looplist:
            if self._looplist.count(port) >= 0:
                self._looplist.remove(port)
            return True
        return False

    def _add_to_loop(self, port: str) -> bool:
        """Adds a port to the list of serial interfaces that shall be polled
        in the _continue_loop() function."""
        logger.debug("[_add_to_loop]")
        if port in [i.device for i in comports()]:
            if self._looplist.count(port) == 0:
                self._looplist.append(port)
            return True
        return False

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for binary message from App to Instrument."""
        logger.debug("[on TxBinaryMsg]")
        data = msg.data
        target = msg.instrument
        logger.debug("Actor %s received: %s for: %s", self.globalName, data, target)
        instrument: SaradInst = None
        if target in self._cluster:
            try:
                reply = (
                    [instrument for instrument in self._cluster if instrument == target]
                    .pop()
                    .get_message_payload(data, 5)
                )
            except (SerialException, OSError):
                logger.error("Connection to %s lost", target)
                reply = {"is_valid": False, "is_last_frame": True}
        logger.debug("and got reply from instrument: %s", reply)
        if reply["is_valid"]:
            self.send(sender, RxBinaryMsg(reply["raw"]))
            while not reply["is_last_frame"]:
                try:
                    reply = (
                        [
                            instrument
                            for instrument in self._cluster
                            if instrument == target
                        ]
                        .pop()
                        .get_next_payload(5)
                    )
                    self.send(sender, RxBinaryMsg(reply["raw"]))
                except (SerialException, OSError):
                    logger.error("Connection to %s lost", target)
                    reply = {"is_valid": False, "is_last_frame": True}
        if not reply["is_valid"]:
            logger.warning(
                "Invalid binary message from instrument. Removing %s", sender
            )
            self._remove_actor(self._get_actor_id(sender, self.child_actors))

    def receiveMsg_FreeInstrMsg(self, msg, _sender) -> None:
        # pylint: disable=invalid-name
        """Handler for FreeInstrMsg indicating that the instrument was released by the App.
        Used here to release the serial interface with the release_instrument() function."""
        logger.debug("[on FreeInstrMsg]")
        instrument: SaradInst = None
        if msg.instrument in self._cluster:
            (
                [
                    instrument
                    for instrument in self._cluster
                    if instrument == msg.instrument
                ]
                .pop()
                .release_instrument()
            )

    def receiveMsg_GetLocalPortsMsg(self, _msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetLocalPortsMsg request from REST API"""
        logger.debug("[on GetLocalPortsMsg]")
        ports = [
            {"PORT": port.device, "PID": port.pid, "VID": port.vid}
            for port in comports()
        ]
        self.send(sender, ReturnLocalPortsMsg(ports))

    def receiveMsg_GetUsbPortsMsg(self, _msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetUsbPortsMsg request from REST API"""
        logger.debug("[on GetUsbPortsMsg]")
        ports = [port.device for port in comports() if port.vid and port.pid]
        self.send(sender, ReturnUsbPortsMsg(ports))

    def receiveMsg_GetNativePortsMsg(self, _msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetNativePortsMsg request from REST API"""
        logger.debug("[on GetNativePortsMsg]")
        ports = [port.device for port in comports() if not port.pid]
        self.send(sender, ReturnNativePortsMsg(ports))

    def _create_and_setup_actor(self, instrument):
        logger.debug("[_create_and_setup_actor]")
        family = instrument.family["family_id"]
        device_id = instrument.device_id
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "[Add Instrument]: unknown instrument family (index: %s)",
                family,
            )
            sarad_type = "unknown"
        actor_id = f"{device_id}.{sarad_type}.local"
        logger.debug("Create actor %s", actor_id)
        device_actor = self._create_actor(UsbActor, actor_id)
        self.child_actors[actor_id]["port"] = instrument.port
        self.send(
            device_actor,
            SetupMsg(actor_id=actor_id, parent_id=self.my_id, app_type=self.app_type),
        )
        device_status = {
            "Identification": {
                "Name": instrument.type_name,
                "Family": family,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
                "Host": "127.0.0.1",
                "Protocol": sarad_type,
            },
            "Serial": instrument.port,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))

    def _remove_actor(self, gone_port):
        logger.debug("[_remove_actor]")
        port_actors = self._switch_to_port_key(self.child_actors)
        gone_address = port_actors[gone_port]
        gone_id = self._get_actor_id(gone_address, self.child_actors)
        if gone_port in port_actors:
            logger.debug("Send ActorExitRequest to device actor.")
            self.send(gone_address, ActorExitRequest())
            self.child_actors.pop(gone_id, None)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )

    def receiveMsg_InstrAddedMsg(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Create device actors for instruments connected to
        the serial ports given in the argument list."""
        logger.debug("[on InstrAddedMsg]")
        port_actors = self._switch_to_port_key(self.child_actors)
        old_ports = set(port_actors.keys())
        new_instruments = self._cluster.update_connected_instruments(
            ports_to_skip=list(old_ports)
        )
        new_ports = set()
        for instrument in new_instruments:
            new_ports.add(instrument.port)
        target = list(new_ports)
        for port in target:
            for instrument in self._cluster.connected_instruments:
                if instrument.port == port:
                    self._create_and_setup_actor(instrument)

    def receiveMsg_InstrRemovedMsg(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Kill device actors for instruments that have been unplugged from
        the serial ports given in the argument list."""
        logger.debug("[on InstrRemoveMsg]")
        port_actors = self._switch_to_port_key(self.child_actors)
        old_ports = set(port_actors.keys())
        current_ports = set(port.device for port in comports())
        gone_ports = old_ports.difference(current_ports)
        logger.debug("Call _remove_actor for %s", gone_ports)
        for port in gone_ports:
            self._remove_actor(port)

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        self._continue_loop()
