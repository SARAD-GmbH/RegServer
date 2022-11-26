"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-device_actor.puml
"""
from datetime import datetime

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (Frontend, KillMsg,
                                               ReservationStatusMsg, Status,
                                               UpdateDeviceStatusMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import frontend_config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.redirect_actor import RedirectorActor
from registrationserver.shutdown import system_shutdown

# logger.debug("%s -> %s", __package__, __file__)


class DeviceBaseActor(BaseActor):
    """Base class for protocol specific device actors.

    Implements all methods that all device actors have in common.
    Handles the following actor messages:

    * SetupMsg: is used to initialize the actor right after its creation.
      This is needed because some parts of the initialization cannot be done in
      __init__(). Other initialization steps require data from the
      MdnsListener/MqttListener creating the device actor. The same method is
      used for updates of the device state comming from the
      MdnsListener/MqttListener.

    * ReserveDeviceMsg: is being called when the end-user-application wants to
        reserve the directly or indirectly connected device for exclusive
        communication, should return if a reservation is currently possible

    * TxBinaryMsg: is being called when the end-user-application wants to send
        data, should return the direct or indirect response from the device,
        None in case the device is not reachable (so the end application can
        set the timeout itself)

    * FreeDeviceMsg: is being called when the end-user-application is done
        requesting or sending data, should return True as soon the freeing
        process has been initialized.
    """

    @overrides
    def __init__(self):
        super().__init__()
        self.device_status = {}
        self.subscribers = {}
        self.reserve_device_msg = None
        self.sender_api = None
        self.is_device_actor = True
        self.redirector_actor = None
        self.return_message = None

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_status = msg.device_status
        logger.debug("Device status: %s", self.device_status)
        self._publish_status_change()

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.sender_api = sender
        self.reserve_device_msg = msg
        instr_id = short_id(self.my_id)
        try:
            if self.device_status["Reservation"]["Active"]:
                if (
                    (self.device_status["Reservation"]["Host"] == msg.host)
                    and (self.device_status["Reservation"]["App"] == msg.app)
                    and (self.device_status["Reservation"]["User"] == msg.user)
                ):
                    return_message = ReservationStatusMsg(instr_id, Status.OK_UPDATED)
                else:
                    return_message = ReservationStatusMsg(instr_id, Status.OCCUPIED)
                self.send(self.sender_api, return_message)
                return
        except KeyError:
            logger.debug("First reservation since restart of RegServer")
        self.return_message = ReservationStatusMsg(instr_id, Status.NOT_FOUND)
        self._reserve_at_is()

    def _reserve_at_is(self):
        # pylint: disable=unused-argument
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.reserve_device_msg: Dataclass identifying the requesting app, host and user.
        """

    def _forward_reservation(self, success: Status):
        # pylint: disable=unused-argument
        """Create redirector.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        if success in [Status.OK, Status.OK_UPDATED, Status.OK_SKIPPED]:
            if Frontend.REST in frontend_config:
                # create redirector
                if not self._create_redirector():
                    logger.warning("Tried to create a redirector that already exists.")
            else:
                reservation = {
                    "Active": True,
                    "App": self.reserve_device_msg.app,
                    "Host": self.reserve_device_msg.host,
                    "User": self.reserve_device_msg.user,
                    "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
                self._update_reservation_status(reservation)
            return
        if success in [Status.NOT_FOUND, Status.IS_NOT_FOUND]:
            logger.error(
                "Reservation failed with %s. Removing device from list.", success
            )
            self.send(self.myAddress, KillMsg())
        elif success == Status.ERROR:
            logger.critical("%s during reservation", success)
            system_shutdown()
        self.return_message = (
            ReservationStatusMsg(instr_id=short_id(self.my_id), status=success),
        )
        self.send(self.sender_api, self.return_message)

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
        instr_id = short_id(self.my_id)
        try:
            assert msg.status in (Status.OK, Status.OK_SKIPPED)
        except AssertionError:
            self.send(
                self.sender_api, ReservationStatusMsg(instr_id, Status.UNKNOWN_PORT)
            )
            return
        # Write Reservation section into device status
        reservation = {
            "Active": True,
            "App": self.reserve_device_msg.app,
            "Host": self.reserve_device_msg.host,
            "User": self.reserve_device_msg.user,
            "IP": msg.ip_address,
            "Port": msg.port,
            "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        self._update_reservation_status(reservation)

    def _update_reservation_status(self, reservation):
        instr_id = short_id(self.my_id)
        self.device_status["Reservation"] = reservation
        logger.info("Reservation state updated: %s", self.device_status)
        self._publish_status_change()
        self.return_message = ReservationStatusMsg(instr_id, Status.OK)
        self.send(self.sender_api, self.return_message)
        self.return_message = None

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.sender_api = sender
        instr_id = short_id(self.my_id)
        status = Status.OK
        try:
            if self.device_status["Reservation"]["Active"]:
                logger.info("Free active %s", self.my_id)
                self.device_status["Reservation"]["Active"] = False
                if self.device_status["Reservation"].get("IP") is not None:
                    self.device_status["Reservation"].pop("IP")
                if self.device_status["Reservation"].get("Port") is not None:
                    self.device_status["Reservation"].pop("Port")
                self.device_status["Reservation"]["Timestamp"] = (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z"
                )
                status = Status.OK
            else:
                status = Status.OK_SKIPPED
        except KeyError:
            logger.debug("Instr. was not reserved before.")
            status = Status.OK_SKIPPED
        self._forward_to_children(KillMsg())
        self.return_message = ReservationStatusMsg(instr_id, status)
        if status == Status.OK:
            self._publish_status_change()
        if not self.child_actors:
            self.send(self.sender_api, self.return_message)
            self.return_message = None
        logger.info("Free %s", self.my_id)

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
        """Publish a device status to all members of device_actors."""
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

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if self.return_message is not None:
            self.send(self.sender_api, self.return_message)
            self.return_message = None

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self.return_message is not None:
            self.send(self.sender_api, self.return_message)
        super().receiveMsg_KillMsg(msg, sender)
