"""Actor to manage the local cluster of connected SARAD instruments.
Covers as well USB ports as native RS-232 ports.

Created
    2021-07-10

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

"""

import json
from typing import List

from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster
from sarad.sari import SaradInst
from serial.tools.list_ports import comports
from thespian.actors import (Actor, ActorExitRequest, ChildActorExited,
                             WakeupMessage)


class ClusterActor(Actor):
    """Actor to manage all local instruments connected via USB or RS-232"""

    ACCEPTED_COMMANDS = {
        "ADD": "_add",
        "REMOVE": "_remove",
        "SEND": "_send",
        "LIST": "_list",
        "LIST-USB": "_list_usb",
        "LIST-NATIVE": "_list_natives",
        "LOOP": "_loop",
        "LOOP-REMOVE": "_loop_remove",
        "DO_LOOP": "_do_loop",
        "LIST-PORTS": "_list_ports",
    }

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
        self._actors = {}
        super().__init__()
        logger.info("ClusterActor initialized")

    def _loop(self, msg: dict, sender) -> None:
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

        if not self._loop_started and self._loop:
            self.send(self.myAddress, {"CMD": "DO_LOOP"})

        self.send(
            sender,
            {
                "RETURN": "LOOP",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"DATA": ports_ok},
            },
        )

    def _loop_remove(self, msg: dict, sender) -> None:
        target = msg["PAR"]["PORT"]
        logger.info("Removing from loop: %s", target)
        ports_ok: List[str] = list()
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

    def _do_loop(self, _msg: dict, _sender) -> None:
        logger.info("Started polling: %s", self._looplist)
        self._cluster.update_connected_instruments()
        for instrument in self._cluster.connected_instruments:
            self._create_actor(instrument)
        if not self._loop_started:
            self._loop_started = True
            self.wakeupAfter(config["LOCAL_RETRY_INTERVALL"])
        else:
            logger.info("Stopped Polling")

    def _verified_ports(self) -> List[str]:
        active_ports = [port.device for port in comports()]
        return [port for port in self._looplist if port in active_ports]

    def _continue_loop(self):
        if self._looplist:
            verified_rs232_list = self._verified_ports()
            verified_rs232 = set(verified_rs232_list)
            active_ports = set(self._actors.keys())
            active_rs232_ports = verified_rs232.intersection(active_ports)
            logger.debug("Looping over %s of %s", verified_rs232_list, self._looplist)
            self._cluster.update_connected_instruments(verified_rs232_list)
            current_active_ports = set(
                instr.port for instr in self._cluster.connected_instruments
            )
            current_active_rs232 = current_active_ports.intersection(verified_rs232)
            new_ports = list(current_active_rs232.difference(active_rs232_ports))
            if new_ports == []:
                gone_ports = list(active_rs232_ports.difference(current_active_rs232))
                if gone_ports != []:
                    logger.info("Remove instruments from ports %s", gone_ports)
                    for gone_port in gone_ports:
                        self._remove_actor(gone_port)
            else:
                logger.info("Add instruments connected to ports %s", new_ports)
                for instrument in self._cluster.connected_instruments:
                    if instrument.port in new_ports:
                        self._create_actor(instrument)
        if self._loop_started and self._looplist:
            self.wakeupAfter(config["LOCAL_RETRY_INTERVALL"])
            return
        self._loop_started = False

    def _remove_from_loop(self, port: str) -> bool:
        if port in self._looplist:
            if self._looplist.count(port) >= 0:
                self._looplist.remove(port)
            return True
        return False

    def _add_to_loop(self, port: str) -> bool:
        if port in [i.device for i in comports()]:
            if self._looplist.count(port) == 0:
                self._looplist.append(port)
            return True
        return False

    def _send(self, msg: dict, sender) -> None:
        data = msg["PAR"]["DATA"]
        target = msg["PAR"]["Instrument"]
        logger.debug("Actor %s received: %s for: %s", self.globalName, data, target)
        instrument: SaradInst
        if target in self._cluster:
            reply = (
                [instrument for instrument in self._cluster if instrument == target]
                .pop()
                .get_message_payload(data, 3)["raw"]
            )

        logger.debug("and got reply from instrument: %s", reply)
        return_message = {
            "RETURN": "SEND",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": reply},
        }
        self.send(sender, return_message)

    def _list_ports(self, _msg: dict, sender) -> None:
        result: List[str] = list()

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

    def _list_usb(self, _msg: dict, sender) -> None:
        result: List[str] = list()

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
            for instrument in self._cluster.update_connected_instruments(ports)
        ]

        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-USB",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        logger.debug(return_message)
        self.send(sender, return_message)

    def _list_natives(self, _msg: dict, sender) -> None:
        result: List[str] = list()

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
            for instrument in self._cluster.update_connected_instruments(ports)
        ]

        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-NATIVE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        self.send(sender, return_message)

    def _list(self, msg: dict, sender) -> None:
        result: List[SaradInst] = list()
        target = msg["PAR"].get("PORTS", None)

        if not target:
            instruments = self._cluster.update_connected_instruments()

        if isinstance(target, str):
            instruments = self._cluster.update_connected_instruments([target])

        if isinstance(target, list):
            instruments = self._cluster.update_connected_instruments(target)

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

    def _create_actor(self, instrument):
        serial_device = instrument.port
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
        global_name = f"{device_id}.{sarad_type}.local"
        logger.debug("Create actor %s", global_name)
        self._actors[serial_device] = self.createActor(UsbActor, globalName=global_name)
        data = json.dumps(
            {
                "Identification": {
                    "Name": instrument.type_name,
                    "Family": family,
                    "Type": instrument.type_id,
                    "Serial number": instrument.serial_number,
                    "Host": "127.0.0.1",
                    "Protocol": sarad_type,
                },
                "Serial": serial_device,
            }
        )
        msg = {"CMD": "SETUP", "PAR": data}
        logger.debug("Ask to setup device actor %s with msg %s", global_name, msg)
        self.send(self._actors[serial_device], msg)

    def _remove_actor(self, gone_port):
        if gone_port in self._actors:
            self.send(self._actors[gone_port], ActorExitRequest())
            self._actors.pop(gone_port, None)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )

    def _add(self, msg, _sender):
        """Create device actors for instruments connected to
        the serial ports given in the argument list."""
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self._actors.keys())
            instruments = self._cluster.update_connected_instruments()
            current_ports = set()
            for instrument in instruments:
                current_ports.add(instrument.port)
            new_ports = current_ports.difference(old_ports)
            target = list(new_ports)
            for port in target:
                for instrument in self._cluster.connected_instruments:
                    if instrument.port == port:
                        self._create_actor(instrument)
        if isinstance(target, str):
            instruments = self._cluster.update_connected_instruments([target])
        if isinstance(target, list):
            if target == []:
                return
            instruments = self._cluster.update_connected_instruments(target)
        for instrument in instruments:
            self._create_actor(instrument)
        return

    def _remove(self, msg, _sender):
        """Kill device actors for instruments that have been unplugged from
        the serial ports given in the argument list."""
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self._actors.keys())
            instruments = self._cluster.update_connected_instruments()
            current_ports = set()
            for instrument in instruments:
                current_ports.add(instrument.port)
            gone_ports = old_ports.difference(current_ports)
            target = list(gone_ports)
            for port in target:
                self._remove_actor(port)
        if isinstance(target, str):
            self._cluster.update_connected_instruments([target])
            self._remove_actor(target)
        if isinstance(target, list):
            self._cluster.update_connected_instruments(target)
            for port in target:
                self._remove_actor(port)

    def _kill(self, msg, sender):
        pass

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, WakeupMessage):
            self._continue_loop()
            return
        if isinstance(msg, ActorExitRequest):
            self._kill(msg, sender)
            return
        if isinstance(msg, ChildActorExited):
            logger.debug("ChildActorExited received")
            return
        if not isinstance(msg, dict):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return
        return_key = msg.get("RETURN", None)
        cmd_key = msg.get("CMD", None)
        if ((return_key is None) and (cmd_key is None)) or (
            (return_key is not None) and (cmd_key is not None)
        ):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_MESSAGE"])
            return
        if cmd_key is not None:
            cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
            if cmd_function is None:
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(
                    RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                )
                return
            if getattr(self, cmd_function, None) is None:
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(
                    RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                )
                return
            getattr(self, cmd_function)(msg, sender)
