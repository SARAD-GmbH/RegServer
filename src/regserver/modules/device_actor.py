"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from copy import deepcopy
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
from regserver.config import config, frontend_config
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.redirect_actor import RedirectorActor
from thespian.actors import Actor, ActorSystem  # type: ignore

REQUEST_TIMEOUT = timedelta(seconds=20)  # Timeout for all backend requests


@dataclass
class Lock:
    """Provides a lock to prevent concurrent calls of binary messages."""

    value: bool
    time: datetime = datetime.min


@dataclass
class RequestLock:
    """Provides a lock to prevent concurrent calls for all common requests."""

    requester: Actor | ActorSystem | None = None
    locked: bool = False
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

    RET_TIMEOUT = b"B\x80\x7f\xf0\xf0\x00E"

    @overrides
    def __init__(self):
        super().__init__()
        self.device_status: dict = {}
        self.prev_device_status: dict = {}
        self.subscribers: dict = {}
        self.reserve_device_msg: ReserveDeviceMsg = ReserveDeviceMsg(
            host="", user="", app="", create_redirector=False
        )
        self.actor_type = ActorType.DEVICE
        self.redirector_actor = None
        self.return_message = None
        self.instr_id: str = ""
        self.request_locks: dict[str, RequestLock] = {
            "Reserve": RequestLock(),
            "Free": RequestLock(),
            "GetRecentValue": RequestLock(),
            "GetDeviceStatus": RequestLock(),
            "BaudRate": RequestLock(),
            "StartMonitoring": RequestLock(),
            "StopMonitoring": RequestLock(),
            "SetRtc": RequestLock(),
        }
        self.bin_locks: list[Lock] = []

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self.instr_id = short_id(self.my_id)

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._finish_set_device_status(msg.device_status)

    def _finish_set_device_status(self, device_status):
        sections = ["Identification", "Reservation", "Remote"]
        for section in sections:
            if device_status.get(section, False):
                if self.device_status.get(section, False):
                    for key in self.device_status[section]:
                        if key in device_status[section]:
                            self.device_status[section][key] = device_status[section][
                                key
                            ]
                else:
                    self.device_status[section] = device_status[section]
        if device_status.get("State", False):
            self.device_status["State"] = device_status["State"]
        if device_status.get("Reservation", False):
            if device_status["Reservation"].get("Active", False):
                if not device_status["Reservation"].get("Host", False):
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
            and self.request_locks["Reserve"].locked
            and (datetime.now() - self.request_locks["Reserve"].time > REQUEST_TIMEOUT)
        ):
            self._handle_reserve_reply_from_is(success=Status.NOT_FOUND)
        elif (
            (msg.payload == "timeout_on_free")
            and self.request_locks["Free"].locked
            and (datetime.now() - self.request_locks["Free"].time > REQUEST_TIMEOUT)
        ):
            self._handle_free_reply_from_is(success=Status.NOT_FOUND)
        elif (
            (msg.payload == "timeout_on_value")
            and self.request_locks["GetRecentValue"].locked
            and (
                datetime.now() - self.request_locks["GetRecentValue"].time
                > REQUEST_TIMEOUT
            )
        ):
            self._handle_recent_value_reply_from_is(
                answer=RecentValueMsg(
                    status=Status.NOT_FOUND,
                    instr_id=self.instr_id,
                )
            )
        elif (
            (msg.payload == "timeout_on_set_rtc")
            and self.request_locks["SetRtc"].locked
            and (datetime.now() - self.request_locks["SetRtc"].time > REQUEST_TIMEOUT)
        ):
            self._handle_set_rtc_reply_from_is(status=Status.NOT_FOUND, confirm=True)
        elif (
            (msg.payload == "timeout_on_start_monitoring")
            and self.request_locks["StartMonitoring"].locked
            and (
                datetime.now() - self.request_locks["StartMonitoring"].time
                > REQUEST_TIMEOUT
            )
        ):
            self._handle_start_monitoring_reply_from_is(
                status=Status.NOT_FOUND, confirm=True
            )
        elif (
            (msg.payload == "timeout_on_stop_monitoring")
            and self.request_locks.get(
                "StopMonitoring", RequestLock(locked=False)
            ).locked
            and (
                datetime.now() - self.request_locks["StopMonitoring"].time
                > REQUEST_TIMEOUT
            )
        ):
            self._handle_stop_monitoring_reply_from_is(status=Status.NOT_FOUND)
        elif (
            (msg.payload == "timeout_on_get_device_status")
            and self.request_locks["GetDeviceStatus"].locked
            and (
                datetime.now() - self.request_locks["GetDeviceSatus"].time
                > REQUEST_TIMEOUT
            )
        ):
            self._handle_status_reply_from_is(status=Status.NOT_FOUND)
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
            if bin_lock.value and (datetime.now() - bin_lock.time > REQUEST_TIMEOUT):
                logger.error(
                    "Timeout in %s on binary command %d",
                    self.my_id,
                    msg.payload.counter,
                )
                self.bin_locks = []
                self._kill_myself()

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.request_locks["Free"].locked:
            logger.info("%s FREE action pending", self.my_id)
            if datetime.now() - self.request_locks["Free"].time > REQUEST_TIMEOUT:
                logger.warning(
                    "Pending FREE on %s took longer than %s",
                    self.my_id,
                    REQUEST_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
        if self.request_locks["Reserve"].locked:
            logger.info("%s RESERVE action pending", self.my_id)
            if datetime.now() - self.request_locks["Reserve"].time > REQUEST_TIMEOUT:
                logger.warning(
                    "Pending RESERVE on %s took longer than %s",
                    self.my_id,
                    REQUEST_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
            self.wakeupAfter(
                timedelta(milliseconds=500),
                (self.receiveMsg_ReserveDeviceMsg, msg, sender),
            )
            return
        self.request_locks["Reserve"].locked = True
        self.request_locks["Reserve"].time = datetime.now()
        self.request_locks["Reserve"].requester = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            reservation = self.device_status["Reservation"]
            current_user = reservation.get("User", "")
            current_app = reservation.get("App", "")
            current_host = reservation.get("Host", "")
            requested_user = msg.user
            requested_app = msg.app
            requested_host = msg.host
            if (
                current_user == requested_user
                and current_app == requested_app
                and current_host == requested_host
            ):
                reply_status = Status.OK_UPDATED
            else:
                reply_status = Status.OCCUPIED
            self.return_message = ReservationStatusMsg(self.instr_id, reply_status)
            self._send_reservation_status_msg()
            return
        self.reserve_device_msg = deepcopy(msg)
        self._request_reserve_at_is()

    def _request_reserve_at_is(self):
        # pylint: disable=unused-argument
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.reserve_device_msg: Dataclass identifying the requesting app, host and user.
        """
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_reserve")

    def _handle_reserve_reply_from_is(self, success: Status):
        # pylint: disable=unused-argument
        """Create redirector.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("_handle_reserve_reply_from_is")
        self.request_locks["Reserve"].locked = False
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
                            self.instr_id, Status.OK
                        )
                    else:
                        self.return_message = ReservationStatusMsg(
                            self.instr_id, Status.OCCUPIED
                        )
                        self._send_reservation_status_msg()
                        logger.debug("_send_reservation_status_msg case A")
                        return
            except (KeyError, TypeError):
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
        self.return_message = ReservationStatusMsg(self.instr_id, success)
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation of %s failed with %s. Removing device from list.",
                self.my_id,
                success,
            )
            self._send_reservation_status_msg()
            self._kill_myself(resurrect=True)
        elif success == Status.ERROR:
            logger.error("%s during reservation of %s", success, self.my_id)
            self._send_reservation_status_msg()
            logger.debug("_send_reservation_status_msg case D")
            self._kill_myself(resurrect=True)

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.request_locks["Free"].locked:
            logger.info("%s FREE action pending", self.my_id)
            if datetime.now() - self.request_locks["Free"].time > REQUEST_TIMEOUT:
                logger.warning(
                    "Pending FREE on %s took longer than %s",
                    self.my_id,
                    REQUEST_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
            self.wakeupAfter(
                timedelta(milliseconds=500),
                (self.receiveMsg_FreeDeviceMsg, msg, sender),
            )
            return
        if self.request_locks["Reserve"].locked:
            logger.info("%s RESERVE action pending", self.my_id)
            if datetime.now() - self.request_locks["Reserve"].time > REQUEST_TIMEOUT:
                logger.warning(
                    "Pending RESERVE on %s took longer than %s",
                    self.my_id,
                    REQUEST_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
        self.request_locks["Free"].locked = True
        self.request_locks["Free"].time = datetime.now()
        self.request_locks["Free"].requester = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if not is_reserved:
            self.return_message = ReservationStatusMsg(self.instr_id, Status.OK_SKIPPED)
            self._handle_free_reply_from_is(Status.OK_SKIPPED)
            return
        self._request_free_at_is()

    def _request_free_at_is(self):
        # pylint: disable=unused-argument
        """Request freeing an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_free")

    def _handle_free_reply_from_is(self, success: Status):
        # pylint: disable=unused-argument
        """Inform all interested parties that the instrument is free.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.info("Free command on %s returned %s", self.instr_id, success)
        self.request_locks["Free"].locked = False
        if success in (Status.OK, Status.OK_SKIPPED, Status.OK_UPDATED):
            try:
                logger.debug("Free active %s", self.my_id)
                self.device_status["Reservation"]["Active"] = False
                self.device_status["Reservation"]["Timestamp"] = datetime.now(
                    timezone.utc
                ).isoformat(timespec="seconds")
            except (KeyError, TypeError):
                logger.debug("Instr. was not reserved before.")
                success = Status.OK_SKIPPED
        self.return_message = ReservationStatusMsg(self.instr_id, success)
        logger.debug(self.device_status)
        if self.child_actors:
            self._forward_to_children(KillMsg())
        else:
            self._send_free_status_msg()

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
        self.request_locks["GetRecentValue"].requester = sender
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
            if self.request_locks["GetRecentValue"].locked:
                logger.info("%s VALUE action pending", self.my_id)
                if (
                    datetime.now() - self.request_locks["GetRecentValue"].time
                    > REQUEST_TIMEOUT
                ):
                    logger.warning(
                        "Pending VALUE on %s took longer than %s",
                        self.my_id,
                        REQUEST_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_GetRecentValueMsg, msg, sender),
                )
                return
            self.request_locks["GetRecentValue"].locked = True
            self.request_locks["GetRecentValue"].time = datetime.now()
            self._request_recent_value_at_is(msg, sender)

    def _request_recent_value_at_is(self, msg, sender):
        # pylint: disable=unused-argument
        """Request a recent value at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_value")

    def _handle_recent_value_reply_from_is(self, answer: RecentValueMsg):
        # pylint: disable=unused-argument
        """Forward the recent value from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("Send answer to requester: %s", answer)
        self.request_locks["GetRecentValue"].locked = False
        self.send(self.request_locks["GetRecentValue"].requester, answer)

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
        self.request_locks["SetRtc"].locked = False
        if confirm:
            self.send(
                self.request_locks["SetRtc"].requester,
                SetRtcAckMsg(self.instr_id, status, utc_offset=utc_offset, wait=wait),
            )

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
        self.request_locks["StartMonitoring"].locked = False
        if confirm:
            self.send(
                self.request_locks["StartMonitoring"].requester,
                StartMonitoringAckMsg(self.instr_id, status, offset=offset),
            )

    def _handle_stop_monitoring_reply_from_is(self, status: Status):
        # pylint: disable=unused-argument
        """Forward the acknowledgement received from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
        """
        self.request_locks["StopMonitoring"].locked = False
        self.send(
            self.request_locks["StopMonitoring"].requester,
            StopMonitoringAckMsg(self.instr_id, status),
        )

    def _update_reservation_status(self, reservation):
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)

    def _send_reservation_status_msg(self):
        logger.debug("%s _send_reservation_status_msg", self.my_id)
        self._publish_status_change()
        if self.request_locks["Reserve"].requester is not None:
            if self.return_message is not None:
                self.send(self.request_locks["Reserve"].requester, self.return_message)
            else:
                logger.error(
                    "self.return_message should contain a ReservationStatusMsg for Reserve"
                )
        self.return_message = None
        self.request_locks["Reserve"].locked = False

    def _send_free_status_msg(self):
        logger.debug("%s _send_reservation_status_msg", self.my_id)
        self._publish_status_change()
        if self.request_locks["Free"].requester is not None:
            if self.return_message is not None:
                self.send(self.request_locks["Free"].requester, self.return_message)
            else:
                logger.error(
                    "self.return_message should contain a ReservationStatusMsg for Free"
                )
        self.return_message = None
        self.request_locks["Free"].locked = False

    def receiveMsg_GetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetDeviceStatusMsg asking to send updated information
        about the device status to the sender.

        Sends back a message containing the device_status."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        # TODO Lock!
        self.request_locks["GetDeviceStatus"].requester = sender
        self.request_locks["GetDeviceStatus"].locked = True
        self._request_status_at_is()

    def _request_status_at_is(self):
        """Send a request to the Instrument Server to get the recent status of
        the device.

        This has to be overriden in the backend specific implementation."""
        self._handle_status_reply_from_is(Status.OK)

    def _handle_status_reply_from_is(self, status: Status):
        # pylint: disable=unused-argument
        """Forward the status received from the Instrument Server to the sender
        requesting status information. This function has to be called in the
        protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
        """
        self.send(
            self.request_locks["GetDeviceStatus"].requester,
            UpdateDeviceStatusMsg(self.my_id, self.device_status),
        )
        self.request_locks["GetDeviceStatus"].locked = False

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
        if self.prev_device_status != self.device_status:
            if self.device_status.get("Identification", False):
                self.device_status["Identification"]["IS Id"] = self.device_status[
                    "Identification"
                ].get("IS Id", config["IS_ID"])
                for actor_address in self.subscribers.values():
                    self.send(
                        actor_address,
                        UpdateDeviceStatusMsg(self.my_id, self.device_status),
                    )
            logger.debug("Published change: %s", self.device_status)
            self.prev_device_status = deepcopy(self.device_status)

    def _publish_status(self, new_subscribers: list):
        """Publish a device status to all new_subscribers."""
        if self.device_status.get("Identification", False):
            self.device_status["Identification"]["IS Id"] = self.device_status[
                "Identification"
            ].get("IS Id", config["IS_ID"])
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
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_start_monitoring")

    def _request_stop_monitoring_at_is(self):
        """Handler to terminate the monitoring mode on the Device Actor.

        This is only a stub. The method is implemented in the backend Device Actor."""
        logger.info("%s requested to stop monitoring", self.my_id)
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_stop_monitoring")

    def _request_bin_at_is(self, data):
        # pylint: disable=unused-argument
        """Handler to forward a binary cmd message into the direction of the
        instrument.

        This is only a stub. The method is implemented in the backend Device Actor.

        """
        logger.debug("cmd: %s", data)
        self.wakeupAfter(
            REQUEST_TIMEOUT,
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
        self.request_locks["StartMonitoring"].requester = sender
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
            if self.request_locks["StartMonitoring"].locked:
                logger.info("%s START MONITORING action pending", self.my_id)
                if (
                    datetime.now() - self.request_locks["StartMonitoring"].time
                    > REQUEST_TIMEOUT
                ):
                    logger.warning(
                        "Pending START MONITORING on %s took longer than %s",
                        self.my_id,
                        REQUEST_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_StartMonitoringMsg, msg, sender),
                )
                return
            self.request_locks["StartMonitoring"].locked = True
            self.request_locks["StartMonitoring"].time = datetime.now()
            self._request_start_monitoring_at_is(msg.start_time, confirm=True)

    def receiveMsg_StopMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Terminate monitoring mode."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.request_locks["StopMonitoring"].requester = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if not is_reserved:
            self._handle_stop_monitoring_reply_from_is(status=Status.OK_SKIPPED)
        else:
            if self.request_locks["StopMonitoring"].locked:
                logger.info("%s STOP MONITORING action pending", self.my_id)
                if (
                    datetime.now() - self.request_locks["StopMonitoring"].time
                    > REQUEST_TIMEOUT
                ):
                    logger.warning(
                        "Pending STOP MONITORING on %s took longer than %s",
                        self.my_id,
                        REQUEST_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_StopMonitoringMsg, msg, sender),
                )
                return
            self.request_locks["StopMonitoring"].locked = True
            self.request_locks["StopMonitoring"].time = datetime.now()
            self._request_stop_monitoring_at_is()

    def receiveMsg_SetRtcMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the RTC of the instrument given in msg."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.request_locks["SetRtc"].requester = sender
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            self._handle_set_rtc_reply_from_is(status=Status.OCCUPIED, confirm=True)
        else:
            if self.request_locks["SetRtc"].locked:
                logger.info("%s SET RTC action pending", self.my_id)
                if datetime.now() - self.request_locks["SetRtc"].time > REQUEST_TIMEOUT:
                    logger.warning(
                        "Pending SET RTC on %s took longer than %s",
                        self.my_id,
                        REQUEST_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
                self.wakeupAfter(
                    timedelta(milliseconds=500),
                    (self.receiveMsg_SetRtcMsg, msg, sender),
                )
                return
            self.request_locks["SetRtc"].locked = True
            self.request_locks["SetRtc"].time = datetime.now()
            self._request_set_rtc_at_is(confirm=True)

    def _request_set_rtc_at_is(self, confirm=False):
        # pylint: disable=unused-argument
        """Request setting the RTC of an instrument. This method has
        to be implemented (overridden) in the backend Device Actor.
        """
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout_on_set_rtc")

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if self.device_status.get("Reservation", False):
            if self.device_status["Reservation"].get("IP", False):
                self.device_status["Reservation"].pop("IP")
            if self.device_status["Reservation"].get("Port", False):
                self.device_status["Reservation"].pop("Port")
            if self.return_message is not None:
                self._send_free_status_msg()
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.device_status.get("Reservation", False):
            if (
                self.device_status["Reservation"].get("Active", False)
                and self.child_actors
                and self.redirector_actor is not None
            ):
                self._handle_bin_reply_from_is(answer=RxBinaryMsg(self.RET_TIMEOUT))
        self.device_status["State"] = 1
        if self.child_actors:
            logger.info("%s has children: %s", self.my_id, self.child_actors)
        if self.request_locks["Reserve"].locked:
            self._handle_reserve_reply_from_is(success=Status.NOT_FOUND)
        if self.request_locks["Free"].locked:
            self._handle_free_reply_from_is(success=Status.NOT_FOUND)
        if self.request_locks["GetRecentValue"].locked:
            self._handle_recent_value_reply_from_is(
                answer=RecentValueMsg(
                    status=Status.NOT_FOUND,
                    instr_id=self.instr_id,
                )
            )
        if self.request_locks["SetRtc"].locked:
            self._handle_set_rtc_reply_from_is(status=Status.NOT_FOUND, confirm=True)
        if self.request_locks["StartMonitoring"].locked:
            self._handle_start_monitoring_reply_from_is(
                status=Status.NOT_FOUND, confirm=True
            )
        if self.request_locks["StopMonitoring"].locked:
            self._handle_stop_monitoring_reply_from_is(status=Status.NOT_FOUND)
        if self.request_locks["GetDeviceStatus"].locked:
            self._handle_status_reply_from_is(status=Status.NOT_FOUND)
        try:
            super()._kill_myself(register=register, resurrect=resurrect)
        except TypeError as exception:
            logger.warning("TypeError in _kill_myself on %s: %s", self.my_id, exception)

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        logger.info(
            "%s exited at %s.",
            self.my_id,
            self.device_status["Identification"]["Host"],
        )
