"""MQTT Scheduler Actor for Instrument Server MQTT

Created
    2021-10-29

Author
    Michael Strey <strey@sarad.de>

"""

import json
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Thread

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, FreeDeviceMsg,
                                      GetDeviceStatusesMsg, GetRecentValueMsg,
                                      RescanMsg, ReserveDeviceMsg, SetRtcMsg,
                                      ShutdownMsg, StartMonitoringMsg, Status,
                                      StopMonitoringMsg, TxBinaryMsg)
from regserver.config import config
from regserver.helpers import (diff_of_dicts, get_sarad_type, short_id,
                               transport_technology)
from regserver.logger import logger
from regserver.modules.backend.mqtt.mqtt_base_actor import MqttBaseActor
from regserver.modules.ismqtt_messages import (Control, ControlType,
                                               InstrumentServerMeta,
                                               Reservation, get_instr_control,
                                               get_instr_reservation,
                                               get_is_meta)
from regserver.version import VERSION

if os.name != "nt":
    from gpiozero import PWMLED  # type: ignore
    from gpiozero.exc import BadPinFactory, GPIOPinInUse  # type: ignore


class MqttSchedulerActor(MqttBaseActor):
    """Actor interacting with a new device"""

    MAX_RESERVE_TIME = 300

    @staticmethod
    def _active_device_actors(actor_dict):
        """Extract only active device actors from actor_dict"""
        active_device_actor_dict = {}
        for actor_id, description in actor_dict.items():
            if (description["actor_type"] == ActorType.DEVICE) and (
                transport_technology(actor_id) not in ("mqtt", "mdns")
            ):
                active_device_actor_dict[actor_id] = description
        return active_device_actor_dict

    @overrides
    def __init__(self):
        super().__init__()
        self.reservations = {}  # {device_id: <reservation object>}
        # cmd_id to check the correct order of messages
        self.cmd_ids = {}  # {instr_id: <command id>}
        self.is_meta = InstrumentServerMeta(
            state=0,
            host=config["MY_HOSTNAME"],
            is_id=config["IS_ID"],
            description=config["DESCRIPTION"],
            place=config["PLACE"],
            latitude=config["LATITUDE"],
            longitude=config["LONGITUDE"],
            altitude=config["ALTITUDE"],
            version=VERSION,
            running_since=datetime.now(timezone.utc).replace(microsecond=0),
        )
        self.pending_control_action = {
            "instr_id": "",
            "control": Control(ctype=ControlType.UNKNOWN, data=None),
            "ctype": ControlType.UNKNOWN,
        }
        if os.name != "nt":
            try:
                self.led = PWMLED(23)
                self.led.pulse()
            except (BadPinFactory, GPIOPinInUse):
                logger.info(
                    "On a Raspberry Pi, you could see a LED pulsing on GPIO 23."
                )
                self.led = False
        else:
            self.led = False
        self.last_update = datetime(year=1970, month=1, day=1)
        self.buy_ahead = b""
        self.cached_reply = b""
        self.first_get_next = False
        self.inner_thread: Thread = Thread(
            target=None,
            kwargs={},
            daemon=True,
        )

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        # callbacks for host
        self.mqttc.message_callback_add(f"{self.group}/+/meta", self.on_is_meta)
        self.mqttc.message_callback_add(
            f"{self.group}/{msg.client_id}/cmd", self.on_host_cmd
        )
        # callbacks for instrument
        self.mqttc.message_callback_add(
            f"{self.group}/{msg.client_id}/+/meta", self.on_instr_meta
        )
        self.mqttc.message_callback_add(f"{self.group}/+/+/control", self.on_control)
        self.mqttc.message_callback_add(
            f"{self.group}/{msg.client_id}/+/cmd", self.on_cmd
        )
        # last will and testament
        self.mqttc.will_set(
            topic=f"{self.group}/{msg.client_id}/meta",
            payload=get_is_meta(replace(self.is_meta, state=10)),
            qos=2,
            retain=True,
        )

    @overrides
    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        # pylint: disable=too-many-arguments
        super().on_disconnect(client, userdata, flags, reason_code, properties)
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
            if transport_technology(actor_id) not in ("mqtt", "mdns"):
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
            self.reservations[device_id] = replace(
                self.reservations[device_id], status=msg.status
            )
        else:
            self.reservations[device_id] = Reservation(
                status=msg.status, timestamp=time.time()
            )
        reservation_object = self.reservations[device_id]
        if self.pending_control_action["ctype"] in (
            ControlType.RESERVE,
            ControlType.FREE,
        ):
            logger.debug("Publish reservation state")
            if reservation_object.status in (
                Status.OK,
                Status.OK_SKIPPED,
                Status.OK_UPDATED,
            ):
                if self.pending_control_action["ctype"] == ControlType.RESERVE:
                    reservation_object = replace(reservation_object, active=True)
                else:
                    reservation_object = replace(reservation_object, active=False)
            self.reservations[device_id] = reservation_object
            reservation_json = get_instr_reservation(reservation_object)
            topic = f"{self.group}/{self.is_id}/{msg.instr_id}/reservation"
            logger.debug("Publish %s on %s", reservation_json, topic)
            self.mqttc.publish(
                topic=topic, payload=reservation_json, qos=self.qos, retain=False
            )
            self.pending_control_action["ctype"] = ControlType.UNKNOWN

    def receiveMsg_RecentValueMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RecentValueMsg from Device Actor.

        This message contains the reply to GetRecentValueMsg."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if self.pending_control_action["ctype"] == ControlType.VALUE:
            topic = f"{self.group}/{self.is_id}/{msg.instr_id}/value"
            if (msg.gps is None) or (not msg.gps.valid):
                gps_dict = None
            else:
                gps_dict = {
                    "valid": msg.gps.valid,
                    "lat": msg.gps.latitude,
                    "lon": msg.gps.longitude,
                    "alt": msg.gps.altitude,
                    "dev": msg.gps.deviation,
                }
            payload = {
                "status": msg.status.value,
                "client": self.pending_control_action["control"].data.client,
                "c_name": msg.component_name,
                "s_name": msg.sensor_name,
                "m_name": msg.measurand_name,
                "measurand": msg.measurand,
                "operator": msg.operator,
                "value": msg.value,
                "unit": msg.unit,
                "time": msg.timestamp,
                "utc_offset": msg.utc_offset,
                "interval": msg.sample_interval,
                "gps": gps_dict,
            }
            logger.debug("Publish %s on %s", payload, topic)
            self.mqttc.publish(
                topic=topic, payload=json.dumps(payload), qos=self.qos, retain=False
            )
            self.pending_control_action["ctype"] = ControlType.UNKNOWN

    def receiveMsg_UpdateDeviceStatusesMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusesMsg from Device Actor.

        Receives a dict of all device_statuses and publishes meta information
        for every instrument in a meta topic."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for device_id, status_dict in msg.device_statuses.items():
            if transport_technology(device_id) in ("mqtt", "mdns"):
                continue
            topic = f"{self.group}/{self.is_id}/{short_id(device_id)}/meta"
            try:
                status_dict["Identification"]["Host"] = self.is_meta.host
                self.mqttc.publish(
                    topic=topic,
                    payload=json.dumps(status_dict),
                    qos=self.qos,
                    retain=False,
                )
            except KeyError as exception:
                logger.warning("No host information for %s: %s", device_id, exception)

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name, too-many-locals
        """Handler for UpdateDeviceStatusMsg from Device Actor.

        Adds a new instrument to the list of available instruments
        or updates the reservation state."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if transport_technology(msg.device_id) in ("mqtt", "mdns"):
            return
        instr_id = short_id(msg.device_id)
        device_id = msg.device_id
        device_status = msg.device_status
        new_instrument_connected = False
        if not device_status.get("State", 2) < 2:
            reservation = device_status.get("Reservation")
            if device_id not in self.reservations:
                logger.debug("Publish %s as new instrument.", instr_id)
                new_instrument_connected = True
                self.mqttc.subscribe(f"{self.group}/{self.is_id}/{instr_id}/control", 2)
                self.mqttc.subscribe(f"{self.group}/{self.is_id}/{instr_id}/cmd", 2)
                identification = device_status["Identification"]
                identification["Host"] = self.is_meta.host
                message = {"State": 2, "Identification": identification}
                self.mqttc.publish(
                    topic=f"{self.group}/{self.is_id}/{instr_id}/meta",
                    payload=json.dumps(message),
                    qos=self.qos,
                    retain=False,
                )
                if reservation is None:
                    logger.debug("%s has never been reserved.", instr_id)
                    self.reservations[device_id] = Reservation(
                        status=Status.OK_SKIPPED, timestamp=time.time()
                    )
                    reservation = {"Active": False}
                else:
                    self.reservations[device_id] = Reservation(
                        timestamp=time.time(),
                        active=reservation.get("Active", False),
                        host=reservation.get("Host", ""),
                        app=reservation.get("App", ""),
                        user=reservation.get("User", ""),
                        status=Status.OK,
                    )
            saved_reservation_object = self.reservations.get(device_id)
            if saved_reservation_object is not None:
                status = saved_reservation_object.status
            else:
                status = Status.OK
            try:
                reservation_object = Reservation(
                    timestamp=time.time(),
                    active=reservation.get("Active", False),
                    host=reservation.get("Host", ""),
                    app=reservation.get("App", ""),
                    user=reservation.get("User", ""),
                    status=status,
                )
            except AttributeError:
                reservation_object = Reservation(
                    timestamp=time.time(),
                    active=False,
                    host="",
                    app="",
                    user="",
                    status=status,
                )
            if (
                not (self.reservations[device_id] == reservation_object)
                or new_instrument_connected
            ):
                self.reservations[device_id] = reservation_object
                reservation_json = get_instr_reservation(reservation_object)
                topic = f"{self.group}/{self.is_id}/{instr_id}/reservation"
                logger.debug("Publish %s on %s", reservation_json, topic)
                self.mqttc.publish(
                    topic=topic, payload=reservation_json, qos=self.qos, retain=False
                )
                if new_instrument_connected and (self.is_meta.state < 2):
                    self._instruments_connected()

    def _instruments_connected(self):
        """Check whether there are connected instruments"""
        topic = f"{self.group}/{self.is_id}/meta"
        old_state = self.is_meta.state
        if self.reservations:
            new_state = 2
            if self.led and self.is_connected:
                self.led.on()
        else:
            new_state = 1
            if self.led:
                self.led.pulse()
        payload = get_is_meta(replace(self.is_meta, state=new_state))
        if old_state != new_state:
            self.mqttc.publish(
                topic=topic,
                payload=payload,
                qos=self.qos,
                retain=True,
            )
            logger.debug("Publish %s on %s", payload, topic)

    def _remove_instrument(self, device_id):
        # pylint: disable=invalid-name
        """Removes an instrument from the list of available instruments."""
        try:
            self._unsubscribe_from_device_status_msg(
                self.actor_dict[device_id]["address"]
            )
        except KeyError:
            logger.warning("Cannot unsubscribe %s from DeviceStatusMsg", device_id)
        if self.reservations.pop(device_id, None) is not None:
            logger.info("Remove %s", device_id)
            instr_id = short_id(device_id)
            self.mqttc.unsubscribe(f"{self.group}/{self.is_id}/{instr_id}/control")
            self.mqttc.unsubscribe(f"{self.group}/{self.is_id}/{instr_id}/cmd")
            self.mqttc.publish(
                topic=f"{self.group}/{self.is_id}/{instr_id}/meta",
                payload=json.dumps({"State": 0}),
                qos=self.qos,
                retain=False,
            )
        self._instruments_connected()

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        for actor_id, description in self.actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                self._remove_instrument(actor_id)
        topic = f"{self.group}/{self.is_id}/meta"
        payload = json.dumps({"State": 0})
        publish_result = self.mqttc.publish(
            topic=topic,
            payload=payload,
            qos=self.qos,
            retain=True,
        )
        publish_result.wait_for_publish()
        logger.debug("Publish %s on %s", payload, topic)
        if self.led and not self.led.closed:
            self.led.close()
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # pylint: disable=too-many-arguments
        """Will be carried out when the client connected to the MQTT broker."""
        super().on_connect(client, userdata, flags, reason_code, properties)
        if self.led:
            self.led.on()
        self._instruments_connected()
        self.mqttc.subscribe(f"{self.group}/+/meta", 2)
        self.mqttc.subscribe(f"{self.group}/{self.is_id}/+/meta", 2)
        self.mqttc.subscribe(f"{self.group}/{self.is_id}/cmd", 2)
        self._subscribe_to_actor_dict_msg()

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
            self.pending_control_action = {
                "instr_id": instr_id,
                "control": control,
                "ctype": control.ctype,
            }
            if control.ctype == ControlType.RESERVE:
                self.process_reserve(instr_id, control)
            elif control.ctype == ControlType.FREE:
                self.process_free(instr_id)
                logger.debug(
                    "[FREE] client=%s, instr_id=%s, control=%s",
                    self.mqttc,
                    instr_id,
                    control,
                )
            elif control.ctype == ControlType.VALUE:
                self.process_value(instr_id, control)
            elif control.ctype == ControlType.CONFIG:
                self.process_config(instr_id, control)
            elif control.ctype == ControlType.MONITOR_START:
                self.process_monitor(instr_id, control.data.start_time)
            elif control.ctype == ControlType.MONITOR_STOP:
                self.process_monitor_stop(instr_id)
            elif control.ctype == ControlType.SET_RTC:
                self.process_set_rtc(instr_id)

    def on_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic for instruments."""
        logger.info("[on_cmd] %s: %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        protocol_type = get_sarad_type(instr_id)
        self.cmd_ids[instr_id] = message.payload[0]
        cmd = message.payload[1:]
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            if self._is_get_next(data=cmd, protocol_type=protocol_type):
                self.inner_thread = Thread(
                    target=self._publish_function,
                    kwargs={"instr_id": instr_id},
                    daemon=True,
                )
                self._start_thread(self.inner_thread)
                if not self.buy_ahead:
                    logger.debug("Forward %s to %s", cmd, instr_id)
                    self.send(device_actor, TxBinaryMsg(cmd))
                    self.buy_ahead = cmd
                    self.first_get_next = True
                    logger.info("buy_ahead")
            else:
                logger.debug("Forward %s to %s", cmd, instr_id)
                self.send(device_actor, TxBinaryMsg(cmd))
                self.buy_ahead = b""
                self.cached_reply = b""

    def on_host_cmd(self, _client, _userdata, message):
        """Event handler for all MQTT messages with cmd topic for the host."""
        logger.debug("[on_host_cmd] %s: %s", message.topic, message.payload)
        if message.payload.decode("utf-8") == "scan":
            self.send(self.registrar, RescanMsg(host="127.0.0.1"))
        elif message.payload.decode("utf-8") == "shutdown":
            self.send(self.registrar, ShutdownMsg(password="", host="127.0.0.1"))
        elif message.payload.decode("utf-8") == "update":
            if (datetime.now() - self.last_update) > timedelta(seconds=1):
                logger.debug("Send updated meta information of instruments")
                self.send(self.registrar, GetDeviceStatusesMsg())
                self.last_update = datetime.now()

    def receiveMsg_RxBinaryMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for actor messages returning from 'SEND" command

        Forward the payload received from device_actor via MQTT."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for actor_id, description in self.actor_dict.items():
            if description["address"] == sender:
                instr_id = short_id(actor_id)
                if self.buy_ahead:
                    if self.first_get_next:
                        logger.info("Send reply msg.data to broker")
                        cmd_id = self.cmd_ids[instr_id]
                        reply = bytes([cmd_id]) + msg.data
                        self.mqttc.publish(
                            topic=f"{self.group}/{self.is_id}/{instr_id}/msg",
                            payload=reply,
                            qos=self.qos,
                            retain=False,
                        )
                        self.first_get_next = False
                        device_actor, _device_id = self._device_actor(instr_id)
                        if device_actor is not None:
                            self.send(device_actor, TxBinaryMsg(self.buy_ahead))
                    else:
                        self.inner_thread = Thread(
                            target=self._fill_cache,
                            kwargs={"instr_id": instr_id, "data": msg.data},
                            daemon=True,
                        )
                        self._start_thread(self.inner_thread)
                else:
                    cmd_id = self.cmd_ids[instr_id]
                    reply = bytes([cmd_id]) + msg.data
                    self.mqttc.publish(
                        topic=f"{self.group}/{self.is_id}/{instr_id}/msg",
                        payload=reply,
                        qos=self.qos,
                        retain=False,
                    )

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
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'free' request was received
        for a specific instrument ID.

        """
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, FreeDeviceMsg())
        self.cached_reply = b""
        self.buy_ahead = b""

    def process_value(self, instr_id, control):
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'value' request was
        received for a specific instrument ID.

        """
        logger.debug(
            "[VALUE] client=%s, instr_id=%s, control=%s",
            self.mqttc,
            instr_id,
            control,
        )
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(
                device_actor,
                GetRecentValueMsg(
                    component=control.data.component,
                    sensor=control.data.sensor,
                    measurand=control.data.measurand,
                ),
            )

    def process_config(self, instr_id, control):
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'config' request was
        received for a specific instrument ID. The config request configurates
        the monitoring mode.

        """
        # TODO implement

    def process_monitor(self, instr_id: str, start_time: datetime):
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'monitor-start' request to start
        the monitoring mode was received for a specific instrument ID.

        """
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, StartMonitoringMsg(instr_id, start_time=start_time))

    def process_monitor_stop(self, instr_id: str):
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'monitor-stop' request to stop
        the monitoring mode was received for a specific instrument ID.

        """
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, StopMonitoringMsg(instr_id))

    def process_set_rtc(self, instr_id):
        """Sub event handler that will be called from the on_message event
        handler, when a MQTT control message with a 'set-rtc' request to set
        the clock on teh instrument was received for a specific instrument ID.

        """
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, SetRtcMsg(instr_id))

    def on_is_meta(self, _client, _userdata, message):
        """Handler for all messages of topic group/+/meta.
        This function and subscription was introduced to handle the very special case
        when an Instr. Server leaves an active meta topic on the MQTT broker with
        its retain flag and the is_id was changed."""
        logger.debug("[on_is_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        is_id = topic_parts[1]
        try:
            payload = json.loads(message.payload)
        except (TypeError, json.decoder.JSONDecodeError):
            if message.payload == b"":
                logger.debug("Retained %s removed", message.topic)
            else:
                logger.warning(
                    "Cannot decode %s at topic %s", message.payload, message.topic
                )
            return
        try:
            hostname = payload["Identification"]["Host"]
        except KeyError:
            return
        if (is_id != self.is_id) and (hostname == self.is_meta.host):
            logger.info("Remove retained message at %s", message.topic)
            self.mqttc.publish(
                topic=message.topic,
                payload="",
                qos=self.qos,
                retain=True,
            )

    def on_instr_meta(self, _client, _userdata, message):
        """Handler for all messages of topic group/is_id/+/meta.
        This function and subscription was introduced to handle the very special case
        when a crashed Instr. Server leaves an active meta topic on the MQTT broker with
        its retain flag."""
        logger.debug("[on_instr_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        instr_id = topic_parts[2]
        try:
            payload = json.loads(message.payload)
        except (TypeError, json.decoder.JSONDecodeError):
            if message.payload == b"":
                logger.debug("Retained %s removed", message.topic)
            else:
                logger.warning(
                    "Cannot decode %s at topic %s", message.payload, message.topic
                )
            return
        device_actor, _device_id = self._device_actor(instr_id)
        if (device_actor is None) and (payload.get("State", 2) in (2, 1)):
            topic = f"{self.group}/{self.is_id}/{instr_id}/meta"
            logger.info("Remove retained message at %s", topic)
            self.mqttc.publish(
                topic=topic,
                payload="",
                qos=self.qos,
                retain=True,
            )

    def _device_actor(self, instr_id):
        """Get device actor address and device_id from instr_id"""
        for actor_id, description in self.actor_dict.items():
            if (description["actor_type"] == ActorType.DEVICE) and (
                transport_technology(actor_id) not in ("mqtt", "mdns")
            ):
                if instr_id == short_id(actor_id):
                    return (description["address"], actor_id)
        return (None, "")

    def receiveMsg_RescanAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RescanAckMsg from Registrar."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._instruments_connected()

    def receiveMsg_SetRtcAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetRtcAckMsg from UsbActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        topic = f"{self.group}/{self.is_id}/{msg.instr_id}/ack"
        message = {
            "req": "set-rtc",
            "client": self.pending_control_action["control"].data.client,
            "status": msg.status.value,
            "utc_offset": msg.utc_offset,
            "wait": msg.wait,
        }
        self.mqttc.publish(
            topic=topic,
            payload=json.dumps(message),
            qos=self.qos,
            retain=False,
        )
        logger.info("Publish %s on %s", message, topic)

    def receiveMsg_StartMonitoringAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for StartMonitoringAckMsg from UsbActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        topic = f"{self.group}/{self.is_id}/{msg.instr_id}/ack"
        message = {
            "req": "monitor-start",
            "client": self.pending_control_action["control"].data.client,
            "status": msg.status.value,
            "offset": msg.offset.total_seconds(),
        }
        self.mqttc.publish(
            topic=topic,
            payload=json.dumps(message),
            qos=self.qos,
            retain=False,
        )
        logger.info("Publish %s on %s", message, topic)

    def receiveMsg_StopMonitoringAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for StopMonitoringAckMsg from UsbActor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        topic = f"{self.group}/{self.is_id}/{msg.instr_id}/ack"
        message = {
            "req": "monitor-stop",
            "client": self.pending_control_action["control"].data.client,
            "status": msg.status.value,
        }
        self.mqttc.publish(
            topic=topic,
            payload=json.dumps(message),
            qos=self.qos,
            retain=False,
        )
        logger.info("Publish %s on %s", message, topic)

    def receiveMsg_ShutdownAckMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ShutdownAckMsg from Registrar."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self._instruments_connected()

    def _is_get_next(self, data: bytes, protocol_type: str) -> bool:
        """Check whether bytes contains a GetNext or ReadDataContinue command."""
        logger.info(data)
        if protocol_type == "sarad-1688":
            if data[3] == 7:
                logger.debug("is GetNext")
                return True
        if protocol_type == "sarad-dacm":
            if data[3] == 15:
                logger.info("is ReadDataContinue")
                return True
        return False

    def _start_thread(self, thread):
        if not self.inner_thread.is_alive():
            self.inner_thread = thread
            self.inner_thread.start()
        else:
            logger.debug("Waiting for %s to finish...", self.inner_thread)
            self.wakeupAfter(timedelta(seconds=0.5), payload=thread)

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name, disable=too-many-branches
        """Handler for WakeupMessage"""
        if isinstance(msg.payload, Thread):
            self._start_thread(msg.payload)

    def _publish_function(self, instr_id):
        while not self.cached_reply:
            time.sleep(0.05)
        logger.debug("cached reply available")
        reply = bytes([self.cmd_ids[instr_id]]) + self.cached_reply
        self.mqttc.publish(
            topic=f"{self.group}/{self.is_id}/{instr_id}/msg",
            payload=reply,
            qos=self.qos,
            retain=False,
        )
        self.cached_reply = b""

    def _fill_cache(self, instr_id, data):
        while self.cached_reply:
            time.sleep(0.05)
        logger.info("Put reply msg.data into cache")
        self.cached_reply = data
        device_actor, _device_id = self._device_actor(instr_id)
        if device_actor is not None:
            self.send(device_actor, TxBinaryMsg(self.buy_ahead))
