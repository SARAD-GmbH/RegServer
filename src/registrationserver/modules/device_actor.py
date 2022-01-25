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
from registrationserver.actor_messages import (AppType, ConnectMsg, KillMsg,
                                               RemoveDeviceMsg,
                                               ReservationStatusMsg, Status,
                                               SubscribeMsg,
                                               UpdateDeviceStatusMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.config import ismqtt_config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.redirect_actor import RedirectorActor
from thespian.actors import Actor  # type: ignore

logger.debug("%s -> %s", __package__, __file__)


class DeviceBaseActor(BaseActor):
    """Base class for protocol specific device actors.

    Implements all methods that all device actors have in common.
    Handles the following actor messages:

    * SetupMsg: is used to initialize the actor right after its creation.
      This is needed because some parts of the initialization cannot be done in
      __init__() (because for instance self.globalName is not available yet in
      __init__()), other initialization steps require data from the
      MdnsListener/MqttSubscriber creating the device actor. The same method is
      used for updates of the device state comming from the
      MdnsListener/MqttSubscriber.

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
        logger.debug("Initialize a new device actor.")
        super().__init__()
        self.device_status = {}
        self.my_redirector = None
        self.app = None
        self.user = None
        self.host = None
        self.sender_api = None
        self.mqtt_scheduler = None
        logger.info("Device actor created.")

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        if self.app_type == AppType.ISMQTT:
            # We trust in the existence of mqtt_scheduler, that was created by
            # the Registrar before the creation of any device actor.
            self.mqtt_scheduler = self.createActor(Actor, globalName="mqtt_scheduler")

    @overrides
    def _subscribe(self):
        """Subscribe at Registrar actor."""
        self.send(
            self.registrar,
            SubscribeMsg(
                actor_id=self.my_id,
                parent=self.parent.parent_address,
                is_device_actor=True,
                get_updates=False,
            ),
        )

    def receiveMsg_SetDeviceStatusMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg"""
        self.device_status = msg.device_status
        logger.debug("Device status: %s", self.device_status)
        if self.mqtt_scheduler is not None:
            self.device_status["Identification"]["Host"] = ismqtt_config["IS_ID"]
            self.send(
                self.mqtt_scheduler,
                UpdateDeviceStatusMsg(short_id(self.my_id), self.device_status),
            )

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        logger.info("%s for actor %s", msg, self.my_id)
        # Send 'REMOVE' message to MQTT Scheduler
        if self.app_type == AppType.ISMQTT:
            self.send(self.mqtt_scheduler, RemoveDeviceMsg(short_id(self.my_id)))
        super().receiveMsg_KillMsg(msg, sender)

    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReserveDeviceMsg from REST API."""
        logger.info("Device actor received a ReserveDeviceMsg with message: %s", msg)
        self.sender_api = sender
        self.app = msg.app
        self.host = msg.host
        self.user = msg.user
        if self.app_type == AppType.RS:
            try:
                if self.device_status["Reservation"]["Active"]:
                    if self.device_status["Reservation"]["Host"] == self.host:
                        return_message = ReservationStatusMsg(Status.OK_UPDATED)
                    else:
                        return_message = ReservationStatusMsg(Status.OCCUPIED)
                    self.send(self.sender_api, return_message)
                    return
            except KeyError:
                logger.debug("First reservation since restart of RegServer")
            self._reserve_at_is()
        return

    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.app: String identifying the requesting app.
            self.host: String identifying the host running the app.
            self.user: String identifying the user of the app.
            self.sender_api: The actor object asking for reservation.
        """

    def _forward_reservation(self, success: bool):
        # pylint: disable=unused-argument, no-self-use
        """Forward the reply from the Instrument Server to the redirector actor.
        This function has to be called in the protocol specific modules.
        """
        if success:
            if self._create_redirector():
                return
            self.send(self.sender_api, ReservationStatusMsg(Status.OK))
        else:
            self.send(self.sender_api, ReservationStatusMsg(Status.OCCUPIED))

    def _create_redirector(self) -> bool:
        """Create redirector actor if it does not exist already"""
        if self.my_redirector is None:
            self.my_redirector = self._create_actor(
                RedirectorActor, short_id(self.my_id)
            )
            return True
        logger.debug(
            "[create_redirector] Redirector %s already exists.", self.my_redirector
        )
        return False

    def receiveMsg_SocketMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SocketMsg from Redirector Actor."""
        logger.debug("Redirector returned with %s", msg)
        try:
            assert msg.status in (Status.OK, Status.OK_SKIPPED)
        except AssertionError:
            self.send(self.sender_api, ReservationStatusMsg(Status.UNKNOWN_PORT))
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
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)
        self.send(self.my_redirector, ConnectMsg())
        self.send(self.sender_api, ReservationStatusMsg(Status.OK))

    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for FreeDeviceMsg from REST API."""
        logger.info("Device actor received a FreeDeviceMsg from API. %s", msg)
        self.sender_api = sender
        try:
            if self.device_status["Reservation"]["Active"]:
                self.device_status["Reservation"]["Active"] = False
                self.device_status["Reservation"].pop("IP")
                self.device_status["Reservation"].pop("Port")
                self.device_status["Reservation"]["Timestamp"] = (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z"
                )
                return_message = ReservationStatusMsg(Status.OK)
            else:
                return_message = ReservationStatusMsg(Status.OK_SKIPPED)
        except KeyError:
            logger.debug("Instr. was not reserved before.")
            return_message = ReservationStatusMsg(Status.OK_SKIPPED)
        self.send(self.sender_api, return_message)
        if self.my_redirector is not None:
            logger.debug("Kill redirector %s", self.my_redirector)
            self.send(self.my_redirector, KillMsg())

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        # pylint: disable=invalid-name
        """Change the device status to Free after receiving the confirmation
        that the redirector exited."""
        reservation = {
            "Active": False,
            "App": self.device_status["Reservation"]["App"],
            "Host": self.device_status["Reservation"]["Host"],
            "User": self.device_status["Reservation"]["User"],
            "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        logger.info("[Free] %s", reservation)
        self.device_status["Reservation"] = reservation
        self.my_redirector = None

    def receiveMsg_GetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetDeviceStatusMsg asking to send updated information
        about the device status to the sender.

        Sends back a message containing the device_status."""
        self.send(
            sender, UpdateDeviceStatusMsg(short_id(self.my_id), self.device_status)
        )
