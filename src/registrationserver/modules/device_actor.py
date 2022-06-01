"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-device_actor.puml
"""
from datetime import datetime

import registrationserver.config as configuration
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (Frontend, KillMsg,
                                               ReservationStatusMsg, Status,
                                               UpdateDeviceStatusMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.redirect_actor import RedirectorActor
from registrationserver.shutdown import system_shutdown

logger.debug("%s -> %s", __package__, __file__)


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
        self.app = None
        self.user = None
        self.host = None
        self.sender_api = None
        self.is_device_actor = True
        self.redirector_actor = None

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_status = msg.device_status
        logger.debug("Device status: %s", self.device_status)
        if Frontend.MQTT in configuration.frontend_config:
            self.device_status["Identification"]["Host"] = configuration.config["IS_ID"]
        self._publish_status_change()

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.sender_api = sender
        self.app = msg.app
        self.host = msg.host
        self.user = msg.user
        instr_id = short_id(self.my_id)
        try:
            if self.device_status["Reservation"]["Active"]:
                if self.device_status["Reservation"]["Host"] == self.host:
                    return_message = ReservationStatusMsg(instr_id, Status.OK_UPDATED)
                else:
                    return_message = ReservationStatusMsg(instr_id, Status.OCCUPIED)
                self.send(self.sender_api, return_message)
                return
        except KeyError:
            logger.debug("First reservation since restart of RegServer")
        self._reserve_at_is()

    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.app: String identifying the requesting app.
            self.host: String identifying the host running the app.
            self.user: String identifying the user of the app.
        """

    def _forward_reservation(self, success: Status):
        # pylint: disable=unused-argument, no-self-use
        """Create redirector.
        Forward the reservation state from the Instrument Server to the REST API.
        This function has to be called in the protocol specific modules.
        """
        if success in [Status.OK, Status.OK_UPDATED, Status.OK_SKIPPED]:
            if Frontend.REST in configuration.frontend_config:
                # create redirector
                if not self._create_redirector():
                    logger.warning("Tried to create a redirector that already exists.")
            else:
                reservation = {
                    "Active": True,
                    "App": self.app,
                    "Host": self.host,
                    "User": self.user,
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
        self.send(
            self.sender_api,
            ReservationStatusMsg(instr_id=short_id(self.my_id), status=success),
        )

    def _create_redirector(self) -> bool:
        """Create redirector actor if it does not exist already"""
        if not self.child_actors:
            self._create_actor(RedirectorActor, short_id(self.my_id))
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
            "App": self.app,
            "Host": self.host,
            "User": self.user,
            "IP": msg.ip_address,
            "Port": msg.port,
            "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        self._update_reservation_status(reservation)

    def _update_reservation_status(self, reservation):
        instr_id = short_id(self.my_id)
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)
        self.send(self.sender_api, ReservationStatusMsg(instr_id, Status.OK))
        self._publish_status_change()

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.sender_api = sender
        instr_id = short_id(self.my_id)
        try:
            if self.device_status["Reservation"]["Active"]:
                self.device_status["Reservation"]["Active"] = False
                if self.device_status["Reservation"].get("IP") is not None:
                    self.device_status["Reservation"].pop("IP")
                if self.device_status["Reservation"].get("Port") is not None:
                    self.device_status["Reservation"].pop("Port")
                self.device_status["Reservation"]["Timestamp"] = (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z"
                )
                return_message = ReservationStatusMsg(instr_id, Status.OK)
            else:
                return_message = ReservationStatusMsg(instr_id, Status.OK_SKIPPED)
        except KeyError:
            logger.debug("Instr. was not reserved before.")
            return_message = ReservationStatusMsg(instr_id, Status.OK_SKIPPED)
        self.send(self.sender_api, return_message)
        self._forward_to_children(KillMsg())
        self._publish_status_change()

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
            self._publish_status_change()

    def _publish_status_change(self):
        """Publish a changed device status to all subscribers."""
        for actor_address in self.subscribers.values():
            self.send(
                actor_address,
                UpdateDeviceStatusMsg(self.my_id, self.device_status),
            )

    def receiveMsg_TxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.redirector_actor = sender
