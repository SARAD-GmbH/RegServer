"""Actor of the Registration Server representing a usable serial device

:Created:
    2023-01-27

:Authors:
    | Michael Strey <strey@sarad.de>

"""

from threading import Thread
from time import sleep
from typing import Union

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from regserver.actor_messages import KillMsg, SetupUsbActorMsg
from regserver.base_actor import BaseActor
from regserver.config import usb_backend_config
from regserver.logger import logger
from regserver.modules.backend.usb.net_usb_actor import NetUsbActor
from regserver.modules.backend.usb.usb_actor import UsbActor
from sarad.doseman import DosemanInst  # type: ignore
from sarad.sari import SI, SaradInst, sarad_family  # type: ignore
from serial import SerialException  # type: ignore
from serial.tools import list_ports  # type: ignore


class ComActor(BaseActor):
    """Actor representing a usable serial connections via USB, RS-232, RS-485 or ZigBee"""

    @overrides
    def __init__(self):
        super().__init__()
        self.polling_loop_running = False
        self.stop_polling = False
        self.route = None
        self.polling_interval = 0
        self.detect_instr_thread = Thread(target=self._detect_instr, daemon=True)
        self.guessed_family = None  # id of instrument family

    def _guess_family(self):
        family_mapping = [
            (r"(?i)irda", 1),
            (r"(?i)monitor", 5),
            (r"(?i)scout|(?i)smart", 2),
            (r"(?i)ft232", 4),
        ]
        for mapping in family_mapping:
            for port in list_ports.grep(mapping[0]):
                if self.route.port == port.device:
                    self.guessed_family = mapping[1]
                    logger.info(
                        "%s, %s, #%d",
                        port.device,
                        port.description,
                        self.guessed_family,
                    )
        if self.guessed_family is None:
            self.guessed_family = 1  # DOSEman family is the default
            for port in list_ports.comports():
                if self.route.port == port.device:
                    logger.info(
                        "%s, %s, #%d",
                        port.device,
                        port.description,
                        self.guessed_family,
                    )

    def receiveMsg_SetupComActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle message to initialize ComActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.route = msg.route
        self.polling_interval = msg.loop_interval
        if self.child_actors:
            logger.debug("%s: Update device actor", self.my_id)
            self._forward_to_children(KillMsg())
            self.stop_polling = self.polling_loop_running
            # refer to receiveMsg_ChildActorExited()
        else:
            logger.debug("%s: Update -- no child", self.my_id)
            self._guess_family()
            self._do_loop()
            self._start_polling()

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if not self.on_kill:
            self._do_loop()
            self._start_polling()

    def _do_loop(self) -> None:
        if not self.detect_instr_thread.is_alive():
            self.detect_instr_thread = Thread(target=self._detect_instr, daemon=True)
            try:
                self.detect_instr_thread.start()
            except RuntimeError:
                pass

    def _detect_instr(self) -> None:
        logger.debug("[_detect_instr] %s", self.route)
        if self.guessed_family == 5:
            sleep(2.5)  # Wait for the relay
        elif self.guessed_family == 4:
            sleep(8)  # Wait for ZigBee coordinator to start
        if not self.child_actors:
            instrument = self._get_instrument(self.route)
            if instrument is not None:
                self._create_and_setup_actor(instrument)

    def _start_polling(self):
        if self.polling_interval and (not self.polling_loop_running):
            logger.info(
                "%s: Start polling %s every %d s.",
                self.my_id,
                self.route,
                self.polling_interval,
            )
            self.polling_loop_running = True
            self.wakeupAfter(self.polling_interval)
        else:
            self.stop_polling = False

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        logger.debug("Wakeup %s, payload = %s", self.my_id, msg.payload)
        if (not self.on_kill) and self.polling_interval and not self.stop_polling:
            self._do_loop()
            self.wakeupAfter(self.polling_interval)
            self.polling_loop_running = True
        else:
            self.polling_loop_running = False

    def _get_instrument(self, route) -> Union[SI, None]:
        hid = Hashids()
        if self.guessed_family in (2, 4, 5):
            instruments_to_test = (SaradInst(family=sarad_family(0)), DosemanInst())
        else:
            instruments_to_test = (DosemanInst(), SaradInst(family=sarad_family(0)))
        instr_id = None
        for test_instrument in instruments_to_test:
            try:
                test_instrument.route = route
                if not test_instrument.valid_family:
                    logger.debug(
                        "Family %s not valid on port %s",
                        test_instrument.family["family_name"],
                        self.route.port,
                    )
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
                self._kill_myself()
                break
        if instr_id is not None:
            return test_instrument
        return None

    def _do_nothing(self):
        logger.debug("No new instrument found on %s", self.my_id)

    def _create_and_setup_actor(self, instrument):
        logger.debug("[_create_and_setup_actor] on %s", self.my_id)
        try:
            family = instrument.family["family_id"]
        except AttributeError:
            logger.error("_create_and_setup_called but instrument is %s", instrument)
            return
        instr_id = instrument.device_id
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2, 4]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "Add Instrument on %s: unknown instrument family (index: %s)",
                self.my_id,
                family,
            )
            sarad_type = "unknown"
        if (family == 1) and (instrument.type_id in (1, 2, 3)):
            # DOSEman, DOSEman Pro, and MyRIAM are using an IR cradle with USB/ser adapter
            poll_doseman = True
            if (not self.polling_loop_running) and not self.polling_interval:
                self.polling_interval = usb_backend_config["LOCAL_RETRY_INTERVAL"]
                self._start_polling()
        else:
            poll_doseman = False
        actor_id = f"{instr_id}.{sarad_type}.local"
        logger.debug("Create actor %s on %s", actor_id, self.my_id)
        if family == 4:
            device_actor = self._create_actor(NetUsbActor, actor_id, None)
        else:
            device_actor = self._create_actor(UsbActor, actor_id, None)
        self.send(
            device_actor,
            SetupUsbActorMsg(
                instrument.route,
                instrument.family,
                bool(self.polling_interval) or poll_doseman,
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
