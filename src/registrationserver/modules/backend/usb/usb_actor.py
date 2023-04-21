"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

.. uml :: uml-usb_actor.puml
"""

from datetime import datetime, timedelta
from enum import Enum
from threading import Thread
from typing import Union

from hashids import Hashids  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (FinishReserveMsg,
                                               FinishWakeupMsg, Gps, KillMsg,
                                               RecentValueMsg, RescanMsg,
                                               RxBinaryMsg, Status)
from registrationserver.config import usb_backend_config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from sarad.dacm import DacmInst  # type: ignore
from sarad.doseman import DosemanInst  # type: ignore
from sarad.radonscout import RscInst  # type: ignore
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore

# logger.debug("%s -> %s", __package__, __file__)


class Purpose(Enum):
    """One item for every possible purpose the HTTP request is be made for."""

    WAKEUP = 2
    RESERVE = 3


class ThreadType(Enum):
    """One item for every possible thread."""

    CHECK_CONNECTION = 1
    TX_BINARY = 2
    RECENT_VALUE = 3


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.mqtt_scheduler = None
        self.instrument: Union[SaradInst, None] = None
        self.is_connected = True
        self.check_connection_thread = Thread(
            target=self._check_connection,
            daemon=True,
        )
        self.tx_binary_thread = Thread(
            target=self._tx_binary,
            kwargs={"data": None, "sender": None},
            daemon=True,
        )
        self.get_recent_value_thread = Thread(
            target=self._tx_binary,
            kwargs={
                "sender": None,
                "component": None,
                "sensor": None,
                "measurand": None,
            },
            daemon=True,
        )

    def _start_thread(self, thread, thread_type: ThreadType):
        if (
            not self.check_connection_thread.is_alive()
            and not self.tx_binary_thread.is_alive()
            and not self.get_recent_value_thread.is_alive()
        ):
            if thread_type == ThreadType.CHECK_CONNECTION:
                self.check_connection_thread = thread
                self.check_connection_thread.start()
            elif thread_type == ThreadType.TX_BINARY:
                self.tx_binary_thread = thread
                self.tx_binary_thread.start()
            elif thread_type == ThreadType.RECENT_VALUE:
                self.get_recent_value_thread = thread
                self.get_recent_value_thread.start()
        else:
            self.wakeupAfter(timedelta(seconds=0.5), payload=(thread, thread_type))

    def _check_connection(self, purpose: Purpose = Purpose.WAKEUP):
        logger.debug("Check if %s is still connected", self.my_id)
        self.is_connected = self.instrument.get_description()
        if purpose == Purpose.WAKEUP:
            self.send(self.myAddress, FinishWakeupMsg())
        elif purpose == Purpose.RESERVE:
            self.send(self.myAddress, FinishReserveMsg(Status.OK))

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
        if family_id == 1:
            family_class = DosemanInst
        elif family_id == 2:
            family_class = RscInst
        elif family_id == 5:
            family_class = DacmInst
        else:
            logger.error("Family %s not supported", family_id)
            return None
        self.instrument = family_class()
        self.instrument.route = msg.route
        self.instrument.release_instrument()
        logger.info("Instrument with Id %s detected.", self.my_id)
        if msg.poll:
            self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])
        return None

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        logger.debug("Wakeup %s", self.my_id)
        if msg.payload is None:
            self.wakeupAfter(usb_backend_config["LOCAL_RETRY_INTERVAL"])
            try:
                is_reserved = self.device_status["Reservation"]["Active"]
            except KeyError:
                is_reserved = False
            if (not self.on_kill) and (not is_reserved):
                if not self.check_connection_thread.is_alive():
                    self.check_connection_thread = Thread(
                        target=self._check_connection,
                        kwargs={
                            "purpose": Purpose.WAKEUP,
                        },
                        daemon=True,
                    )
        elif isinstance(msg.payload, Thread):
            self._start_thread(msg.payload[0], msg.payload[1])

    def receiveMsg_FinishWakeupMsg(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Finalize the handling of WakeupMessage"""
        if not self.is_connected:
            logger.info("Nothing connected -> Killing myself")
            self.send(self.myAddress, KillMsg())
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

    def dummy_reply(self, data, sender) -> bool:
        """Filter TX message and give a dummy reply.

        This function was invented in order to prevent messages destined for
        the WLAN module to be sent to the instrument.
        """
        tx_rx = {b"B\x80\x7f\xe6\xe6\x00E": b"B\x80\x7f\xe7\xe7\x00E"}
        if data in tx_rx:
            logger.debug("Reply %s with %s", data, tx_rx[data])
            self.send(sender, RxBinaryMsg(tx_rx[data]))
            return True
        return False

    @overrides
    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for binary message from App to Instrument."""
        super().receiveMsg_TxBinaryMsg(msg, sender)
        self._start_thread(
            Thread(
                target=self._tx_binary,
                kwargs={"data": msg.data, "sender": sender},
                daemon=True,
            ),
            ThreadType.TX_BINARY,
        )

    def _tx_binary(self, data, sender):
        if self.dummy_reply(data, sender):
            return
        if not self.instrument.check_cmd(data):
            logger.error("Command %s from app is invalid", data)
            self.send(sender, RxBinaryMsg(b""))
            return
        emergency = False
        try:
            reply = self.instrument.get_message_payload(data, timeout=1)
        except (SerialException, OSError):
            logger.error("Connection to %s lost", self.instrument)
            reply = {"is_valid": False, "is_last_frame": True}
            emergency = True
        logger.debug("Instrument replied %s", reply)
        if reply["is_valid"]:
            self.send(sender, RxBinaryMsg(reply["standard_frame"]))
            while not reply["is_last_frame"]:
                try:
                    reply = self.instrument.get_next_payload(timeout=1)
                    self.send(sender, RxBinaryMsg(reply["standard_frame"]))
                except (SerialException, OSError):
                    logger.error("Connection to %s lost", self.my_id)
                    reply = {"is_valid": False, "is_last_frame": True}
                    emergency = True
        if emergency:
            logger.info("Killing myself")
            self.send(self.myAddress, KillMsg())
        elif not reply["is_valid"]:
            logger.warning("Invalid binary message from instrument.")
            self.send(sender, RxBinaryMsg(reply["raw"]))

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

    def receiveMsg_FinishReserveMsg(self, _msg, _sender):
        # pylint: disable=invalid-name
        """Forward the reservation state from the Instrument Server to the REST API."""
        if not self.is_connected:
            logger.info("Killing myself")
            self.send(self.myAddress, KillMsg())
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

    def receiveMsg_GetRecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Get a value from a DACM instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._start_thread(
            Thread(
                target=self._tx_binary,
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
                timestamp = datetime.utcnow()
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
        self.send(sender, answer)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        self.instrument.release_instrument()
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        try:
            self.instrument.release_instrument()
        except AttributeError:
            logger.warning("The USB Actor to be killed wasn't initialized properly.")
        super().receiveMsg_KillMsg(msg, sender)


if __name__ == "__main__":
    pass
