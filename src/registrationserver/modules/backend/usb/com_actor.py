"""Actor of the Registration Server representing a usable serial device

:Created:
    2023-01-27

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import os
from typing import Union

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, SetDeviceStatusMsg,
                                               SetupUsbActorMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.backend.usb.usb_actor import UsbActor
from sarad.dacm import DacmInst  # type: ignore
from sarad.doseman import DosemanInst  # type: ignore
from sarad.radonscout import RscInst  # type: ignore
from sarad.sari import SI  # type: ignore
from serial import SerialException  # type: ignore


class ComActor(BaseActor):
    """Actor representing a usable serial connections via USB, RS-232, RS-485 or ZigBee"""

    @overrides
    def __init__(self):
        super().__init__()
        self.loop_running: bool = False
        self.stop_loop: bool = False
        self.route = None
        self.loop_interval = 0
        self.poll_doseman = False

    def receiveMsg_SetupComActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle message to initialize ComActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.route = msg.route
        self.loop_interval = msg.loop_interval
        if self.child_actors:
            logger.info("Update -- child")
            self._forward_to_children(KillMsg())
            self.stop_loop = self.loop_running
            # refer to receiveMsg_ChildActorExited()
        else:
            logger.info("Update -- no child")
            self._do_loop()
            self._start_polling()

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if not self.on_kill:
            self._do_loop()
            self._start_polling()

    def _do_loop(self) -> None:
        logger.info("[_do_loop] %s", self.route)
        instrument = None
        if not self.child_actors:
            instrument = self._get_instrument(self.route)
        if instrument is not None:
            self._create_and_setup_actor(instrument)

    def _start_polling(self):
        if self.loop_interval and (not self.loop_running):
            logger.info("Start polling %s.", self.route)
            self.loop_running = True
            self.wakeupAfter(self.loop_interval)
        else:
            self.stop_loop = False

    def receiveMsg_WakeupMessage(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if (not self.on_kill) and self.loop_interval and not self.stop_loop:
            self._do_loop()
            self.wakeupAfter(self.loop_interval)
            self.loop_running = True
        else:
            self.loop_running = False

    def _get_instrument(self, route) -> Union[SI, None]:
        hid = Hashids()
        instruments_to_test = (DacmInst(), RscInst(), DosemanInst())
        instr_id = None
        for test_instrument in instruments_to_test:
            try:
                test_instrument.route = route
                if not test_instrument.valid_family:
                    logger.debug("Family not valid")
                    test_instrument.release_instrument()
                    continue
                logger.debug(
                    "type_id = %d, serial_number = %d",
                    test_instrument.type_id,
                    test_instrument.serial_number,
                )
                if test_instrument.type_id and test_instrument.serial_number:
                    instr_id = hid.encode(
                        test_instrument.family["family_id"],
                        test_instrument.type_id,
                        test_instrument.serial_number,
                    )
                    test_instrument.device_id = instr_id
                    logger.debug(
                        "%s found on route %s.",
                        test_instrument.family["family_name"],
                        route,
                    )
                    test_instrument.release_instrument()
                    break
                test_instrument.release_instrument()
            except SerialException:
                logger.error("%s not accessible.", route)
            except OSError:
                logger.critical("OSError -- exiting for a restart")
                os._exit(1)  # pylint: disable=protected-access
        if instr_id is not None:
            return test_instrument
        return None

    def _create_and_setup_actor(self, instrument):
        logger.debug("[_create_and_setup_actor]")
        family = instrument.family["family_id"]
        instr_id = instrument.device_id
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
        if (family == 1) and (instrument.type_id in (1, 2)):
            # DOSEman and DOSEman Pro are using an IR cradle with USB/ser adapter
            self.poll_doseman = True
        else:
            self.poll_doseman = False
        actor_id = f"{instr_id}.{sarad_type}.local"
        logger.debug("Create actor %s", actor_id)
        device_actor = self._create_actor(UsbActor, actor_id, None)
        device_status = {
            "Identification": {
                "Name": instrument.type_name,
                "Family": family,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
                "Firmware version": instrument.software_version,
                "Host": "127.0.0.1",
                "Protocol": sarad_type,
                "Origin": config["IS_ID"],
            },
            "Serial": instrument.route.port,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))
        self.send(
            device_actor,
            SetupUsbActorMsg(
                instrument.route,
                instrument.family,
                bool(self.loop_interval) or self.poll_doseman,
            ),
        )

    def _remove_child_actor(self):
        logger.debug("Send KillMsg to device actor.")
        try:
            actor_id = list(self.child_actors.keys())[0]
            self.send(self.child_actors[actor_id]["actor_address"], KillMsg())
            self.child_actors.pop(actor_id, None)
        except IndexError:
            logger.error(
                "Tried to remove instrument from %s, that never was added properly.",
                self.route,
            )
