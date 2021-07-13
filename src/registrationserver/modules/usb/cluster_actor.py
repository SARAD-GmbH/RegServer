"""
clusteractor
"""

from sarad.cluster import SaradCluster
from sarad.sari import SaradInst
import serial.tools.list_ports as list_ports

from thespian.actors import Actor, ActorExitRequest
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES


class ClusterActor(Actor):
    """
    classdocs
    """

    _cluster: SaradCluster = SaradCluster()

    ACCEPTED_COMMANDS = {
        "SEND": "_send",
        "LIST": "_list",
        "LIST-USB": "_list_usb",
        "LIST-NATVE": "_list_natives",
    }

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

        ports = [port for port in list_ports.comports() if port.vid and port.pid]

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

        ports = [port for port in list_ports.comports() if not port.pid]

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
