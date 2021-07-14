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

    _cluster: SaradCluster = SaradCluster()
    _loop: List[str] = []
    _loop_started: bool = False

    ACCEPTED_COMMANDS = {
        "SEND": "_send",
        "LIST": "_list",
        "LIST-USB": "_list_usb",
        "LIST-NATIVE": "_list_natives",
        "LOOP": "_loop",
        "LOOP_REMOVE": "_loop_remove",
        "DO_LOOP": "_do_loop",
    }

    def __init__(self):
        super().__init__()
        logger.info("ClusterActor initialized")

    def _loop(self, msg: dict, sender) -> None:
        target = msg["PAR"]["PORT"]
        logger.info("Adding to loop: %s", target)
        ok: list
        if isinstance(target, list):
            for port in target:
                if self._add_to_loop(port):
                    ok.append(port)
        if isinstance(target, str):
            if self._add_to_loop(target):
                ok.append(target)

        if not self._loop_started:
            self.send(self, {"CMD": "DO_LOOP"})

        return {
            "RETURN": "LOOP",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": ok},
        }

    def _loop_remove(self, msg: dict, sender) -> None:
        target = msg["PAR"]["PORT"]
        logger.info("Removing from loop: %s", target)
        ok: list
        if isinstance(target, list):
            for port in target:
                if self._remove_from_loop(port):
                    ok.append(port)
        if isinstance(target, str):
            if self._remove_from_loop(target):
                ok.append(target)

        if not self._loop:
            self._loop_started = False

        return {
            "RETURN": "LOOP",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": ok},
        }

    def _do_loop(self, msg: dict, sender) -> None:
        logger.info("Started Polling: %s", self._loop)
        if not self._loop_started:
            self._loop_started = True
            self.wakeupAfter(config["LOCAL_RETRY_INTERVALL"])
        else:
            logger.info("Stopped Polling")

    def _continue_loop(self):
        self._cluster.update_connected_instruments(self._loop)
        if self._loop_started:
            logger.debug("Polling Ports: %s", self._loop)
            self.wakeupAfter(config["LOCAL_RETRY_INTERVALL"])

    def _remove_from_loop(self, port: str) -> bool:
        if port in self._loop:
            if self._loop.count(port) >= 0:
                self._loop.remove(port)
            return True
        return False

    def _add_to_loop(self, port: str) -> bool:
        if port in [i.device for i in comports()]:
            if self._loop.count(port) == 0:
                self._loop.append(port)
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
                .get_transparent_reply(data, reply_length=134, timeout=0.1)
            )

        logger.debug("and got reply from instrument: %s", reply)
        return_message = {
            "RETURN": "SEND",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": reply},
        }
        self.send(sender, return_message)

    def _list_usb(self, msg: dict, sender) -> None:
        result: list[SaradInst]

        ports = [port for port in comports() if port.vid and port.pid]

        result = self._cluster.update_connected_instruments(ports)

        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-USB",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        self.send(sender, return_message)

    def _list_natives(self, msg: dict, sender) -> None:
        result: list[SaradInst]

        ports = [port for port in comports() if not port.pid]

        result = self._cluster.update_connected_instruments(ports)

        logger.debug("and got list: %s", result)
        return_message = {
            "RETURN": "LIST-USB",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": {"DATA": result},
        }
        self.send(sender, return_message)

    def _list(self, msg: dict, sender) -> None:
        result: list[SaradInst]
        target = msg["PAR"].get("PORTS", None)

        if not target:
            result = self._cluster.update_connected_instruments()

        if isinstance(target, str):
            result = self._cluster.update_connected_instruments([target])

        if isinstance(target, list):
            result = self._cluster.update_connected_instruments(target)

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
