"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, FreeDeviceMsg, Frontend,
                                      GetDeviceStatusMsg, GetRecentValueMsg,
                                      KillMsg, RecentValueMsg,
                                      ReservationStatusMsg, ReserveDeviceMsg,
                                      RxBinaryMsg, SetRtcAckMsg, SetRtcMsg,
                                      StartMonitoringAckMsg,
                                      StartMonitoringMsg, Status,
                                      StopMonitoringAckMsg, StopMonitoringMsg,
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
class ActionRequest:
    """Class to store requested actions."""

    worker: callable = print
    msg: (
        ReserveDeviceMsg
        | FreeDeviceMsg
        | GetDeviceStatusMsg
        | GetRecentValueMsg
        | StartMonitoringMsg
        | StopMonitoringMsg
        | SetRtcMsg
        | None
    ) = None
    sender: Actor | ActorSystem | None = None
    timeout_handler: callable = print
    on_kill_handler: callable = print
    time: datetime = datetime.min


@dataclass
class RequestLock:
    """Provides a lock to prevent concurrent calls for all common requests."""

    request: ActionRequest = field(default_factory=ActionRequest)
    locked: bool = False


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
            "StartMonitoring": RequestLock(),
            "StopMonitoring": RequestLock(),
            "SetRtc": RequestLock(),
        }
        self.request_queue: list[ActionRequest] = []
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

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to retry a waiting reservation task."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(msg.payload, ActionRequest):
            action_request: ActionRequest = msg.payload
            logger.debug("Retry to start action at %s", self.my_id)
            action_request.worker(action_request)
        elif msg.payload == "timeout":
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
            for _lock_key, lock in self.request_locks.items():
                if lock.locked and (
                    datetime.now() - lock.request.time >= REQUEST_TIMEOUT
                ):
                    logger.warning(
                        "Timeout in locked %s on %s", lock.request.msg, self.my_id
                    )
                    lock.request.timeout_handler(lock.request)
                    lock.locked = False
            for pending_request in self.request_queue:
                if datetime.now() - pending_request.time >= REQUEST_TIMEOUT:
                    logger.warning(
                        "Timeout in pending %s on %s", pending_request.msg, self.my_id
                    )
                    pending_request.timeout_handler(pending_request)
                    self.request_queue.remove(pending_request)
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
        if self._is_reserved():
            self.request_locks["Reserve"].request.sender = sender
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
            self._send_reservation_status_msg(sender)
            return
        if self.on_kill:
            self._handle_reserve_reply_from_is(
                success=Status.NOT_FOUND, requester=sender
            )
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        action_request = ActionRequest(
            worker=self._reserve_device_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._reserve_device_timeout,
            time=datetime.now(),
            on_kill_handler=self._reserve_device_on_kill,
        )
        self._fifo(action_request)

    def _reserve_device_worker(self, action_request):
        if self._lock_request("Reserve", action_request):
            self.reserve_device_msg = deepcopy(action_request.msg)
            self._request_reserve_at_is(action_request.sender)

    def _reserve_device_timeout(self, action_request):
        self._handle_reserve_reply_from_is(
            success=Status.BUSY_TIMEOUT, requester=action_request.sender
        )

    def _reserve_device_on_kill(self, action_request):
        self._handle_reserve_reply_from_is(
            success=Status.NOT_FOUND, requester=action_request.sender
        )

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if not self._is_reserved():
            self.return_message = ReservationStatusMsg(self.instr_id, Status.OK_SKIPPED)
            self._handle_free_reply_from_is(Status.OK_SKIPPED, sender)
            return
        action_request = ActionRequest(
            worker=self._free_device_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._free_device_timeout,
            time=datetime.now(),
            on_kill_handler=self._free_device_on_kill,
        )
        if self.on_kill:
            self._free_device_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _free_device_worker(self, action_request):
        if self._lock_request("Free", action_request):
            self._request_free_at_is(action_request.sender)

    def _free_device_timeout(self, action_request):
        self._handle_free_reply_from_is(
            success=Status.BUSY_TIMEOUT, requester=action_request.sender
        )

    def _free_device_on_kill(self, action_request):
        self._handle_free_reply_from_is(
            success=Status.NOT_FOUND, requester=action_request.sender
        )

    def receiveMsg_SocketMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SocketMsg from Redirector Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        requester = self.request_locks["Reserve"].request.sender
        if msg.status not in (Status.OK, Status.OK_SKIPPED):
            self.return_message = ReservationStatusMsg(self.instr_id, msg.status)
            self._send_reservation_status_msg(requester)
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
        self._send_reservation_status_msg(requester)
        logger.debug("_send_reservation_status_msg case B")

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.redirector_actor = sender
        self.bin_locks.append(Lock(value=True, time=datetime.now()))
        if len(self.bin_locks) > 256:
            self.bin_locks.pop(0)
        self._request_bin_at_is(msg.data)

    def receiveMsg_GetRecentValueMsg(self, msg: GetRecentValueMsg, sender):
        # pylint: disable=invalid-name
        """Get a value from an instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self._is_reserved():
            logger.warning(
                "%s cannot reply to GetRecentValueMsg -- occupied", self.my_id
            )
            self._handle_recent_value_reply_from_is(
                answer=RecentValueMsg(
                    status=Status.OCCUPIED,
                    instr_id=self.instr_id,
                    client=msg.client,
                ),
                requester=sender,
            )
            return
        action_request = ActionRequest(
            worker=self._get_recent_value_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._get_recent_value_timeout,
            time=datetime.now(),
            on_kill_handler=self._get_recent_value_on_kill,
        )
        if self.on_kill:
            self._get_recent_value_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _get_recent_value_worker(self, action_request: ActionRequest):
        if self._lock_request("GetRecentValue", action_request):
            self._request_recent_value_at_is(
                msg=action_request.msg, sender=action_request.sender
            )

    def _get_recent_value_timeout(self, action_request: ActionRequest):
        logger.warning("%s cannot reply to GetRecentValueMsg -- timeout", self.my_id)
        self._handle_recent_value_reply_from_is(
            answer=RecentValueMsg(
                status=Status.BUSY_TIMEOUT,
                instr_id=self.instr_id,
                client=action_request.msg.client,
            ),
            requester=action_request.sender,
        )

    def _get_recent_value_on_kill(self, action_request: ActionRequest):
        logger.warning("%s cannot reply to GetRecentValueMsg -- on kill", self.my_id)
        self._handle_recent_value_reply_from_is(
            answer=RecentValueMsg(
                status=Status.NOT_FOUND,
                instr_id=self.instr_id,
                client=action_request.msg.client,
            ),
            requester=action_request.sender,
        )

    def receiveMsg_GetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetDeviceStatusMsg asking to send updated information
        about the device status to the sender.

        Sends back a message containing the device_status."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self._is_reserved():
            self.request_locks["GetDeviceStatus"].request.sender = sender
            self._handle_status_reply_from_is(Status.OCCUPIED, sender)
            return
        action_request = ActionRequest(
            worker=self._get_device_status_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._get_device_status_timeout,
            time=datetime.now(),
            on_kill_handler=self._get_device_status_on_kill,
        )
        if self.on_kill:
            self._get_device_status_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _get_device_status_worker(self, action_request):
        if self._lock_request("GetDeviceStatus", action_request):
            self._request_status_at_is(action_request.sender)

    def _get_device_status_timeout(self, action_request):
        self._handle_status_reply_from_is(
            status=Status.BUSY_TIMEOUT, requester=action_request.sender
        )

    def _get_device_status_on_kill(self, action_request):
        self._handle_status_reply_from_is(
            status=Status.NOT_FOUND, requester=action_request.sender
        )

    def receiveMsg_StartMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Start monitoring mode at a given time."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self._is_reserved():
            self.request_locks["StartMonitoring"].request.sender = sender
            self._handle_start_monitoring_reply_from_is(
                status=Status.OCCUPIED, confirm=True, requester=sender
            )
            return
        action_request = ActionRequest(
            worker=self._start_monitoring_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._start_monitoring_timeout,
            time=datetime.now(),
            on_kill_handler=self._start_monitoring_on_kill,
        )
        if self.on_kill:
            self._start_monitoring_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _start_monitoring_worker(self, action_request):
        if self._lock_request("StartMonitoring", action_request):
            self._request_start_monitoring_at_is(
                sender=action_request.sender,
                start_time=action_request.msg.start_time,
                confirm=True,
            )

    def _start_monitoring_timeout(self, action_request):
        self._handle_start_monitoring_reply_from_is(
            status=Status.BUSY_TIMEOUT, confirm=True, requester=action_request.sender
        )

    def _start_monitoring_on_kill(self, action_request):
        self._handle_start_monitoring_reply_from_is(
            status=Status.NOT_FOUND, confirm=True, requester=action_request.sender
        )

    def receiveMsg_StopMonitoringMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Terminate monitoring mode."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if not self._is_reserved():
            self._handle_stop_monitoring_reply_from_is(
                status=Status.OK_SKIPPED, requester=sender
            )
            return
        action_request = ActionRequest(
            worker=self._stop_monitoring_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._stop_monitoring_timeout,
            time=datetime.now(),
            on_kill_handler=self._stop_monitoring_on_kill,
        )
        if self.on_kill:
            self._stop_monitoring_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _stop_monitoring_worker(self, action_request: ActionRequest):
        if self._lock_request("StopMonitoring", action_request):
            self._request_stop_monitoring_at_is(action_request.sender)

    def _stop_monitoring_timeout(self, action_request):
        self._handle_stop_monitoring_reply_from_is(
            status=Status.BUSY_TIMEOUT, requester=action_request.sender
        )

    def _stop_monitoring_on_kill(self, action_request):
        self._handle_stop_monitoring_reply_from_is(
            status=Status.NOT_FOUND, requester=action_request.sender
        )

    def receiveMsg_SetRtcMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the RTC of the instrument given in msg."""
        if msg.instr_id != self.instr_id:
            logger.error("%s for %s from %s", msg, self.my_id, sender)
        else:
            logger.debug("%s for %s from %s", msg, self.my_id, sender)
        action_request = ActionRequest(
            worker=self._set_rtc_worker,
            msg=msg,
            sender=sender,
            timeout_handler=self._set_rtc_timeout,
            time=datetime.now(),
            on_kill_handler=self._set_rtc_on_kill,
        )
        if self.on_kill:
            self._set_rtc_on_kill(action_request)
            return
        self.wakeupAfter(REQUEST_TIMEOUT, "timeout")
        self._fifo(action_request)

    def _set_rtc_worker(self, action_request: ActionRequest):
        if self._lock_request("SetRtc", action_request):
            self._request_set_rtc_at_is(sender=action_request.sender, confirm=True)

    def _set_rtc_timeout(self, action_request):
        self._handle_set_rtc_reply_from_is(
            answer=SetRtcAckMsg(self.instr_id, Status.BUSY_TIMEOUT),
            confirm=True,
            requester=action_request.sender,
        )

    def _set_rtc_on_kill(self, action_request):
        self._handle_set_rtc_reply_from_is(
            answer=SetRtcAckMsg(self.instr_id, Status.NOT_FOUND),
            confirm=True,
            requester=action_request.sender,
        )

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if self.device_status.get("Reservation", False):
            if self.device_status["Reservation"].get("IP", False):
                self.device_status["Reservation"].pop("IP")
            if self.device_status["Reservation"].get("Port", False):
                self.device_status["Reservation"].pop("Port")
            if self.return_message is not None:
                self._send_free_status_msg(self.request_locks["Free"].request.sender)
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def receiveMsg_ActorExitRequest(self, msg, sender):
        super().receiveMsg_ActorExitRequest(msg, sender)
        logger.debug(
            "%s exited at %s.",
            self.my_id,
            self.device_status["Identification"]["Host"],
        )

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

    def _request_reserve_at_is(self, sender):
        # pylint: disable=unused-argument
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.reserve_device_msg: Dataclass identifying the requesting app, host and user.
        """

    def _request_free_at_is(self, sender):
        # pylint: disable=unused-argument
        """Request freeing an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """

    def _handle_reserve_reply_from_is(self, success: Status, requester):
        # pylint: disable=unused-argument
        """Create redirector.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("_handle_reserve_reply_from_is. %s, %s", success, requester)
        if success not in [Status.OCCUPIED]:
            self._release_lock("Reserve")
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
                        self._send_reservation_status_msg(requester)
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
                    self._send_reservation_status_msg(requester)
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
                self._send_reservation_status_msg(requester)
                logger.debug("_send_reservation_status_msg case C")
            return
        self.return_message = ReservationStatusMsg(self.instr_id, success)
        if success in [
            Status.BUSY_TIMEOUT,
            Status.NOT_FOUND,
            Status.IS_NOT_FOUND,
            Status.ERROR,
        ]:
            logger.error(
                "Reservation of %s failed with %s.",
                self.my_id,
                success,
            )
            self._send_reservation_status_msg(requester)

    def _handle_free_reply_from_is(self, success: Status, requester):
        # pylint: disable=unused-argument
        """Inform all interested parties that the instrument is free.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("Free command on %s returned %s", self.instr_id, success)
        if success not in [Status.OK_SKIPPED]:
            self._release_lock("Free")
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
            self._send_free_status_msg(requester)

    def _create_redirector(self) -> bool:
        """Create redirector actor if it does not exist already"""
        if not self.child_actors:
            self._create_actor(RedirectorActor, short_id(self.my_id), None)
            return True
        return False

    def _request_recent_value_at_is(self, msg, sender):
        # pylint: disable=unused-argument
        """Request a recent value at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.
        """
        logger.debug(
            "_request_recent_value_at_is %d/%d/%d for %s",
            msg.component,
            msg.sensor,
            msg.measurand,
            self.my_id,
        )

    def _handle_recent_value_reply_from_is(self, answer: RecentValueMsg, requester):
        # pylint: disable=unused-argument
        """Forward the recent value from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        logger.debug("Send answer to requester: %s", answer)
        client = ""
        for _key, request_lock in self.request_locks.items():
            if request_lock.locked:
                client = request_lock.request.msg.client
                break
        if client:
            answer = replace(answer, client=client)
        logger.debug("Recent value reply from %s to %s", self.my_id, answer.client)
        self.send(requester, answer)
        if answer.status not in [Status.OCCUPIED]:
            self._release_lock("GetRecentValue")

    def _handle_set_rtc_reply_from_is(
        self, answer: SetRtcAckMsg, requester, confirm: bool
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
            client = ""
            for _key, request_lock in self.request_locks.items():
                if request_lock.locked:
                    client = request_lock.request.msg.client
                    break
            answer = replace(answer, client=client)
            logger.info("Set RTC reply from %s to %s", self.my_id, client)
            self.send(requester, answer)
        if answer.status not in [Status.OCCUPIED]:
            self._release_lock("SetRtc")

    def _handle_start_monitoring_reply_from_is(
        self, status: Status, requester, confirm: bool, offset: timedelta = timedelta(0)
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
            client = ""
            for _key, request_lock in self.request_locks.items():
                if request_lock.locked:
                    client = request_lock.request.msg.client
                    break
            self.send(
                requester,
                StartMonitoringAckMsg(
                    self.instr_id, status, offset=offset, client=client
                ),
            )
        if status not in [Status.OCCUPIED]:
            self._release_lock("StartMonitoring")

    def _handle_stop_monitoring_reply_from_is(self, status: Status, requester):
        # pylint: disable=unused-argument
        """Forward the acknowledgement received from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
        """
        client = ""
        for _key, request_lock in self.request_locks.items():
            if request_lock.locked:
                client = request_lock.request.msg.client
                break
        self.send(
            requester,
            StopMonitoringAckMsg(self.instr_id, status, client=client),
        )
        if status not in [Status.OCCUPIED]:
            self._release_lock("StopMonitoring")

    def _update_reservation_status(self, reservation):
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)

    def _send_reservation_status_msg(self, requester):
        logger.debug("%s _send_reservation_status_msg", self.my_id)
        self._publish_status_change()
        if requester not in [self.myAddress, None]:
            if self.return_message is not None:
                self.send(requester, self.return_message)
            else:
                logger.error(
                    "self.return_message should contain a ReservationStatusMsg for Reserve"
                )
        if self.return_message.status not in [Status.OCCUPIED]:
            self._release_lock("Reserve")
        self.return_message = None

    def _send_free_status_msg(self, requester):
        logger.debug("%s _send_free_status_msg", self.my_id)
        self._publish_status_change()
        if requester not in [self.myAddress, None]:
            if self.return_message is not None:
                self.send(requester, self.return_message)
            else:
                logger.error(
                    "self.return_message should contain a ReservationStatusMsg for Free"
                )
        if self.return_message.status not in [Status.OK_SKIPPED]:
            self._release_lock("Free")
        self.return_message = None

    def _request_status_at_is(self, sender):
        """Send a request to the Instrument Server to get the recent status of
        the device.

        This has to be overriden in the backend specific implementation."""
        self._handle_status_reply_from_is(Status.OK, sender)

    def _handle_status_reply_from_is(self, status: Status, requester):
        # pylint: disable=unused-argument
        """Forward the status received from the Instrument Server to the sender
        requesting status information. This function has to be called in the
        protocol specific modules.

        Args:
            status (Status): Info about the success of operation.
        """
        self.send(
            requester,
            UpdateDeviceStatusMsg(self.my_id, self.device_status),
        )
        if status not in [Status.OCCUPIED]:
            self._release_lock("GetDeviceStatus")

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

    def _request_start_monitoring_at_is(self, sender, start_time=None, confirm=False):
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

    def _request_stop_monitoring_at_is(self, sender):
        """Handler to terminate the monitoring mode on the Device Actor.

        This is only a stub. The method is implemented in the backend Device Actor."""
        logger.info("%s requested to stop monitoring", self.my_id)

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

    def _request_set_rtc_at_is(self, sender, confirm=False):
        # pylint: disable=unused-argument
        """Request setting the RTC of an instrument. This method has
        to be implemented (overridden) in the backend Device Actor.
        """

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if not self.on_kill:
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
            for _lock_key, lock in self.request_locks.items():
                if lock.locked:
                    lock.request.on_kill_handler(lock.request)
            for pending_request in self.request_queue:
                pending_request.on_kill_handler(pending_request)
        try:
            super()._kill_myself(register=register, resurrect=resurrect)
        except TypeError as exception:
            logger.warning("TypeError in _kill_myself on %s: %s", self.my_id, exception)

    def _lock_request(self, request_lock: str, action_request: ActionRequest) -> bool:
        """Set the lock for the request, check for reservation and forward the
        request to Instrument Server."""
        logger.debug("Request %s lock for %s", request_lock, self.my_id)
        if action_request not in self.request_queue:
            return False
        for lock_key, lock in self.request_locks.items():
            if lock.locked:
                logger.debug("%s %s action pending", self.my_id, lock_key)
                if datetime.now() - lock.request.time >= REQUEST_TIMEOUT:
                    logger.warning(
                        "Pending %s on %s took longer than %s",
                        request_lock,
                        self.my_id,
                        REQUEST_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return False
                self.wakeupAfter(timedelta(milliseconds=500), action_request)
                return False
        self.request_queue.pop(
            0
        )  # Every request shall either be in the queue or in the lock.
        self.request_locks[request_lock].request = action_request
        self.request_locks[request_lock].locked = True
        return True

    def _is_reserved(self) -> bool:
        """Helper to find out whether this device is reserved."""
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            return self.device_status["Reservation"].get("Active", False)
        return False

    def _release_lock(self, request_lock: str):
        """Release the lock."""
        self.request_locks[request_lock].locked = False

    def _fifo(self, action_request):
        """Puts action_request into the request_queue, takes the first action
        from the queue and calls its worker."""
        self.request_queue.append(action_request)
        logger.debug("%d elements in queue of %s", len(self.request_queue), self.my_id)
        dequeued_action = self.request_queue[0]
        dequeued_action.worker(dequeued_action)
