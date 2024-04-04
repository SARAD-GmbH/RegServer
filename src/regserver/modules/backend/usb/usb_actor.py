"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Thread
from typing import Union

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from regserver.actor_messages import (Gps, RecentValueMsg, RescanMsg,
                                      RxBinaryMsg, Status)
from regserver.config import usb_backend_config
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor
from sarad.dacm import DacmInst  # type: ignore
from sarad.doseman import DosemanInst  # type: ignore
from sarad.radonscout import RscInst  # type: ignore
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore


class Purpose(Enum):
    """One item for every possible purpose the HTTP request is be made for."""

    WAKEUP = 2
    RESERVE = 3


class ThreadType(Enum):
    """One item for every possible thread."""

    CHECK_CONNECTION = 1
    TX_BINARY = 2
    RECENT_VALUE = 3
    START_MEASURING = 4


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.instrument: Union[SaradInst, None] = None
        self.is_connected = True
        self.check_connection_thread = Thread(
            target=self._check_connection,
            daemon=True,
        )
        self.get_recent_value_thread = Thread(
            target=self._get_recent_value,
            kwargs={
                "sender": None,
                "component": None,
                "sensor": None,
                "measurand": None,
            },
            daemon=True,
        )
        self.setup_thread = Thread(
            target=self._setup,
            kwargs={"family_id": None, "poll": False, "route": None},
            daemon=True,
        )
        self.start_measuring_thread = Thread(
            target=self._start_measuring_function, daemon=True
        )
        self.tx_binary_thread_proceed = Thread(
            target=self._tx_binary_proceed,
            kwargs={"data": None},
            daemon=True,
        )

    def _start_thread(self, thread, thread_type: ThreadType):
        if (
            not self.check_connection_thread.is_alive()
            and not self.get_recent_value_thread.is_alive()
        ):
            if thread_type == ThreadType.CHECK_CONNECTION:
                self.check_connection_thread = thread
                self.check_connection_thread.start()
            elif thread_type == ThreadType.RECENT_VALUE:
                self.get_recent_value_thread = thread
                self.get_recent_value_thread.start()
            elif thread_type == ThreadType.START_MEASURING:
                self.start_measuring_thread = thread
                self.start_measuring_thread.start()
        else:
            self.wakeupAfter(timedelta(seconds=0.5), payload=(thread, thread_type))

    def _check_connection(self, purpose: Purpose = Purpose.WAKEUP):
        logger.debug("Check if %s is still connected", self.my_id)
        if self.instrument is not None:
            self.is_connected = self.instrument.get_description()
        if purpose == Purpose.WAKEUP:
            self._finish_poll()
        elif purpose == Purpose.RESERVE:
            self._finish_reserve()

    def receiveMsg_SetupUsbActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the SaradInst object for serial communication."""
        logger.debug(
            "SetupUsbActorMsg(route=%s, family=%d) for %s from %s",
            msg.route,
            msg.family["family_id"],
            self.my_id,
            sender,
        )
        family_id = msg.family["family_id"]
        if msg.poll:
            self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])
        self.setup_thread = Thread(
            target=self._setup,
            kwargs={"family_id": family_id, "route": msg.route},
            daemon=True,
        )
        self.setup_thread.start()

    def _setup(self, family_id=None, route=None):
        if family_id == 1:
            family_class = DosemanInst
        elif family_id == 2:
            family_class = RscInst
        elif family_id == 5:
            family_class = DacmInst
        else:
            logger.critical("Family %s not supported", family_id)
            self.is_connected = False
            return
        self.instrument = family_class()
        self.instrument.route = route
        if usb_backend_config["SET_RTC"]:
            if usb_backend_config["USE_UTC"]:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            logger.info("Set RTC of %s to %s", self.my_id, now)
            self.instrument.set_real_time_clock(now)
        self.instrument.release_instrument()
        logger.info("Instrument with Id %s detected.", self.my_id)
        return

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name, disable=too-many-branches
        """Handler for WakeupMessage"""
        # logger.debug("Wakeup %s, payload = %s", self.my_id, msg.payload)
        if msg.payload is None:
            logger.debug("Check connection of %s", self.my_id)
            self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])
            try:
                is_reserved = self.device_status["Reservation"]["Active"]
            except KeyError:
                is_reserved = False
            if (not self.on_kill) and (not is_reserved):
                if not self.check_connection_thread.is_alive():
                    logger.debug("Start check connection thread for %s", self.my_id)
                    self._start_thread(
                        Thread(
                            target=self._check_connection,
                            kwargs={
                                "purpose": Purpose.WAKEUP,
                            },
                            daemon=True,
                        ),
                        thread_type=ThreadType.CHECK_CONNECTION,
                    )
        elif isinstance(msg.payload, tuple) and isinstance(msg.payload[0], Thread):
            logger.debug("Start %s thread", msg.payload[1])
            self._start_thread(msg.payload[0], msg.payload[1])
        elif msg.payload == "start_measuring":
            self._start_measuring()
        elif msg.payload == "get_values":
            self._get_recent_value(
                sender=None, component=component, sensor=sensor, measurand=measurand
            )

    def _finish_poll(self):
        """Finalize the handling of WakeupMessage for regular rescan"""
        if not self.is_connected and not self.on_kill:
            logger.info("Nothing connected -> Killing myself")
            self._kill_myself()
        else:
            hid = Hashids()
            instr_id = hid.encode(
                self.instrument.family["family_id"],
                self.instrument.type_id,
                self.instrument.serial_number,
            )
            old_instr_id = short_id(self.my_id)
            if instr_id != old_instr_id:
                logger.info(
                    "Instr_id was %s and now is %s -> Rescan",
                    old_instr_id,
                    instr_id,
                )
                self.send(self.parent, RescanMsg())

    def dummy_reply(self, data) -> Union[bytes, bool]:
        """Filter TX message and give a dummy reply.

        This function was invented in order to prevent messages destined for
        the WLAN module to be sent to the instrument.
        """
        tx_rx = {b"B\x80\x7f\xe6\xe6\x00E": b"B\x80\x7f\xe7\xe7\x00E"}
        if data in tx_rx:
            logger.debug("Reply %s with %s", data, tx_rx[data])
            return tx_rx[data]
        return False

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for binary message from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        self.tx_binary_thread_proceed = Thread(
            target=self._tx_binary_proceed,
            kwargs={"data": msg.data},
            daemon=True,
        )
        if not self.tx_binary_thread_proceed.is_alive():
            self.tx_binary_thread_proceed.start()

    def _tx_binary_proceed(self, data):
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        if is_reserved:
            dummy_reply = self.dummy_reply(data)
            if dummy_reply:
                self.send(self.redirector_actor, RxBinaryMsg(dummy_reply))
                return
            if not self.instrument.check_cmd(data):
                logger.error("Command %s from app is invalid", data)
                self.send(self.redirector_actor, RxBinaryMsg(b""))
                return
            emergency = False
            read_next = True
            while read_next:
                try:
                    reply = self.instrument.get_message_payload(data, timeout=3)
                except (SerialException, OSError):
                    logger.error("Connection to %s lost", self.instrument)
                    reply = {"is_valid": False, "is_last_frame": True}
                    emergency = True
                logger.debug("Instrument replied %s", reply)
                if reply["is_valid"]:
                    self.send(
                        self.redirector_actor, RxBinaryMsg(reply["standard_frame"])
                    )
                    read_next = not reply["is_last_frame"]
                    data = b""
                    continue
                if emergency:
                    logger.info("Killing myself")
                    self._kill_myself()
                    return
                logger.warning("Invalid binary message from instrument. %s", reply)
                self.send(self.redirector_actor, RxBinaryMsg(reply["raw"]))
                return

    @overrides
    def _request_reserve_at_is(self):
        """Reserve the requested instrument.

        To avoid wrong reservations of instruments like DOSEman sitting on an
        IR cradle that might stay connected to USB or instruments connected via
        RS-232, we have to double-check the availability of the instrument.

        """
        self._start_thread(
            Thread(
                target=self._check_connection,
                kwargs={
                    "purpose": Purpose.RESERVE,
                },
                daemon=True,
            ),
            ThreadType.CHECK_CONNECTION,
        )

    def _finish_reserve(self):
        """Forward the reservation state from the Instrument Server to the REST API."""
        logger.debug("_finish_reserve")
        if not self.is_connected and not self.on_kill:
            logger.info("Killing myself")
            self._kill_myself()
            self._handle_reserve_reply_from_is(Status.NOT_FOUND)
        else:
            self._handle_reserve_reply_from_is(Status.OK)

    @overrides
    def _request_free_at_is(self):
        """Free the instrument

        The USB Actor is already the last in the chain. There is no need to ask
        somebody else to free the instrument.
        """
        self._handle_free_reply_from_is(Status.OK)

    def receiveMsg_StartMeasuringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Start measuring at a given time."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.start_time is None:
            self._start_measuring()
        else:
            offset = msg.start_time - datetime.now(timezone.utc)
            self.wakeupAfter(offset, payload="start_measuring")

    def _start_measuring(self):
        self._start_thread(
            Thread(
                target=self._start_measuring_function,
                daemon=True,
            ),
            ThreadType.START_MEASURING,
        )

    def _start_measuring_function(self):
        cycle_index = 0
        is_reserved = self.device_status.get("Reservation", False)
        if is_reserved:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        if is_reserved:
            self.wakeupAfter(timedelta(seconds=1), payload="start_measuring")
        else:
            if usb_backend_config["USE_UTC"]:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            logger.info("Set RTC of %s to %s", self.my_id, now)
            self.instrument.set_real_time_clock(now)
            try:
                success = self.instrument.start_cycle(cycle_index)
                logger.info(
                    "Device %s started with cycle_index %d",
                    self.instrument.device_id,
                    cycle_index,
                )
            except Exception as exception:  # pylint: disable=broad-except
                logger.error(
                    "Failed to start cycle on %s. Exception: %s", self.my_id, exception
                )
            if not success:
                logger.error("Start/Stop not supported by %s", self.my_id)
            for component in self.instrument:
                for sensor in component:
                    for measurand in sensor:
                        self._get_recent_value(
                            sender=None,
                            component=list(self.instrument).index(component),
                            sensor=list(component).index(sensor),
                            measurand=list(sensor).index(measurand),
                        )

    @overrides
    def receiveMsg_BaudRateMsg(self, msg, sender):
        super().receiveMsg_BaudRateMsg(msg, sender)
        self.instrument._family["baudrate"] = list(  # pylint: disable=protected-access
            msg.baud_rate
        )

    def receiveMsg_GetRecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Get a value from a DACM instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._start_thread(
            Thread(
                target=self._get_recent_value,
                kwargs={
                    "sender": sender,
                    "component": msg.component,
                    "sensor": msg.sensor,
                    "measurand": msg.measurand,
                },
                daemon=True,
            ),
            ThreadType.RECENT_VALUE,
        )

    def _get_recent_value(self, sender, component, sensor, measurand):
        if sender is None:
            sender = self.registrar
        try:
            reply = self.instrument.get_recent_value(component, sensor, measurand)
        except IndexError:
            answer = RecentValueMsg(status=Status.INDEX_ERROR)
            self.send(sender, answer)
            return
        logger.debug(
            "get_recent_value(%d, %d, %d) came back with %s",
            component,
            sensor,
            measurand,
            reply,
        )
        if reply:
            if reply.get("gps") is None:
                gps = Gps(valid=False)
            else:
                gps = Gps(
                    valid=reply["gps"]["valid"],
                    latitude=reply["gps"]["latitude"],
                    longitude=reply["gps"]["longitude"],
                    altitude=reply["gps"]["altitude"],
                    deviation=reply["gps"]["deviation"],
                )
            if measurand:
                timestamp = reply["datetime"]
            else:
                timestamp = datetime.now(timezone.utc)
            answer = RecentValueMsg(
                component_name=reply["component_name"],
                sensor_name=reply["sensor_name"],
                measurand_name=reply["measurand_name"],
                measurand=reply["measurand"],
                operator=reply["measurand_operator"],
                value=reply["value"],
                unit=reply["measurand_unit"],
                timestamp=timestamp,
                gps=gps,
                status=Status.OK,
            )
        else:
            answer = RecentValueMsg(status=Status.INDEX_ERROR)
        logger.info(answer)
        self.send(sender, answer)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        self.instrument.release_instrument()
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        try:
            self.instrument.release_instrument()
        except AttributeError:
            logger.warning("The USB Actor to be killed wasn't initialized properly.")
        super()._kill_myself(register=register)


if __name__ == "__main__":
    pass
