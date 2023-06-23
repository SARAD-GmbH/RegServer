"""Actor of the Registration Server representing a usable serial device

:Created:
    2023-01-27

:Authors:
    | Michael Strey <strey@sarad.de>

"""

from datetime import timedelta
from threading import Thread
from typing import Union

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, SetDeviceStatusMsg,
                                               SetupUsbActorMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import config, usb_backend_config
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
        self.loop_thread = Thread(target=self._loop_function, daemon=True)
        self.next_method = None
        self.instrument = None

    def receiveMsg_SetupComActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle message to initialize ComActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.route = msg.route
        self.loop_interval = msg.loop_interval
        if self.child_actors:
            logger.debug("%s: Update device actor", self.my_id)
            self._forward_to_children(KillMsg())
            self.stop_loop = self.loop_running
            # refer to receiveMsg_ChildActorExited()
        else:
            logger.debug("%s: Update -- no child", self.my_id)
            self._do_loop()
            self._start_polling()

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if not self.on_kill:
            self._do_loop()
            self._start_polling()

    def _do_loop(self) -> None:
        if not self.loop_thread.is_alive():
            self.loop_thread = Thread(target=self._loop_function, daemon=True)
            try:
                self.loop_thread.start()
                self.wakeupAfter(timedelta(seconds=0.5), payload="loop")
            except RuntimeError:
                pass

    def _loop_function(self) -> None:
        logger.debug("[_do_loop] %s", self.route)
        self.instrument = None
        if not self.child_actors:
            self.instrument = self._get_instrument(self.route)
        if self.instrument is not None:
            self.next_method = self._create_and_setup_actor
        else:
            self.next_method = self._do_nothing

    def _start_polling(self):
        if self.loop_interval and (not self.loop_running):
            logger.info(
                "%s: Start polling %s every %d s.",
                self.my_id,
                self.route,
                self.loop_interval,
            )
            self.loop_running = True
            self.wakeupAfter(self.loop_interval)
        else:
            self.stop_loop = False

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        logger.debug("Wakeup %s, payload = %s", self.my_id, msg.payload)
        if msg.payload == "loop":
            if self.next_method is None:
                self.wakeupAfter(timedelta(seconds=0.5), payload=msg.payload)
            else:
                self.next_method()
                self.next_method = None
        elif msg.payload is None:
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
            except (SerialException, OSError) as exception:
                logger.error("%s: %s not accessible: %s", self.my_id, route, exception)
                self.next_method = self._kill_myself
                break
        if instr_id is not None:
            return test_instrument
        return None

    def _do_nothing(self):
        logger.debug("No new instrument found on %s", self.my_id)

    def _create_and_setup_actor(self):
        logger.debug("[_create_and_setup_actor] on %s", self.my_id)
        try:
            family = self.instrument.family["family_id"]
        except AttributeError:
            logger.error(
                "_create_and_setup_called but self.instrument is %s", self.instrument
            )
            return
        instr_id = self.instrument.device_id
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "Add Instrument on %s: unknown instrument family (index: %s)",
                self.my_id,
                family,
            )
            sarad_type = "unknown"
        if (family == 1) and (self.instrument.type_id in (1, 2)):
            # DOSEman and DOSEman Pro are using an IR cradle with USB/ser adapter
            self.poll_doseman = True
            if (not self.loop_running) and not self.loop_interval:
                self.loop_interval = usb_backend_config["LOCAL_RETRY_INTERVAL"]
                self._start_polling()
        else:
            self.poll_doseman = False
        actor_id = f"{instr_id}.{sarad_type}.local"
        logger.debug("Create actor %s on %s", actor_id, self.my_id)
        device_actor = self._create_actor(UsbActor, actor_id, None)
        device_status = {
            "Identification": {
                "Name": self.instrument.type_name,
                "Family": family,
                "Type": self.instrument.type_id,
                "Serial number": self.instrument.serial_number,
                "Firmware version": self.instrument.software_version,
                "Host": "127.0.0.1",
                "Protocol": sarad_type,
                "Origin": config["IS_ID"],
            },
            "Serial": self.instrument.route.port,
            "State": 2,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))
        self.send(
            device_actor,
            SetupUsbActorMsg(
                self.instrument.route,
                self.instrument.family,
                bool(self.loop_interval) or self.poll_doseman,
            ),
        )

    def _remove_child_actor(self):
        logger.debug("%s sending KillMsg to device actor.")
        try:
            actor_id = list(self.child_actors.keys())[0]
            self.send(self.child_actors[actor_id]["actor_address"], KillMsg())
            self.child_actors.pop(actor_id, None)
        except IndexError:
            logger.error(
                "%s: Tried to remove instrument from %s, that never was added properly.",
                self.my_id,
                self.route,
            )
