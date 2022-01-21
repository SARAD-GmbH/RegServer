"""Actor to manage the local cluster of connected SARAD instruments.
Covers as well USB ports as native RS-232 ports.

:Created:
    2021-07-10

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from typing import Any, Dict, List

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import SetDeviceStatusMsg, SetupMsg
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.helpers import get_key
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster
from sarad.sari import SaradInst
from serial import SerialException
from serial.tools.list_ports import comports
from thespian.actors import ActorExitRequest


class ClusterActor(BaseActor):
    """Actor to manage all local instruments connected via USB or RS-232"""

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
        self._kill_flag = False
        super().__init__()
        logger.debug("ClusterActor initialized")

    def _on_loop_cmd(self, msg, sender) -> None:
        target = msg["PAR"]["PORT"]
        logger.info("Adding to loop: %s", target)
        ports_ok: List[str] = []
        if isinstance(target, list):
            for port in target:
                if self._add_to_loop(port):
                    ports_ok.append(port)
        if isinstance(target, str):
            if self._add_to_loop(target):
                ports_ok.append(target)
        if not self._loop_started and self._on_loop_cmd:
            self.send(self.myAddress, {"CMD": "DO_LOOP"})
        self.send(
            sender,
            {
                "RETURN": "LOOP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"DATA": ports_ok},
            },
        )

    def _on_loop_remove_cmd(self, msg, sender) -> None:
        target = msg["PAR"]["PORT"]
        logger.info("Removing from loop: %s", target)
        ports_ok: List[str] = []
        if isinstance(target, list):
            for port in target:
                if self._remove_from_loop(port):
                    ports_ok.append(port)
        if isinstance(target, str):
            if self._remove_from_loop(target):
                ports_ok.append(target)
        if not self._looplist:
            self._loop_started = False
        self.send(
            sender,
            {
                "RETURN": "LOOP-REMOVE",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"DATA": ports_ok},
            },
        )

    def _on_do_loop_cmd(self, _msg, _sender) -> None:
        logger.debug("[_on_do_loop_cmd]")
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
            active_ports = set(self.child_actors.keys())
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
        logger.debug("[_add_to_loop]")
        if port in [i.device for i in comports()]:
            if self._looplist.count(port) == 0:
                self._looplist.append(port)
            return True
        return False

    def _on_send_cmd(self, msg, sender) -> None:
        logger.debug("[_on_send_cmd]")
        data = msg["PAR"]["DATA"]
        target = msg["PAR"]["Instrument"]
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
            return_message = {
                "RETURN": "SEND",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"DATA": reply["raw"]},
            }
            self.send(sender, return_message)
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
                    return_message = {
                        "RETURN": "SEND",
                        "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                        "RESULT": {"DATA": reply["raw"]},
                    }
                    self.send(sender, return_message)
                except (SerialException, OSError):
                    logger.error("Connection to %s lost", target)
                    reply = {"is_valid": False, "is_last_frame": True}
        if not reply["is_valid"]:
            logger.warning(
                "Invalid binary message from instrument. Removing %s", sender
            )
            self._remove_actor(get_key(sender, self.child_actors))

    def _on_free_cmd(self, msg, _sender) -> None:
        logger.debug("[_on_free_cmd]")
        target = msg["PAR"]["Instrument"]
        instrument: SaradInst = None
        if target in self._cluster:
            (
                [instrument for instrument in self._cluster if instrument == target]
                .pop()
                .release_instrument()
            )

    def _on_list_ports_cmd(self, _msg, sender) -> None:
        logger.debug("[_on_list_ports_cmd]")
        result: List[Dict[str, Any]] = []
        ports = [
            {"PORT": port.device, "PID": port.pid, "VID": port.vid}
            for port in comports()
        ]
        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-PORTS",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": ports},
        }
        self.send(sender, return_message)

    def _on_list_usb_cmd(self, _msg, sender) -> None:
        logger.debug("[_on_list_usb_cmd]")
        result: List[Dict[str, Any]] = []
        ports = [port.device for port in comports() if port.vid and port.pid]
        result = [
            {
                "Device ID": instrument.device_id,
                "Serial Device": instrument.port,
                "Family": instrument.family["family_id"],
                "Name": instrument.type_name,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
            }
            for instrument in self._cluster.update_connected_instruments(
                ports_to_test=ports
            )
        ]
        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-USB",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        logger.debug(return_message)
        self.send(sender, return_message)

    def _on_list_natives_cmd(self, _msg, sender) -> None:
        logger.debug("[_on_list_natives_cmd]")
        result: List[Dict[str, Any]] = []
        ports = [port.device for port in comports() if not port.pid]
        result = [
            {
                "Device ID": instrument.device_id,
                "Serial Device": instrument.port,
                "Family": instrument.family["family_id"],
                "Name": instrument.type_name,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
            }
            for instrument in self._cluster.update_connected_instruments(
                ports_to_test=ports
            )
        ]
        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-NATIVE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        self.send(sender, return_message)

    def _on_list_cmd(self, msg, sender) -> None:
        logger.debug("[_on_list_cmd]")
        result: List[Dict[str, Any]] = []
        target = msg["PAR"].get("PORTS", None)
        if not target:
            instruments = self._cluster.update_connected_instruments()
        if isinstance(target, str):
            instruments = self._cluster.update_connected_instruments(
                ports_to_test=[target]
            )
        if isinstance(target, list):
            instruments = self._cluster.update_connected_instruments(
                ports_to_test=target
            )
        result = [
            {
                "Device ID": instrument.device_id,
                "Serial Device": instrument.port,
                "Family": instrument.family["family_id"],
                "Name": instrument.type_name,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
            }
            for instrument in instruments
        ]
        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        self.send(sender, return_message)

    def _create_and_setup_actor(self, instrument):
        logger.debug("[_create_and_setup_actor]")
        actor_id = instrument.port
        family = instrument.family["family_id"]
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
        logger.debug("Create actor %s", actor_id)
        device_actor = self._create_actor(UsbActor, actor_id)
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
            "Serial": actor_id,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))

    def _remove_actor(self, gone_port):
        logger.debug("[_remove_actor]")
        if gone_port in self.child_actors:
            logger.debug("Send ActorExitRequest to device actor.")
            self.send(self.child_actors[gone_port], ActorExitRequest())
            self.child_actors.pop(gone_port, None)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )

    def _on_add_cmd(self, msg, _sender):
        """Create device actors for instruments connected to
        the serial ports given in the argument list."""
        logger.debug("[_on_add_cmd]")
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self.child_actors.keys())
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
        else:
            assert isinstance(target, list)
            if target == []:
                return
            instruments = self._cluster.update_connected_instruments(
                ports_to_test=target
            )
            for instrument in instruments:
                self._create_and_setup_actor(instrument)
        return

    def _on_remove_cmd(self, msg, _sender):
        """Kill device actors for instruments that have been unplugged from
        the serial ports given in the argument list."""
        logger.debug("[_on_remove_cmd]")
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self.child_actors.keys())
            current_ports = set(port.device for port in comports())
            gone_ports = old_ports.difference(current_ports)
            logger.debug("Call _remove_actor for %s", gone_ports)
            for port in gone_ports:
                self._remove_actor(port)
        else:
            assert isinstance(target, list)
            self._cluster.update_connected_instruments(ports_to_test=target)
            for port in target:
                self._remove_actor(port)

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        self._continue_loop()
