"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import json
import time

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (FreeDeviceMsg, ReserveDeviceMsg,
                                               Status, TxBinaryMsg)
from registrationserver.config import config, get_hostname, get_ip
from registrationserver.helpers import diff_of_dicts, short_id
from registrationserver.logger import logger
from registrationserver.modules.backend.mqtt.mqtt_base_actor import \
    MqttBaseActor
from registrationserver.modules.ismqtt_messages import (ControlType,
                                                        InstrumentServerMeta,
                                                        Reservation,
                                                        get_instr_control,
                                                        get_instr_reservation,
                                                        get_is_meta)

# logger.debug("%s -> %s", __package__, __file__)


class MqttSchedulerActor(MqttBaseActor):
    """Actor interacting with a new device"""

    MAX_RESERVE_TIME = 300

    @staticmethod
    def _active_device_actors(actor_dict):
        """Extract only active device actors from actor_dict"""
        active_device_actor_dict = {}
        for actor_id, description in actor_dict.items():
            if description["is_device_actor"]:
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
            host=self.is_id,
            description=config["DESCRIPTION"],
            place=config["PLACE"],
            latitude=config["LATITUDE"],
            longitude=config["LONGITUDE"],
            height=config["HEIGHT"],
        )
        self.pending_control_action = ControlType.UNKNOWN

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add(f"{self.group}/+/+/control", self.on_control)
        self.mqttc.message_callback_add(f"{self.group}/+/+/cmd", self.on_cmd)
        self.mqttc.message_callback_add(
            f"{self.group}/{self.is_id}/+/meta", self.on_instr_meta
        )
        self.mqttc.will_set(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=get_is_meta(self.is_meta._replace(state=0)),
        )
        if self._connect(self.mqtt_broker, self.port):
            self.mqttc.loop_start()

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

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor.

        Adds a new instrument to the list of available instruments."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = short_id(msg.device_id)
        device_id = msg.device_id
        device_status = msg.device_status
        if device_id not in self.reservations:
            logger.debug("Publish %s as new instrument.", instr_id)
            new_subscriptions = [
                (f"{self.group}/{self.is_id}/{instr_id}/control", 0),
                (f"{self.group}/{self.is_id}/{instr_id}/cmd", 0),
            ]
            self._subscribe_topic(new_subscriptions)
            identification = device_status["Identification"]
            identification["Host"] = get_hostname(get_ip(False))
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
        self.reservations[device_id] = reservation_object
        if self.pending_control_action == ControlType.RESERVE:
            logger.debug("Publish reservation")
            if reservation_object.status in (
                Status.OK,
                Status.OK_SKIPPED,
                Status.OK_UPDATED,
            ):
                reservation_object._replace(active=True)
                self.reservations[device_id] = reservation_object
                reservation_json = get_instr_reservation(reservation_object)
                topic = f"{self.group}/{self.is_id}/{instr_id}/reservation"
                logger.debug("Publish %s on %s", reservation_json, topic)
                self.mqttc.publish(topic=topic, payload=reservation_json, retain=True)
        elif self.pending_control_action == ControlType.FREE:
            if self.reservations.get(device_id) is None:
                logger.debug(
                    "[FREE] Instrument is not in the list of reserved instruments."
                )
                reservation_object.status = Status.OK_SKIPPED
            logger.debug("Publish free status")
            if reservation_object.status in (
                Status.OK,
                Status.OK_SKIPPED,
                Status.OK_UPDATED,
            ):
                reservation_object._replace(active=False)
                self.mqttc.publish(
                    topic=f"{self.group}/{self.is_id}/{instr_id}/reservation",
                    payload=get_instr_reservation(reservation_object),
                    retain=True,
                )
        self.pending_control_action = ControlType.UNKNOWN

    def _remove_instrument(self, device_id):
        # pylint: disable=invalid-name
        """Removes an instrument from the list of available instruments."""
        logger.debug("Remove %s", device_id)
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

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        for actor_id, description in self.actor_dict.items():
            if description["is_device_actor"]:
                self._remove_instrument(actor_id)
        self.mqttc.publish(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=json.dumps({"State": 0}),
        )
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def on_connect(self, client, userdata, flags, result_code):
        """Will be carried out when the client connected to the MQTT broker."""
        super().on_connect(client, userdata, flags, result_code)
        self.mqttc.publish(
            retain=True,
            topic=f"{self.group}/{self.is_id}/meta",
            payload=get_is_meta(self.is_meta._replace(state=2)),
        )
        self._subscribe_topic([(f"{self.group}/{self.is_id}/+/meta", 0)])
        self._subscribe_to_actor_dict_msg()
        for actor_id, description in self.actor_dict.items():
            if description["is_device_actor"]:
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
        """Event handler for all MQTT messages with cmd topic."""
        logger.debug("[on_cmd] %s: %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        self.cmd_ids[instr_id] = message.payload[0]
        cmd = message.payload[1:]
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            logger.debug("Forward %s to %s", cmd, instr_id)
            self.send(device_actor, TxBinaryMsg(cmd))

    def receiveMsg_ReservationStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ReservationStatusMsg coming back from Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        _device_actor, device_id = self._device_actor(msg.instr_id)
        reservation = self.reservations.get(device_id)
        if reservation is not None:
            self.reservations[device_id]._replace(status=msg.status)
        else:
            self.reservations[device_id] = Reservation(
                status=msg.status, timestamp=time.time()
            )

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
            if description["is_device_actor"]:
                if instr_id == short_id(actor_id):
                    return (description["address"], actor_id)
        return (None, "")
