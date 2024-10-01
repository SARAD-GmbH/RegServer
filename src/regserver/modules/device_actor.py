"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, Frontend, KillMsg,
                                      RecentValueMsg, ReservationStatusMsg,
                                      ReserveDeviceMsg, RxBinaryMsg,
                                      SetRtcAckMsg, StartMonitoringAckMsg,
                                      Status, StopMonitoringAckMsg,
                                      UpdateDeviceStatusMsg)
from regserver.base_actor import BaseActor
from regserver.config import frontend_config
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.redirect_actor import RedirectorActor
from thespian.actors import Actor, ActorSystem  # type: ignore

RESERVE_TIMEOUT = timedelta(seconds=10)  # Timeout for RESERVE or FREE operations
VALUE_TIMEOUT = timedelta(seconds=10)  # Timeout for VALUE operations
BIN_TIMEOUT = timedelta(seconds=20)  # Timeout for cmd/msg operations
SET_RTC_TIMEOUT = timedelta(seconds=10)  # Timeout for setting the instruments RTC
START_MONITORING_TIMEOUT = timedelta(seconds=10)  # Timeout for start of monitoring mode
STOP_MONITORING_TIMEOUT = timedelta(seconds=10)  # Timeout for stop of monitoring mode


@dataclass
class Lock:
    """Provides a lock to prevent concurrent calls."""

    value: bool
    time: datetime = datetime.min


@dataclass
class TimeoutMsg:
    """Payload of a WakupMsg to check for timeout."""

    type: str = "bin_timeout"
    counter: int = 0


class DeviceBaseActor(BaseActor):
    # pylint: disable=too-many-instance-attributes
    """Base class for protocol specific device actors.

    Implements all methods that all device actors have in common.
    Handles the following actor messages:

    * SetupMsg: is used to initialize the actor right after its creation.
      This is needed because some parts of the initialization cannot be done in
      __init__(). Other initialization steps require data from the
      MdnsListener/MqttClientActor creating the device actor. The same method is
      used for updates of the device state comming from the
      MdnsListener/MqttClientActor.

    * ReserveDeviceMsg: is being called when the end-user-application wants to
        reserve the directly or indirectly connected device for exclusive
        communication, should return if a reservation is currently possible

    * TxBinaryMsg: is being called when the end-user-application wants to send
        data, should return the direct or indirect response from the device,
        None in case the device is not reachable (so the end application can
        set the timeout itself)

    * FreeDeviceMsg: is being called when the end-user-application is done
        requesting or sending data, should return True as soon as the freeing
        process has been initialized.
    """

    RET_TIMEOUT = b"B\x80\x7f\x0c\x0c\x00E"

    @overrides
    def __init__(self):
        super().__init__()
        self.device_status: dict = {}
        self.subscribers: dict = {}
        self.reserve_device_msg: ReserveDeviceMsg = ReserveDeviceMsg(
            host="", user="", app="", create_redirector=False
        )
        self.sender_api: Actor | ActorSystem | None = None
        self.actor_type = ActorType.DEVICE
        self.redirector_actor = None
        self.return_message = None
        self.instr_id: str = ""
        self.reserve_lock: Lock = Lock(value=False)
        self.free_lock: Lock = Lock(value=False)
        self.value_lock: Lock = Lock(value=False)
        self.ack_lock: Lock = Lock(value=False)
        self.bin_locks: list[Lock] = []

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.instr_id = short_id(self.my_id)

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        sections = ["Identification", "Reservation", "Remote"]
        for section in sections:
            if msg.device_status.get(section, False):
                if self.device_status.get(section, False):
                    for key in self.device_status[section]:
                        if key in msg.device_status[section]:
                            self.device_status[section][key] = msg.device_status[
                                section
                            ][key]
                else:
                    self.device_status[section] = msg.device_status[section]
        if msg.device_status.get("State", False):
            self.device_status["State"] = msg.device_status["State"]
        logger.debug(
            "%s created or updated at %s. is_id = %s",
            self.my_id,
            self.device_status["Identification"].get("Host"),
            self.device_status["Identification"].get("IS Id"),
        )
        if msg.device_status.get("Reservation", False):
            if msg.device_status["Reservation"].get("Active", False):
                if not msg.device_status["Reservation"].get("Host", False):
                    logger.debug("Uncomplete reservation information -> Don't publish.")
                    logger.debug("This is most probably comming in from ZeroConf.")
                    return
        self._publish_status_change()

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to retry a waiting reservation task."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(msg.payload, tuple):
            msg.payload[0](msg.payload[1], msg.payload[2])
        elif (
            (msg.payload == "timeout_on_reserve")
            and self.reserve_lock.value
            and (datetime.now() - self.reserve_lock.time > RESERVE_TIMEOUT)
        ):
            self.reserve_lock.value = False
            self._handle_reserve_reply_from_is(success=Status.NOT_FOUND)
        elif (
            (msg.payload == "timeout_on_free")
            and self.free_lock.value
            and (datetime.now() - self.free_lock.time > RESERVE_TIMEOUT)
        ):
            self.free_lock.value = False
            self._handle_free_reply_from_is(success=Status.NOT_FOUND)
        elif (
            (msg.payload == "timeout_on_value")
            and self.value_lock.value
            and (datetime.now() - self.value_lock.time > VALUE_TIMEOUT)
        ):
            self.value_lock.value = False
            self._handle_recent_value_reply_from_is(
                answer=RecentValueMsg(
                    status=Status.NOT_FOUND,
                    instr_id=self.instr_id,
                )
            )
        elif (
            (msg.payload == "timeout_on_set_rtc")
            and self.ack_lock.value
            and (datetime.now() - self.ack_lock.time > SET_RTC_TIMEOUT)
        ):
            self._handle_set_rtc_reply_from_is(status=Status.NOT_FOUND, confirm=True)
        elif (
            (msg.payload == "timeout_on_start_monitoring")
            and self.ack_lock.value
            and (datetime.now() - self.ack_lock.time > START_MONITORING_TIMEOUT)
        ):
            self._handle_start_monitoring_reply_from_is(
                status=Status.NOT_FOUND, confirm=True
            )
        elif isinstance(msg.payload, TimeoutMsg) and msg.payload.type == "bin_timeout":
            logger.debug(
                "msg.payload.counter=%d, self.bin_locks=%s",
                msg.payload.counter,
                self.bin_locks,
            )
            try:
                bin_lock = self.bin_locks[msg.payload.counter]
            except IndexError:
                logger.error(
                    "No bin_lock with index %d in %s",
                    msg.payload.counter,
                    self.bin_locks,
                )
                bin_lock = Lock(value=False)
            if bin_lock.value and (datetime.now() - bin_lock.time > BIN_TIMEOUT):
                logger.error(
                    "Timeout in %s on binary command %d",
                    self.my_id,
                    msg.payload.counter,
                )
                self.bin_locks = []
                self._handle_bin_reply_from_is(answer=RxBinaryMsg(self.RET_TIMEOUT))

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.free_lock.value or self.reserve_lock.value:
            if self.free_lock.value:
                logger.info("%s FREE action pending", self.my_id)
                if datetime.now() - self.free_lock.time > RESERVE_TIMEOUT:
                    logger.warning(
                        "Pending FREE on %s took longer than %s",
                        self.my_id,
                        RESERVE_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
            else:
                logger.info("%s RESERVE action pending", self.my_id)
                if datetime.now() - self.reserve_lock.time > RESERVE_TIMEOUT:
                    logger.warning(
                        "Pending RESERVE on %s took longer than %s",
                        self.my_id,
                        RESERVE_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_ReserveDeviceMsg, msg, sender),
                )
                return
        self.reserve_lock.value = True
        self.reserve_lock.time = datetime.now()
        logger.debug("%s: reserve_lock set to %s", self.my_id, self.reserve_lock.time)
        if self.sender_api is None:
            self.sender_api = sender
        self.reserve_device_msg = msg
        self._request_reserve_at_is()

    def _request_reserve_at_is(self):
        # pylint: disable=unused-argument
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.reserve_device_msg: Dataclass identifying the requesting app, host and user.
        """
        self.wakeupAfter(RESERVE_TIMEOUT, "timeout_on_reserve")

    def _handle_reserve_reply_from_is(self, success: Status):
        # pylint: disable=unused-argument
        """Create redirector.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("_handle_reserve_reply_from_is")
        self.return_message = ReservationStatusMsg(
            instr_id=self.instr_id, status=success
        )
        if success in [Status.OK, Status.OK_UPDATED, Status.OK_SKIPPED]:
            try:
                if self.device_status["Reservation"]["Active"]:
                    if (
                        (
                            self.device_status["Reservation"]["Host"]
                            == self.reserve_device_msg.host
                        )
                        and (
                            self.device_status["Reservation"]["App"]
                            == self.reserve_device_msg.app
                        )
                        and (
                            self.device_status["Reservation"]["User"]
                            == self.reserve_device_msg.user
                        )
                    ):
                        self.return_message = ReservationStatusMsg(
                            self.instr_id, Status.OK_UPDATED
                        )
                    else:
                        self.return_message = ReservationStatusMsg(
                            self.instr_id, Status.OCCUPIED
                        )
                        self._send_reservation_status_msg()
                        logger.debug("_send_reservation_status_msg case A")
                        return
            except KeyError:
                logger.debug("First reservation since restart of RegServer")
            if (
                Frontend.REST in frontend_config
            ) and self.reserve_device_msg.create_redirector:
                if not self.child_actors:
                    logger.debug("Create redirector for %s", self.my_id)
                    self._create_redirector()
                else:
                    self._send_reservation_status_msg()
                    logger.debug("_send_reservation_status_msg case F")
            else:
                reservation = {
                    "Active": True,
                    "App": self.reserve_device_msg.app,
                    "Host": self.reserve_device_msg.host,
                    "User": self.reserve_device_msg.user,
                    "Timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                }
                self._update_reservation_status(reservation)
                self._send_reservation_status_msg()
                logger.debug("_send_reservation_status_msg case C")
            return
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation of %s failed with %s. Removing device from list.",
                self.my_id,
                success,
            )
            self._kill_myself(resurrect=True)
        elif success == Status.ERROR:
            logger.error("%s during reservation of %s", success, self.my_id)
            self._kill_myself(resurrect=True)
        self._send_reservation_status_msg()
        logger.debug("_send_reservation_status_msg case D")

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if not is_reserved:
            self.free_lock.value = True
            self.free_lock.time = datetime.now()
            self.return_message = ReservationStatusMsg(self.instr_id, Status.OK_SKIPPED)
            if self.sender_api is None:
                self.sender_api = sender
            self._send_reservation_status_msg()
            return
        if self.free_lock.value or self.reserve_lock.value:
            if self.free_lock.value:
                logger.info("%s FREE action pending", self.my_id)
                if datetime.now() - self.free_lock.time > RESERVE_TIMEOUT:
                    logger.warning(
                        "Pending FREE on %s took longer than %s",
                        self.my_id,
                        RESERVE_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_FreeDeviceMsg, msg, sender),
                )
                return
            logger.info("%s RESERVE action pending", self.my_id)
            if datetime.now() - self.reserve_lock.time > RESERVE_TIMEOUT:
                logger.warning(
                    "Pending RESERVE on %s took longer than %s",
                    self.my_id,
                    RESERVE_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
        self.free_lock.value = True
        self.free_lock.time = datetime.now()
        logger.debug("%s: free_lock set to %s", self.my_id, self.free_lock)
        if self.sender_api is None:
            self.sender_api = sender
        self._request_free_at_is()

    def _request_free_at_is(self):
        # pylint: disable=unused-argument
        """Request freeing an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """
        self.wakeupAfter(RESERVE_TIMEOUT, "timeout_on_free")

    def _handle_free_reply_from_is(self, success: Status):
        # pylint: disable=unused-argument
        """Inform all interested parties that the instrument is free.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("Free command returned %s", success)
        if success in (Status.OK, Status.OK_SKIPPED, Status.OK_UPDATED):
            try:
                if self.device_status["Reservation"]["Active"]:
                    logger.debug("Free active %s", self.my_id)
                    self.device_status["Reservation"]["Active"] = False
                    self.device_status["Reservation"]["Timestamp"] = datetime.now(
                        timezone.utc
                    ).isoformat(timespec="seconds")
                else:
                    success = Status.OK_SKIPPED
            except KeyError:
                logger.debug("Instr. was not reserved before.")
                success = Status.OK_SKIPPED
        self.return_message = ReservationStatusMsg(self.instr_id, success)
        logger.debug(self.device_status)
        if self.child_actors:
            self._forward_to_children(KillMsg())
        else:
            self._send_reservation_status_msg()

    def _create_redirector(self) -> bool:
        """Create redirector actor if it does not exist already"""
        if not self.child_actors:
            self._create_actor(RedirectorActor, short_id(self.my_id), None)
            return True
        return False

    def receiveMsg_SocketMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SocketMsg from Redirector Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.status not in (Status.OK, Status.OK_SKIPPED):
            self.return_message = ReservationStatusMsg(self.instr_id, msg.status)
            self._send_reservation_status_msg()
            logger.debug("_send_reservation_status_msg case E")
            return
        # Write Reservation section into device status
        reservation = {
            "Active": True,
            "App": self.reserve_device_msg.app,
            "Host": self.reserve_device_msg.host,
            "User": self.reserve_device_msg.user,
            "IP": msg.ip_address,
            "Port": msg.port,
            "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._update_reservation_status(reservation)
        self._send_reservation_status_msg()
        logger.debug("_send_reservation_status_msg case B")

    def receiveMsg_GetRecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Get a value from an instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.sender_api is None:
            self.sender_api = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            self._handle_recent_value_reply_from_is(
                answer=RecentValueMsg(
                    status=Status.OCCUPIED,
                    instr_id=self.instr_id,
                )
            )
        else:
            if self.value_lock.value:
                logger.info("%s VALUE action pending", self.my_id)
                if datetime.now() - self.value_lock.time > VALUE_TIMEOUT:
                    logger.warning(
                        "Pending VALUE on %s took longer than %s",
                        self.my_id,
                        VALUE_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_GetRecentValueMsg, msg, sender),
                )
                return
            self.value_lock.value = True
            self.value_lock.time = datetime.now()
            logger.debug("%s: value_lock set to %s", self.my_id, self.value_lock)
            if self.sender_api is None:
                self.sender_api = sender
            self._request_recent_value_at_is(msg, sender)

    def _request_recent_value_at_is(self, msg, sender):
        # pylint: disable=unused-argument
        """Request a recent value at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """
        self.wakeupAfter(VALUE_TIMEOUT, "timeout_on_value")

    def _handle_recent_value_reply_from_is(self, answer: RecentValueMsg):
        # pylint: disable=unused-argument
        """Forward the recent value from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        self.send(self.sender_api, answer)
        self.sender_api = None
        if self.value_lock.value:
            self.value_lock.value = False

    def _handle_set_rtc_reply_from_is(
        self, status: Status, confirm: bool, utc_offset: float = -13, wait: int = 0
    ):
        # pylint: disable=unused-argument
        """Forward the acknowledgement received from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
            confirm (bool): True, if the ACK shall be forwarded;
                            False, if it was called during setup of the UsbActor.
            utc_offset (float): UTC offset (time zone). -13 = unknown
        """
        if confirm:
            self.send(
                self.sender_api,
                SetRtcAckMsg(self.instr_id, status, utc_offset=utc_offset, wait=wait),
            )
        self.sender_api = None
        if self.ack_lock.value:
            self.ack_lock.value = False

    def _handle_start_monitoring_reply_from_is(
        self, status: Status, confirm: bool, offset: timedelta = timedelta(0)
    ):
        # pylint: disable=unused-argument
        """Forward the acknowledgement received from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
            confirm (bool): True, if the ACK shall be forwarded;
                            False, if it was called during setup of the UsbActor.
        """
        if confirm:
            self.send(
                self.sender_api,
                StartMonitoringAckMsg(self.instr_id, status, offset=offset),
            )
        self.sender_api = None
        if self.ack_lock.value:
            self.ack_lock.value = False

    def _handle_stop_monitoring_reply_from_is(self, status: Status):
        # pylint: disable=unused-argument
        """Forward the acknowledgement received from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
        """
        self.send(
            self.sender_api,
            StopMonitoringAckMsg(self.instr_id, status),
        )
        self.sender_api = None
        if self.ack_lock.value:
            self.ack_lock.value = False

    def _update_reservation_status(self, reservation):
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)

    def _send_reservation_status_msg(self):
        logger.debug("%s _send_reservation_status_msg", self.my_id)
        self._publish_status_change()
        logger.debug(
            "%s: %s; %s; %s; %s",
            self.my_id,
            self.return_message,
            self.sender_api,
            self.reserve_lock.value,
            self.free_lock.value,
        )
        if (
            (self.return_message is not None)
            and (self.sender_api is not None)
            and (self.reserve_lock.value or self.free_lock.value)
        ):
            self.send(self.sender_api, self.return_message)
            self.return_message = None
            self.sender_api = None
        if self.reserve_lock.value:
            self.reserve_lock.value = False
        if self.free_lock.value:
            self.free_lock.value = False

    def receiveMsg_GetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetDeviceStatusMsg asking to send updated information
        about the device status to the sender.

        Sends back a message containing the device_status."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.send(sender, UpdateDeviceStatusMsg(self.my_id, self.device_status))

    def receiveMsg_SubscribeToDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler to register a requesting actor to a list of actors
        that are subscribed to receive updates of device status on every change."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.subscribers[msg.actor_id] = sender
        logger.debug("Subscribers for DeviceStatusMsg: %s", self.subscribers)
        if self.device_status:
            self._publish_status([sender])

    def receiveMsg_UnSubscribeFromDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler to unregister a requesting actor from a list of actors
        that are subscribed to receive updates of device status on every change."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.subscribers.pop(msg.actor_id, None)
        logger.debug("Subscribers for DeviceStatusMsg: %s", self.subscribers)

    def _publish_status_change(self):
        """Publish a changed device status to all subscribers."""
        for actor_address in self.subscribers.values():
            self.send(
                actor_address,
                UpdateDeviceStatusMsg(self.my_id, self.device_status),
            )

    def _publish_status(self, new_subscribers: list):
        """Publish a device status to all new_subscribers."""
        for actor_address in new_subscribers:
            self.send(
                actor_address,
                UpdateDeviceStatusMsg(self.my_id, self.device_status),
            )

    def _request_start_monitoring_at_is(self, start_time=None, confirm=False):
        # pylint: disable=unused-argument
        """Handler to start the monitoring mode on the Device Actor.

        This is only a stub. The method is implemented in the backend Device Actor."""
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        logger.info(
            "%s requested to start monitoring at %s",
            self.my_id,
            start_time.isoformat(sep="T", timespec="auto"),
        )
        self.wakeupAfter(START_MONITORING_TIMEOUT, "timeout_on_start_monitoring")

    def _request_stop_monitoring_at_is(self):
        """Handler to terminate the monitoring mode on the Device Actor.

        This is only a stub. The method is implemented in the backend Device Actor."""
        logger.info("%s requested to stop monitoring", self.my_id)
        self.wakeupAfter(STOP_MONITORING_TIMEOUT, "timeout_on_stop_monitoring")

    def _request_bin_at_is(self, data):
        # pylint: disable=unused-argument
        """Handler to forward a binary cmd message into the direction of the
        instrument.

        This is only a stub. The method is implemented in the backend Device Actor.

        """
        logger.debug("cmd: %s", data)
        self.wakeupAfter(
            BIN_TIMEOUT,
            TimeoutMsg(type="bin_timeout", counter=len(self.bin_locks) - 1),
        )

    def _handle_bin_reply_from_is(self, answer: RxBinaryMsg):
        # pylint: disable=unused-argument
        """Forward a binary message from the Instrument Server to the redirector.
        This function has to be called in the protocol specific modules.
        """
        self.send(self.redirector_actor, answer)
        logger.debug(answer.data)
        if self.bin_locks and self.bin_locks[-1].value:
            self.bin_locks[-1].value = False

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.redirector_actor = sender
        self.bin_locks.append(Lock(value=True, time=datetime.now()))
        if len(self.bin_locks) > 256:
            self.bin_locks.pop(0)
        self._request_bin_at_is(msg.data)

    def receiveMsg_BaudRateMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler to change the baud rate of the serial connection.

        This is only a stub. The method is implemented in the USB device actor only."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)

    def receiveMsg_StartMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Start monitoring mode at a given time."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.sender_api is None:
            self.sender_api = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            self._handle_start_monitoring_reply_from_is(
                status=Status.OCCUPIED, confirm=True
            )
        else:
            if self.ack_lock.value:
                logger.info("%s START MONITORING action pending", self.my_id)
                if datetime.now() - self.ack_lock.time > START_MONITORING_TIMEOUT:
                    logger.warning(
                        "Pending START MONITORING on %s took longer than %s",
                        self.my_id,
                        START_MONITORING_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_StartMonitoringMsg, msg, sender),
                )
                return
            self.ack_lock.value = True
            self.ack_lock.time = datetime.now()
            logger.debug("%s: ack_lock set to %s", self.my_id, self.ack_lock)
            self._request_start_monitoring_at_is(msg.start_time, confirm=True)

    def receiveMsg_StopMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Terminate monitoring mode."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.sender_api is None:
            self.sender_api = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if not is_reserved:
            self._handle_stop_monitoring_reply_from_is(status=Status.OK_SKIPPED)
        else:
            if self.ack_lock.value:
                logger.info("%s STOP MONITORING action pending", self.my_id)
                if datetime.now() - self.ack_lock.time > STOP_MONITORING_TIMEOUT:
                    logger.warning(
                        "Pending STOP MONITORING on %s took longer than %s",
                        self.my_id,
                        STOP_MONITORING_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_StopMonitoringMsg, msg, sender),
                )
                return
            self.ack_lock.value = True
            self.ack_lock.time = datetime.now()
            logger.debug("%s: ack_lock set to %s", self.my_id, self.ack_lock)
            self._request_stop_monitoring_at_is()

    def receiveMsg_SetRtcMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the RTC of the instrument given in msg."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.sender_api is None:
            self.sender_api = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            self._handle_set_rtc_reply_from_is(status=Status.OCCUPIED, confirm=True)
        else:
            if self.ack_lock.value:
                logger.info("%s SET RTC action pending", self.my_id)
                if datetime.now() - self.ack_lock.time > SET_RTC_TIMEOUT:
                    logger.warning(
                        "Pending SET RTC on %s took longer than %s",
                        self.my_id,
                        SET_RTC_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_SetRtcMsg, msg, sender),
                )
                return
            self.ack_lock.value = True
            self.ack_lock.time = datetime.now()
            logger.debug("%s: ack_lock set to %s", self.my_id, self.ack_lock)
            self._request_set_rtc_at_is(confirm=True)

    def _request_set_rtc_at_is(self, confirm=False):
        # pylint: disable=unused-argument
        """Request setting the RTC of an instrument. This method has
        to be implemented (overridden) in the backend Device Actor.
        """
        self.wakeupAfter(SET_RTC_TIMEOUT, "timeout_on_set_rtc")

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if self.device_status.get("Reservation", False):
            if self.device_status["Reservation"].get("IP", False):
                self.device_status["Reservation"].pop("IP")
            if self.device_status["Reservation"].get("Port", False):
                self.device_status["Reservation"].pop("Port")
            if self.return_message is None:
                pass
            else:
                self._send_reservation_status_msg()
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        self.device_status["State"] = 1
        try:
            self._send_reservation_status_msg()
        except AttributeError as exception:
            logger.error("%s on %s", exception, self.my_id)
        try:
            super()._kill_myself(register=register, resurrect=resurrect)
        except TypeError:
            pass

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        logger.info(
            "%s exited at %s.",
            self.my_id,
            self.device_status["Identification"]["Host"],
        )
