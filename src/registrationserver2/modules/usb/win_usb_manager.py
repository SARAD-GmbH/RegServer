"""Actor creating one new device actor for every new instrument

Created
    2021-06-09

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

"""
import json

from overrides import overrides  # type: ignore
from registrationserver2.logger import logger
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.modules.usb.usb_actor import UsbActor
from registrationserver2.modules.usb.usb_serial import USBSerial
from sarad.cluster import SaradCluster
from serial.serialutil import SerialException  # type: ignore
from thespian.actors import (Actor, ActorExitRequest,  # type: ignore
                             ChildActorExited)


class WinUsbManager(Actor):
    """Actor creating one new device actor for every new instrument"""

    ACCEPTED_COMMANDS = {"PROCESS_LIST": "_process_list"}

    ACCEPTED_RETURNS = {
        "SETUP": "_return_with_socket",
        "KILL": "_return_from_kill",
    }

    @overrides
    def __init__(self):
        super().__init__()
        self._port_list = {}
        self._actors = {}
        self._cluster = SaradCluster()

    @overrides
    def receiveMessage(self, msg, sender):
        # pylint: disable=too-many-return-statements
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, ActorExitRequest):
            self._kill(msg, sender)
            return
        if isinstance(msg, ChildActorExited):
            # error handling code could be placed here
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
        elif return_key is not None:
            return_function = self.ACCEPTED_RETURNS.get(return_key, None)
            if return_function is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            if getattr(self, return_function, None) is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            getattr(self, return_function)(msg, sender)

    # Message Handling
    def _process_list(self, msg: dict, _sender):
        logger.info("[LIST] Processing List %s", msg)
        data_key = msg.get("DATA", None)
        if data_key is None:
            return
        list_key = data_key.get("LIST", None)
        if list_key is None:
            return
        if not isinstance(list_key, list):
            return
        for current in list_key:
            if current in self._port_list:
                continue
            logger.info("[Add] Port %s", current)
            self._create_actor(current)
            self._port_list[current.deviceid] = current

        remove = []
        for old in self._port_list:
            if old in list_key:
                continue
            logger.info("[Delete] Port %s", old)
            remove.append(old)
            if old in self._actors:
                self.send(self._actors[old], ActorExitRequest())

        for remove_item in remove:
            self._port_list.pop(remove_item)

    def _kill(self, _msg: dict, _sender):
        for actor in self._actors:
            self.send(actor, ActorExitRequest())
        self._port_list = {}

    def _create_actor(self, device: USBSerial):
        try:
            instruments = self._cluster.update_connected_instruments([device.deviceid])
            instrument = instruments[0]
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
            self._actors[device.deviceid] = self.createActor(
                UsbActor, globalName=global_name
            )
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
                    "Serial": device.deviceid,
                }
            )
            msg = {"CMD": "SETUP", "PAR": data}
            logger.info("Ask to setup device actor %s with msg %s", global_name, msg)
            self.send(self._actors[device.deviceid], msg)

        except IndexError:
            logger.info("No SARAD instrument at %s", device.deviceid)

        except SerialException:
            logger.debug("Error Opening %s", device.deviceid)
