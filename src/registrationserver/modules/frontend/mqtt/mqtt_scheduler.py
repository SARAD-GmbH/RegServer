"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import json
import os
import time

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ActorType, FreeDeviceMsg,
                                               RescanMsg, ReserveDeviceMsg,
                                               ShutdownMsg, Status,
                                               TxBinaryMsg)
from registrationserver.config import config
from registrationserver.helpers import (diff_of_dicts, short_id,
                                        transport_technology)
from registrationserver.logger import logger
from registrationserver.modules.backend.mqtt.mqtt_base_actor import \
    MqttBaseActor
from registrationserver.modules.ismqtt_messages import (ControlType,
                                                        InstrumentServerMeta,
                                                        Reservation,
                                                        get_instr_control,
                                                        get_instr_reservation,
                                                        get_is_meta)

if os.name != "nt":
    from gpiozero import PWMLED  # type: ignore
    from gpiozero.exc import BadPinFactory  # type: ignore


class MqttSchedulerActor(MqttBaseActor):
    """Actor interacting with a new device"""

    MAX_RESERVE_TIME = 300

    @staticmethod
    def _active_device_actors(actor_dict):
        """Extract only active device actors from actor_dict"""
        active_device_actor_dict = {}
        for actor_id, description in actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                active_device_actor_dict[actor_id] = description
        return active_device_actor_dict

    @overrides
    def __init__(self):
        super().__init__()
        self.reservations = {}  # {device_id: <reservation object>}
        # cmd_id to check the correct order of messages
        self.cmd_ids = {}  # {instr_id: <command id>}
        self.msg_id["PUBLISH"] = None
        self.is_id = config["IS_ID"]
        self.is_meta = InstrumentServerMeta(
            state=0,
            host=config["MY_HOSTNAME"],
            is_id=self.is_id,
            description=config["DESCRIPTION"],
            place=config["PLACE"],
            latitude=config["LATITUDE"],
            longitude=config["LONGITUDE"],
            height=config["HEIGHT"],
        )
        self.pending_control_action = ControlType.UNKNOWN
        if os.name != "nt":
            try:
                self.led = PWMLED(23)
                self.led.pulse()
            except BadPinFactory:
                logger.info(
                    "On a Raspberry Pi, you could see a LED pulsing on GPIO 23."
                )
                self.led = False
        else:
            self.led = False

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add(f"{self.group}/+/+/control", self.on_control)
        self.mqttc.message_callback_add(
            f"{self.group}/{self.is_id}/cmd", self.on_host_cmd
        )
        self.mqttc.message_callback_add(f"{self.group}/{self.is_id}/+/cmd", self.on_cmd)
        self.mqttc.message_callback_add(
            f"{self.group}/{self.is_id}/+/meta", self.on_instr_meta
        )
        self.mqttc.will_set(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=get_is_meta(self.is_meta._replace(state=10)),
        )

    @overrides
    def _connected(self):
        super()._connected()
        self._subscribe_topic([(f"{self.group}/{self.is_id}/*/reservation", 0)])

    @overrides
    def on_disconnect(self, client, userdata, reason_code):
        super().on_disconnect(client, userdata, reason_code)
        if self.led:
            self.led.pulse()

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        if not self.is_connected:
            return
        old_actor_dict = self._active_device_actors(self.actor_dict)
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        new_actor_dict = self._active_device_actors(self.actor_dict)
        new_device_actors = diff_of_dicts(new_actor_dict, old_actor_dict)
        logger.debug("New device actors %s", new_device_actors)
        gone_device_actors = diff_of_dicts(old_actor_dict, new_actor_dict)
        logger.debug("Gone device actors %s", gone_device_actors)
        for actor_id, description in new_device_actors.items():
            self._subscribe_to_device_status_msg(description["address"])
        for actor_id in gone_device_actors:
            self._remove_instrument(actor_id)

    def receiveMsg_ReservationStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReservationStatusMsg from Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        _device_actor, device_id = self._device_actor(msg.instr_id)
        reservation = self.reservations.get(device_id)
        if reservation is not None:
            self.reservations[device_id]._replace(status=msg.status)
        else:
            self.reservations[device_id] = Reservation(
                status=msg.status, timestamp=time.time()
            )
        reservation_object = self.reservations[device_id]
        if self.pending_control_action in (ControlType.RESERVE, ControlType.FREE):
            logger.debug("Publish reservation state")
            if reservation_object.status in (
                Status.OK,
                Status.OK_SKIPPED,
                Status.OK_UPDATED,
            ):
                if self.pending_control_action == ControlType.RESERVE:
                    reservation_object._replace(active=True)
                else:
                    reservation_object._replace(active=False)
            self.reservations[device_id] = reservation_object
            reservation_json = get_instr_reservation(reservation_object)
            topic = f"{self.group}/{self.is_id}/{msg.instr_id}/reservation"
            logger.debug("Publish %s on %s", reservation_json, topic)
            self.mqttc.publish(topic=topic, payload=reservation_json, retain=True)
            self.pending_control_action = ControlType.UNKNOWN

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name, too-many-locals
        """Handler for UpdateDeviceStatusMsg from Device Actor.

        Adds a new instrument to the list of available instruments
        or updates the reservation state."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if transport_technology(msg.device_id) == "mqtt":
            return
        instr_id = short_id(msg.device_id)
        device_id = msg.device_id
        device_status = msg.device_status
        new_instrument_connected = False
        if not device_status.get("State", 2) < 2:
            if device_id not in self.reservations:
                logger.debug("Publish %s as new instrument.", instr_id)
                new_instrument_connected = True
                new_subscriptions = [
                    (f"{self.group}/{self.is_id}/{instr_id}/control", 0),
                    (f"{self.group}/{self.is_id}/{instr_id}/cmd", 0),
                ]
                self._subscribe_topic(new_subscriptions)
                identification = device_status["Identification"]
                identification["Host"] = self.is_meta.host
                message = {"State": 2, "Identification": identification}
                self.mqttc.publish(
                    topic=f"{self.group}/{self.is_id}/{instr_id}/meta",
                    payload=json.dumps(message),
                    retain=True,
                )
            reservation = device_status.get("Reservation")
            if reservation is None:
                logger.debug("%s has never been reserved.", instr_id)
                self.reservations[device_id] = Reservation(
                    status=Status.OK_SKIPPED, timestamp=time.time()
                )
                reservation = {"Active": False}
            saved_reservation_object = self.reservations.get(device_id)
            if saved_reservation_object is not None:
                status = saved_reservation_object.status
            else:
                status = Status.OK
            reservation_object = Reservation(
                timestamp=time.time(),
                active=reservation.get("Active", False),
                host=reservation.get("Host", ""),
                app=reservation.get("App", ""),
                user=reservation.get("User", ""),
                status=status,
            )
            if (
                not (self.reservations[device_id] == reservation_object)
                or new_instrument_connected
            ):
                self.reservations[device_id] = reservation_object
                reservation_json = get_instr_reservation(reservation_object)
                topic = f"{self.group}/{self.is_id}/{instr_id}/reservation"
                logger.info("Publish %s on %s", reservation_json, topic)
                self.mqttc.publish(topic=topic, payload=reservation_json, retain=True)
                self._instruments_connected()

    def _instruments_connected(self):
        """Check whether there are connected instruments"""
        topic = f"{self.group}/{self.is_id}/meta"
        if self.reservations:
            payload = get_is_meta(self.is_meta._replace(state=2))
        else:
            payload = get_is_meta(self.is_meta._replace(state=1))
        self.mqttc.publish(
            retain=True,
            topic=topic,
            payload=payload,
        )
        logger.info("Publish %s on %s", payload, topic)

    def _remove_instrument(self, device_id):
        # pylint: disable=invalid-name
        """Removes an instrument from the list of available instruments."""
        logger.info("Remove %s", device_id)
        if self.reservations.pop(device_id, None) is not None:
            instr_id = short_id(device_id)
            gone_subscriptions = [
                f"{self.group}/{self.is_id}/{instr_id}/control",
                f"{self.group}/{self.is_id}/{instr_id}/cmd",
            ]
            self._unsubscribe_topic(gone_subscriptions)
            self.mqttc.publish(
                retain=True,
                topic=f"{self.group}/{self.is_id}/{instr_id}/meta",
                payload=json.dumps({"State": 0}),
            )
        self._instruments_connected()

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        for actor_id, description in self.actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                self._remove_instrument(actor_id)
        self.mqttc.publish(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=json.dumps({"State": 0}),
        )
        if self.led and not self.led.closed:
            self.led.close()
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def on_connect(self, client, userdata, flags, reason_code):
        """Will be carried out when the client connected to the MQTT broker."""
        super().on_connect(client, userdata, flags, reason_code)
        if self.led:
            self.led.on()
        self.mqttc.publish(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=get_is_meta(self.is_meta._replace(state=1)),
        )
        self._subscribe_topic([(f"{self.group}/{self.is_id}/+/meta", 0)])
        self._subscribe_topic([(f"{self.group}/{self.is_id}/cmd", 0)])
        self._subscribe_to_actor_dict_msg()
        for actor_id, description in self.actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                self.process_free(short_id(actor_id))

    def on_control(self, _client, _userdata, message):
        """Event handler for all MQTT messages with control topic."""
        logger.debug("[on_control] %s: %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        device_actor, device_id = self._device_actor(instr_id)
        if device_actor is not None:
            old_control = self.reservations.get(device_id)
            control = get_instr_control(message, old_control)
            logger.debug("Control object: %s", control)
            self.pending_control_action = control.ctype
            if control.ctype == ControlType.RESERVE:
                self.process_reserve(instr_id, control)
            if control.ctype == ControlType.FREE:
                self.process_free(instr_id)
                logger.debug(
                    "[FREE] client=%s, instr_id=%s, control=%s",
                    self.mqttc,
                    instr_id,
                    control,
                )

    def on_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic for instruments."""
        logger.debug("[on_cmd] %s: %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        self.cmd_ids[instr_id] = message.payload[0]
        cmd = message.payload[1:]
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            logger.debug("Forward %s to %s", cmd, instr_id)
            self.send(device_actor, TxBinaryMsg(cmd))

    def on_host_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic for the host."""
        logger.debug("[on_host_cmd] %s: %s", message.topic, message.payload)
        if message.payload.decode("utf-8") == "scan":
            self.send(self.registrar, RescanMsg())
        elif message.payload.decode("utf-8") == "shutdown":
            self.send(self.registrar, ShutdownMsg())

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for actor messages returning from 'SEND" command

        Forward the payload received from device_actor via MQTT."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for actor_id, description in self.actor_dict.items():
            if description["address"] == sender:
                instr_id = short_id(actor_id)
                reply = bytes([self.cmd_ids[instr_id]]) + msg.data
                self.mqttc.publish(f"{self.group}/{self.is_id}/{instr_id}/msg", reply)

    def process_reserve(self, instr_id, control):
        """Sub event handler that will be called from the on_message event handler,
        when a MQTT control message with a 'reserve' request was received
        for a specific instrument ID."""
        logger.debug(
            "[RESERVE] client=%s, instr_id=%s, control=%s",
            self.mqttc,
            instr_id,
            control,
        )
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(
                device_actor,
                ReserveDeviceMsg(
                    host=control.data.host, user=control.data.user, app=control.data.app
                ),
            )

    def process_free(self, instr_id):
        """Sub event handler that will be called from the on_message event handler,
        when a MQTT control message with a 'free' request was received
        for a specific instrument ID."""
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, FreeDeviceMsg())

    def on_instr_meta(self, _client, _userdata, message):
        """Handler for all messages of topic self.is_id/+/meta.
        This function and subscription was introduced to handle the very special case
        when a crashed Instr. Server leaves an active meta topic on the MQTT broker with
        its retain flag."""
        logger.debug("[on_instr_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        payload = json.loads(message.payload)
        device_actor, _device_id = self._device_actor(instr_id)
        if (device_actor is None) and (payload.get("State", 2) in (2, 1)):
            self.mqttc.publish(
                retain=True,
                topic=f"{self.group}/{self.is_id}/{instr_id}/meta",
                payload=json.dumps({"State": 0}),
            )

    def _device_actor(self, instr_id):
        """Get device actor address and device_id from instr_id"""
        for actor_id, description in self.actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                if instr_id == short_id(actor_id):
                    return (description["address"], actor_id)
        return (None, "")

    def receiveMsg_RescanFinishedMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RescanFinishedMsg from Registrar.

        Does nothing else then putting a debug log entry."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)

    def receiveMsg_ShutdownFinishedMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ShutdownFinishedMsg from Registrar.

        Does nothing else then putting a debug log entry."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
