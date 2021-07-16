"""
clusteractor
"""

from typing import List

from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from sarad.cluster import SaradCluster
from sarad.sari import SaradInst
from serial.tools.list_ports import comports
from thespian.actors import Actor, ActorExitRequest, WakeupMessage


class ClusterActor(Actor):
    """
    classdocs
    """

    ACCEPTED_COMMANDS = {
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

    def _loop(self, msg: dict, sender) -> None:  # pylint: disable=unused-argument
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

    def _loop_remove(
        self, msg: dict, sender  # pylint: disable=unused-argument
    ) -> None:
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

    def _do_loop(self, msg: dict, sender) -> None:  # pylint: disable=unused-argument
        logger.info("Started Polling: %s", self._looplist)
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
            active_ports = self._verified_ports()
            logger.debug("Looping over %s of %s", active_ports, self._looplist)
            self._cluster.update_connected_instruments(active_ports)
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

    def _list_ports(self, msg: dict, sender) -> None:  # pylint: disable=unused-argument
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

    def _list_usb(self, msg: dict, sender) -> None:  # pylint: disable=unused-argument
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

    def _list_natives(
        self, msg: dict, sender  # pylint: disable=unused-argument
    ) -> None:
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
