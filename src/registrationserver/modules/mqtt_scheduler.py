"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_scheduler.puml
"""
import json
from datetime import datetime

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import KeepAliveMsg, TxBinaryMsg
from registrationserver.config import ismqtt_config
from registrationserver.helpers import diff_of_dicts, get_key, short_id
from registrationserver.logger import logger
from registrationserver.modules import ismqtt_messages
from registrationserver.modules.mqtt.mqtt_base_actor import MqttBaseActor

logger.debug("%s -> %s", __package__, __file__)


class MqttSchedulerActor(MqttBaseActor):
    """Actor interacting with a new device"""

    MAX_RESERVE_TIME = 300

    @overrides
    def __init__(self):
        super().__init__()
        self.instr_id_actor_dict = {}  # {instr_id: device_actor}
        self.reservations = {}  # {instr_id: <reservation object>}
        # cmd_id to check the correct order of messages
        self.cmd_ids = {}  # {instr_id: <command id>}
        self.msg_id["PUBLISH"] = None
        self.is_id = ismqtt_config["IS_ID"]
        self.is_meta = ismqtt_messages.InstrumentServerMeta(
            state=0,
            host=self.is_id,
            description=ismqtt_config["DESCRIPTION"],
            place=ismqtt_config["PLACE"],
            latitude=ismqtt_config["LATITUDE"],
            longitude=ismqtt_config["LONGITUDE"],
            height=ismqtt_config["HEIGHT"],
        )

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add("+/+/control", self.on_control)
        self.mqttc.message_callback_add("+/+/cmd", self.on_cmd)
        self.mqttc.message_callback_add(f"{self.is_id}/+/meta", self.on_instr_meta)
        self.mqttc.will_set(
            retain=True,
            topic=f"{self.is_id}/meta",
            payload=ismqtt_messages.get_is_meta(self.is_meta),
        )
        self._subscribe_topic([(f"{self.is_id}/+/meta", 0)])
        self._subscribe_to_actor_dict_msg()

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        old_instr_id_actor_dict = self.instr_id_actor_dict
        self.instr_id_actor_dict = {
            short_id(device_id): dict["address"]
            for device_id, dict in self.actor_dict.items()
            if dict["is_device_actor"]
        }
        new_instruments = diff_of_dicts(
            self.instr_id_actor_dict, old_instr_id_actor_dict
        )
        logger.debug("New instruments %s", new_instruments)
        gone_instruments = diff_of_dicts(
            old_instr_id_actor_dict, self.instr_id_actor_dict
        )
        logger.debug("Gone instruments %s", gone_instruments)
        for address in new_instruments.values():
            self._subscribe_to_device_status_msg(address)
        for instr_id in gone_instruments:
            self._remove_instrument(instr_id)

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor.

        Adds a new instrument to the list of available instruments."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = short_id(msg.device_id)
        device_status = msg.device_status
        new_subscriptions = [
            (f"{self.is_id}/{instr_id}/control", 0),
            (f"{self.is_id}/{instr_id}/cmd", 0),
        ]
        self._subscribe_topic(new_subscriptions)
        identification = device_status["Identification"]
        message = {"State": 2, "Identification": identification}
        self.mqttc.publish(
            topic=f"{self.is_id}/{instr_id}/meta",
            payload=json.dumps(message),
            retain=True,
        )

    def _remove_instrument(self, instr_id):
        # pylint: disable=invalid-name
        """Removes an instrument from the list of available instruments."""
        logger.debug("Remove %s", instr_id)
        self.reservations.pop(instr_id, None)
        gone_subscriptions = [
            f"{self.is_id}/{instr_id}/control",
            f"{self.is_id}/{instr_id}/cmd",
        ]
        self._unsubscribe_topic(gone_subscriptions)
        self.mqttc.publish(
            retain=True,
            topic=f"{self.is_id}/{instr_id}/meta",
            payload=json.dumps({"State": 0}),
        )
        self.instr_id_actor_dict.pop(instr_id, None)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        to_remove = self.instr_id_actor_dict
        for instr_id in to_remove:
            self._remove_instrument(instr_id)
        self.mqttc.publish(
            retain=True, topic=f"{self.is_id}/meta", payload=json.dumps({"State": 0})
        )
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def on_connect(self, client, userdata, flags, result_code):
        """Will be carried out when the client connected to the MQTT broker."""
        super().on_connect(client, userdata, flags, result_code)
        self.mqttc.publish(
            retain=True,
            topic=f"{self.is_id}/meta",
            payload=ismqtt_messages.get_is_meta(self.is_meta._replace(state=2)),
        )

    def on_control(self, _client, _userdata, message):
        """Event handler for all MQTT messages with control topic."""
        logger.debug("[on_control] %s: %s", message.topic, message.payload)
        instrument_id = message.topic[: -len("control") - 1][len(self.is_id) + 1 :]
        if instrument_id in self.instr_id_actor_dict:
            old_control = self.reservations.get(instrument_id)
            control = ismqtt_messages.get_instr_control(message, old_control)
            logger.debug("Control object: %s", control)
            if control.ctype == ismqtt_messages.ControlType.RESERVE:
                self.process_reserve(instrument_id, control)
            if control.ctype == ismqtt_messages.ControlType.FREE:
                self.process_free(instrument_id)
                logger.debug(
                    "[FREE] client=%s, instr_id=%s, control=%s",
                    self.mqttc,
                    instrument_id,
                    control,
                )
        else:
            logger.error(
                "[on_control] The requested instrument %s is not connected",
                instrument_id,
            )

    def on_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic."""
        logger.debug("[on_cmd] %s: %s", message.topic, message.payload)
        instr_id = message.topic[: -len("cmd") - 1][len(self.is_id) + 1 :]
        self.cmd_ids[instr_id] = message.payload[0]
        cmd = message.payload[1:]
        device_actor = self.instr_id_actor_dict.get(instr_id)
        if device_actor is not None:
            logger.debug("Forward command %s to device actor %s", cmd, device_actor)
            self.send(device_actor, TxBinaryMsg(cmd))

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for actor messages returning from 'SEND" command

        Forward the payload received from device_actor via MQTT."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = get_key(sender, self.instr_id_actor_dict)
        reply = bytes([self.cmd_ids[instr_id]]) + msg.data
        self.mqttc.publish(f"{self.is_id}/{instr_id}/msg", reply)

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
        device_actor = self.instr_id_actor_dict.get(instr_id)
        if device_actor is not None:
            logger.debug("Send KeepAliveMsg to %s", device_actor)
            self.send(device_actor, KeepAliveMsg())
        success = False
        if not success and not self.reservations.get(instr_id, None):
            success = True
        if not success and (
            self.reservations[instr_id].host == control.data.host
            and self.reservations[instr_id].app == control.data.app
            and self.reservations[instr_id].user == control.data.user
        ):
            success = True
        if (
            not success
            and control.data.timestamp - self.reservations[instr_id].timestamp
            > self.MAX_RESERVE_TIME
        ):
            success = True
        if success:
            reservation = ismqtt_messages.Reservation(
                active=True,
                app=control.data.app,
                host=control.data.host,
                timestamp=control.data.timestamp,
                user=control.data.user,
            )
            self.reservations[instr_id] = reservation
            reservation_json = ismqtt_messages.get_instr_reservation(reservation)
            topic = f"{self.is_id}/{instr_id}/reservation"
            logger.debug("Publish %s on %s", reservation_json, topic)
            self.mqttc.publish(topic=topic, payload=reservation_json, retain=True)

    def process_free(self, instr_id):
        """Sub event handler that will be called from the on_message event handler,
        when a MQTT control message with a 'free' request was received
        for a specific instrument ID."""
        if self.reservations.get(instr_id) is None:
            logger.debug(
                "[FREE] Instrument is not in the list of reserved instruments."
            )
            return
        reservation = json.loads(
            ismqtt_messages.get_instr_reservation(self.reservations[instr_id])
        )
        reservation["Active"] = False
        reservation["Timestamp"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self.reservations[instr_id] = None
        self.mqttc.publish(
            topic=f"{self.is_id}/{instr_id}/reservation",
            payload=json.dumps(reservation),
            retain=True,
        )

    def on_instr_meta(self, _client, _userdata, message):
        """Handler for all messages of topic self.is_id/+/meta.
        This function and subscription was introduced to handle the very special case
        when a crashed Instr. Server leaves an active meta topic on the MQTT broker with
        its retain flag."""
        logger.debug("[on_instr_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[1]
        payload = json.loads(message.payload)
        if (instr_id not in self.instr_id_actor_dict) and (
            payload.get("State", 2) in (2, 1)
        ):
            self.mqttc.publish(
                retain=True,
                topic=f"{self.is_id}/{instr_id}/meta",
                payload=json.dumps({"State": 0}),
            )
