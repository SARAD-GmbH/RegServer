"""Actor to manage the local cluster of connected SARAD instruments.
Covers as well USB ports as native RS-232 ports.

:Created:
    2021-07-10

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from typing import Any, Dict, List

from registrationserver.config import config
from registrationserver.helpers import get_key
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.modules.usb.usb_actor import UsbActor
from registrationserver.shutdown import system_shutdown
from sarad.cluster import SaradCluster
from sarad.sari import SaradInst
from serial import SerialException
from serial.tools.list_ports import comports
from thespian.actors import (Actor, ActorExitRequest, ChildActorExited,
                             PoisonMessage, WakeupMessage)


class ClusterActor(Actor):
    """Actor to manage all local instruments connected via USB or RS-232"""

    ACCEPTED_COMMANDS = {
        "ADD": "_add",
        "FREE": "_free",
        "REMOVE": "_remove",
        "SEND": "_send",
        "LIST": "_list",
        "LIST-USB": "_list_usb",
        "LIST-NATIVE": "_list_natives",
        "LOOP": "_loop",
        "LOOP-REMOVE": "_loop_remove",
        "DO_LOOP": "_do_loop",
        "LIST-PORTS": "_list_ports",
        "KILL": "_kill",
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
        self._actor_system = None
        self._kill_flag = False
        super().__init__()
        logger.debug("ClusterActor initialized")

    def _loop(self, msg, sender) -> None:
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

    def _loop_remove(self, msg, sender) -> None:
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

    def _do_loop(self, _msg, _sender) -> None:
        logger.debug("[_do_loop]")
        logger.info("Started polling: %s", self._looplist)
        self._cluster.update_connected_instruments()
        for instrument in self._cluster.connected_instruments:
            self._create_actor(instrument)
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
        logger.debug("[_continue_loop]")
        if self._looplist:
            verified_rs232_list = self._verified_ports()
            verified_rs232 = set(verified_rs232_list)
            active_ports = set(self._actors.keys())
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

    def _send(self, msg, sender) -> None:
        logger.debug("[_send]")
        data = msg["PAR"]["DATA"]
        target = msg["PAR"]["Instrument"]
        logger.debug("Actor %s received: %s for: %s", self.globalName, data, target)
        instrument: SaradInst
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
            self._remove_actor(get_key(sender, self._actors))

    def _free(self, msg, _sender) -> None:
        logger.debug("[_free]")
        target = msg["PAR"]["Instrument"]
        instrument: SaradInst
        if target in self._cluster:
            (
                [instrument for instrument in self._cluster if instrument == target]
                .pop()
                .release_instrument()
            )

    def _list_ports(self, _msg, sender) -> None:
        logger.debug("[_list_ports]")
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

    def _list_usb(self, _msg, sender) -> None:
        logger.debug("[_list_usb]")
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

    def _list_natives(self, _msg, sender) -> None:
        logger.debug("[_list_natives]")
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

    def _list(self, msg, sender) -> None:
        logger.debug("[_list]")
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

    def _create_actor(self, instrument):
        logger.debug("[_create_actor]")
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
        self._actors[serial_device] = self.createActor(UsbActor)
        data = {
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
        msg = {"CMD": "SETUP", "ID": global_name, "PAR": data}
        logger.debug("Ask to setup device actor %s with msg %s", global_name, msg)
        self.send(self._actors[serial_device], msg)

    def _remove_actor(self, gone_port):
        logger.debug("[_remove_actor]")
        if gone_port in self._actors:
            logger.debug("Send ActorExitRequest to device actor.")
            self.send(self._actors[gone_port], ActorExitRequest())
            self._actors.pop(gone_port, None)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )

    def _add(self, msg, _sender):
        """Create device actors for instruments connected to
        the serial ports given in the argument list."""
        logger.debug("[_add]")
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self._actors.keys())
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
                        self._create_actor(instrument)
        else:
            assert isinstance(target, list)
            if target == []:
                return
            instruments = self._cluster.update_connected_instruments(
                ports_to_test=target
            )
            for instrument in instruments:
                self._create_actor(instrument)
        return

    def _remove(self, msg, _sender):
        """Kill device actors for instruments that have been unplugged from
        the serial ports given in the argument list."""
        logger.debug("[_remove]")
        target = msg["PAR"].get("PORTS", None)
        if target is None:
            old_ports = set(self._actors.keys())
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

    def _kill_myself(self, return_actor):
        logger.debug("Instrument list empty. Killing myself.")
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(return_actor, return_message)
        self.send(self.myAddress, ActorExitRequest())

    def _kill(self, _msg, sender):
        logger.debug("[_kill] called from %s", sender)
        self._actor_system = sender
        self._kill_flag = True
        if self._actors != {}:
            for _port, actor in self._actors.items():
                self.send(actor, ActorExitRequest())
            logger.debug("ActorExitRequests to all device actors sent.")
        else:
            logger.debug("No instrument connected. Killing myself.")
            self._kill_myself(sender)

    def _return_from_kill(self, _msg, sender):
        """Handle RETURN from KILL messages from the device actors.
        Finally kill myself when the last child confirmed its ActorExitRequest
        and the kill flag was set."""
        gone_port = get_key(sender, self._actors)
        self._actors.pop(gone_port, None)
        logger.debug("Instrument at port %s removed", gone_port)
        if (self._actors == {}) and self._kill_flag:
            logger.debug("All instrument are unsigned now. Killing myself.")
            self._kill_myself(self._actor_system)

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, WakeupMessage):
            self._continue_loop()
            return
        if isinstance(msg, ActorExitRequest):
            return
        if isinstance(msg, ChildActorExited):
            logger.debug("ChildActorExited received")
            self._return_from_kill(msg, msg.childAddress)
            return
        if isinstance(msg, PoisonMessage):
            logger.critical("PoisonMessage --> System shutdown.")
            system_shutdown()
            return
        if not isinstance(msg, dict):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            system_shutdown()
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
            system_shutdown()
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
                system_shutdown()
                return
            if getattr(self, cmd_function, None) is None:
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(
                    RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                )
                system_shutdown()
                return
            getattr(self, cmd_function)(msg, sender)
            return
        if return_key is not None:
            logger.debug("RETURN message without handler")
