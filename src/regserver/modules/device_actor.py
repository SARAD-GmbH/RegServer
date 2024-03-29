"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""
from datetime import datetime, timedelta, timezone

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, Frontend, KillMsg,
                                      ReservationStatusMsg, Status,
                                      UpdateDeviceStatusMsg)
from regserver.base_actor import BaseActor
from regserver.config import frontend_config
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.redirect_actor import RedirectorActor

RESERVE_TIMEOUT = timedelta(seconds=10)  # Timeout for RESERVE or FREE operations


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

    @overrides
    def __init__(self):
        super().__init__()
        self.device_status = {}
        self.subscribers = {}
        self.reserve_device_msg = None
        self.sender_api = None
        self.actor_type = ActorType.DEVICE
        self.redirector_actor = None
        self.return_message = None
        self.instr_id = None
        self.reserve_lock = False
        self.free_lock = False

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
        logger.info(
            "Device actor %s created or updated at %s. is_id = %s",
            self.my_id,
            self.device_status["Identification"].get("Host"),
            self.device_status["Identification"].get("IS Id"),
        )

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to retry a waiting reservation task."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(msg.payload, tuple):
            msg.payload[0](msg.payload[1], msg.payload[2])
        elif (msg.payload == "timeout_on_reserve") and self.reserve_lock:
            self.reserve_lock = False
            self._handle_reserve_reply_from_is(success=Status.NOT_FOUND)
        elif (msg.payload == "timeout_on_free") and self.free_lock:
            self.free_lock = False
            self._handle_free_reply_from_is(success=Status.NOT_FOUND)

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.free_lock or self.reserve_lock:
            if self.free_lock:
                logger.info("%s FREE action pending", self.my_id)
                if datetime.now() - self.free_lock > RESERVE_TIMEOUT:
                    logger.warning(
                        "Pending FREE on %s took longer than %s",
                        self.my_id,
                        RESERVE_TIMEOUT,
                    )
                    self._kill_myself(resurrect=True)
                    return
            else:
                logger.info("%s RESERVE action pending", self.my_id)
                if datetime.now() - self.reserve_lock > RESERVE_TIMEOUT:
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
        self.reserve_lock = datetime.now()
        logger.debug("%s: reserve_lock set to %s", self.my_id, self.reserve_lock)
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
            if Frontend.REST in frontend_config:
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
        is_reserved = self.device_status.get("Reservation", False)
        if is_reserved:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        if not is_reserved:
            self.free_lock = datetime.now()
            self.return_message = ReservationStatusMsg(self.instr_id, Status.OK_SKIPPED)
            if self.sender_api is None:
                self.sender_api = sender
            self._send_reservation_status_msg()
            return
        if self.free_lock or self.reserve_lock:
            if self.free_lock:
                logger.info("%s FREE action pending", self.my_id)
                if datetime.now() - self.free_lock > RESERVE_TIMEOUT:
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
            if datetime.now() - self.reserve_lock > RESERVE_TIMEOUT:
                logger.warning(
                    "Pending RESERVE on %s took longer than %s",
                    self.my_id,
                    RESERVE_TIMEOUT,
                )
                self._kill_myself(resurrect=True)
                return
        self.free_lock = datetime.now()
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
                    logger.info("Free active %s", self.my_id)
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
        try:
            assert msg.status in (Status.OK, Status.OK_SKIPPED)
        except AssertionError:
            self.return_message = ReservationStatusMsg(
                self.instr_id, Status.UNKNOWN_PORT
            )
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
            self.reserve_lock,
            self.free_lock,
        )
        if (
            (self.return_message is not None)
            and (self.sender_api is not None)
            and (self.reserve_lock or self.free_lock)
        ):
            self.send(self.sender_api, self.return_message)
            self.return_message = None
            self.sender_api = None
        if self.reserve_lock:
            self.reserve_lock = False
        if self.free_lock:
            self.free_lock = False

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

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.redirector_actor = sender

    def receiveMsg_BaudRateMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler to change the baud rate of the serial connection.

        This is only a stub. The method is implemented in the USB device actor only."""
        logger.info("%s for %s from %s", msg, self.my_id, sender)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if self.device_status["Reservation"].get("IP") is not None:
            self.device_status["Reservation"].pop("IP")
        if self.device_status["Reservation"].get("Port") is not None:
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
            "Device actor %s exited at %s.",
            self.my_id,
            self.device_status["Identification"]["Host"],
        )
