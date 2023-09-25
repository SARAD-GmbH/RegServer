"""Actor representing a SARAD Instrument connected via the MQTT backend

:Created:
    2021-03-10

:Authors:
    | Yang, Yixiang
    | Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_client_actor.puml
"""
import json
from datetime import datetime, timedelta

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ActorType, HostInfoMsg, HostObj,
                                               KillMsg, MqttReceiveMsg,
                                               PrepareMqttActorMsg,
                                               SetDeviceStatusMsg,
                                               TransportTechnology)
from registrationserver.helpers import short_id, transport_technology
from registrationserver.logger import logger
from registrationserver.modules.backend.mqtt.mqtt_base_actor import \
    MqttBaseActor
from registrationserver.modules.backend.mqtt.mqtt_device_actor import \
    MqttDeviceActor

RESCAN_TIMEOUT = timedelta(seconds=7)  # Timeout for RESCAN or SHUTDOWN operations


class MqttClientActor(MqttBaseActor):
    """
    Basic flows:

    #. when an IS MQTT 'IS1_ID' is connected -> _add_host, connected_instruments[IS1_ID] = []
    #. when the ID of this IS MQTT is a key of connected_instruments -> _update_host
    #. disconnection and the ID is a key -> _rm_host, del connected_instruments[IS1_ID]
    #. when an instrument 'Instr_ID11' is connected & the ID of its IS is a key -> _add_instr,
       connected_istruments[IS1_ID].append(Instr_ID11)
    #. when the ID of this instrument exists in the list,
       mapping the ID of its IS MQTT -> _update_instr
    #. disconnection and the instrument ID exists in the list -> _rm_instr

    Structure of connected_instruments::

        connected_instruments = {
           IS1_ID: {
               Instr_ID11 : Actor1_Name,
               Instr_ID12 : Actor2_Name,
               Instr_ID13 : Actor3_Name,
               ...
           },
           IS2_ID: {
               ...
           },
            ...
        }
    """

    @staticmethod
    def _host_dict_to_object(is_id, host_info):
        """Convert an entry of the dictionary of hosts into a Host object.

        Args:
            is_id (str): Instrument server id as given in its configuration.
            host_info (Dict[str]): Dictionary containing host information.

        Returns: A single Host object
        """
        fqdn = host_info.get("Host", "127.0.0.1")
        if fqdn == "127.0.0.1":
            host = is_id
        else:
            host = fqdn
        return HostObj(
            host=host,
            is_id=is_id,
            transport_technology=TransportTechnology.MQTT,
            description=host_info.get("Descr", ""),
            place=host_info.get("Place", ""),
            lat=host_info.get("Lat", 0),
            lon=host_info.get("Lon", 0),
            height=host_info.get("Height", 0),
            state=host_info.get("State", 0),
            version=host_info.get("Ver", ""),
            running_since=datetime.fromisoformat(
                host_info.get(
                    "Since",
                    (datetime(year=1970, month=1, day=1)).isoformat(timespec="seconds"),
                )
            ),
        )

    def device_id(self, instr_id):
        """Deliver device_id belonging to the instr_id in the argument."""
        logger.debug("Search for %s in %s", instr_id, self.child_actors)
        for device_id in self.child_actors:
            if instr_id in device_id:
                return device_id
        return None

    def device_id_2(self, is_id, instr_id):
        """Deliver device_id belonging to the instr_id on is_id in the argument."""
        logger.debug("Search for %s on %s in %s", instr_id, is_id, self.child_actors)
        for device_id, child_actor in self.child_actors.items():
            if (instr_id in device_id) and (child_actor["host"] == is_id):
                return device_id
        return None

    @overrides
    def __init__(self):
        super().__init__()
        self._hosts = {}
        self.actor_type = ActorType.HOST
        self.resurrect_msg = False

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._subscribe_to_actor_dict_msg()

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add(f"{self.group}/+/meta", self.on_is_meta)
        self.mqttc.message_callback_add(f"{self.group}/+/+/meta", self.on_instr_meta)
        self.mqttc.message_callback_add(
            f"{self.group}/+/+/reservation", self.on_instr_reserve
        )
        self.mqttc.message_callback_add(f"{self.group}/+/+/msg", self.on_instr_msg)

    def _add_instr(self, is_id, instr_id, payload: dict, resurrect=False) -> None:
        # pylint: disable=too-many-return-statements
        logger.debug("[add_instr] %s", payload)
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[add_instr] one or both of the IS ID and Instrument ID"
                " are none or the meta message is none."
            )
            return
        if not resurrect:
            for old_device_id in self.actor_dict:
                if short_id(old_device_id) == instr_id:
                    if transport_technology(old_device_id) != "mqtt":
                        logger.info(
                            "%s is already represented by %s",
                            instr_id,
                            old_device_id,
                        )
                        return
                    self._update_instr(is_id, instr_id, payload)
                    return
        try:
            family = payload["Identification"]["Family"]
        except IndexError:
            logger.debug("[add_instr] Family of instrument missed")
            return
        if family == 1:
            sarad_type = "sarad-1688"
        elif family == 2:
            sarad_type = "sarad-1688"
        elif family == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.warning(
                "[add_instr] unknown instrument family (%s)",
                family,
            )
            return
        if is_id not in self._hosts:
            logger.critical(
                "Instr. Server belonging to this device not in self._hosts."
            )
            self._add_host(is_id, None)
        device_id = instr_id + "." + sarad_type + ".mqtt"
        logger.debug(
            "[add_instr] Instrument ID %s, actorname %s",
            instr_id,
            device_id,
        )
        if device_id in self.child_actors:
            logger.warning("%s already exists. Nothing to do.", device_id)
        else:
            device_actor = self._create_actor(MqttDeviceActor, device_id, None)
            self.child_actors[device_id]["host"] = is_id
            payload["State"] = 2
            self.send(device_actor, SetDeviceStatusMsg(device_status=payload))
            self.send(
                device_actor,
                PrepareMqttActorMsg(is_id, self.group),
            )

    def _rm_instr(self, is_id, instr_id) -> None:
        logger.debug("[rm_instr] %s, %s", is_id, instr_id)
        device_id = self.device_id_2(is_id, instr_id)
        if device_id is None:
            logger.debug("Instrument unknown")
            return
        logger.debug("[rm_instr] %s", device_id)
        if self.child_actors.get(device_id, False):
            device_actor = self.child_actors[device_id]["actor_address"]
            self.send(device_actor, KillMsg())
        else:
            logger.warning("Device actor %s doesn't exist.", device_id)

    def _update_instr(self, is_id, instr_id, payload) -> None:
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[update_instr] one or both of the IS ID "
                "and Instrument ID are None or the meta message is None."
            )
            return
        device_id = self.device_id(instr_id)
        if device_id is None:
            logger.warning("[update_instr] Instrument unknown")
            return
        logger.debug("[update_instr] %s", device_id)
        device_actor = self.child_actors[device_id]["actor_address"]
        self.child_actors[device_id]["host"] = is_id
        payload["State"] = 2
        self.send(device_actor, SetDeviceStatusMsg(device_status=payload))

    def _add_host(self, is_id, data) -> None:
        if (is_id is None) or (data is None):
            logger.error("One or both of the IS ID and the meta message are None.")
            return
        logger.debug(
            "Found a new connected host with IS ID %s",
            is_id,
        )
        self._hosts[is_id] = data
        self.mqttc.subscribe(f"{self.group}/{is_id}/+/meta", 2)
        self.send(self.registrar, HostInfoMsg([self._host_dict_to_object(is_id, data)]))
        logger.debug("[Add Host] IS %s added", is_id)

    def _update_host(self, is_id, data) -> None:
        if (is_id is None) or (data is None):
            logger.warning(
                "[Update Host] one or both of the IS ID "
                "and the meta message are none"
            )
            return
        logger.debug(
            "[Update Host] Update an already connected host with IS ID %s",
            is_id,
        )
        self._hosts[is_id] = data
        self.send(self.registrar, HostInfoMsg([self._host_dict_to_object(is_id, data)]))
        return

    def _rm_host(self, is_id, state) -> None:
        logger.debug("[_rm_host] %s", is_id)
        self.mqttc.unsubscribe(f"{self.group}/{is_id}/+/meta")
        instr_to_remove = []
        for device_id, description in self.child_actors.items():
            if description["host"] == is_id:
                logger.debug("[_rm_host] Remove %s", device_id)
                instr_to_remove.append([is_id, short_id(device_id)])
        for instr in instr_to_remove:
            self._rm_instr(instr[0], instr[1])
        logger.debug("[Remove Host] IS %s removed", self._hosts[is_id].get("Host"))
        self._hosts[is_id]["State"] = state
        self.send(
            self.registrar,
            HostInfoMsg([self._host_dict_to_object(is_id, self._hosts[is_id])]),
        )
        del self._hosts[is_id]

    def on_is_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/meta."""
        logger.debug("[on_is_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        is_id = topic_parts[1]
        if self._hosts.get(is_id, False):
            self._hosts[is_id]["rescan_lock"] = False
            self._hosts[is_id]["shutdown_lock"] = False
        try:
            payload = json.loads(message.payload)
        except (TypeError, json.decoder.JSONDecodeError):
            logger.warning(
                "Cannot decode %s at topic %s", message.payload, message.topic
            )
            return
        if "State" not in payload:
            logger.warning(
                "[+/meta] Received meta message not including state of IS %s",
                is_id,
            )
            return
        if payload.get("State") is None:
            logger.warning(
                "[+/meta] Received meta message from IS %s, including a None state",
                is_id,
            )
            return
        if payload["State"] in (2, 1):
            logger.debug(
                "[+/meta] Store the properties of %s",
                is_id,
            )
            if is_id in self._hosts:
                self._update_host(is_id, payload)
            else:
                self._add_host(is_id, payload)
            self.mqttc.publish(
                topic=f"{self.group}/{is_id}/cmd",
                payload="update",
                qos=self.qos,
                retain=False,
            )
        elif payload["State"] in (0, 10):
            if is_id in self._hosts:
                logger.info(
                    "Host with is_id '%s' just died.",
                    is_id,
                )
                self._rm_host(is_id, payload["State"])
            else:
                logger.debug(
                    "[+/meta] IS %s is known but offline",
                    is_id,
                )
        else:
            logger.warning(
                "[+/meta] Subscriber received a meta message of an unknown host %s",
                is_id,
            )

    def on_instr_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/+/meta."""
        logger.debug("[on_instr_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        is_id = topic_parts[1]
        instr_id = topic_parts[2]
        try:
            payload = json.loads(message.payload)
        except (TypeError, json.decoder.JSONDecodeError):
            logger.warning(
                "Cannot decode %s at topic %s", message.payload, message.topic
            )
            return
        if "State" not in payload:
            logger.warning(
                "[+/meta] State of instrument %s missing in meta message from IS %s",
                instr_id,
                is_id,
            )
            return
        if payload.get("State") is None:
            logger.error(
                "[+/meta] None state of instrument %s in meta message from IS %s",
                instr_id,
                is_id,
            )
            return
        if payload["State"] in (2, 1):
            if is_id in self._hosts:
                logger.debug(
                    "[+/meta] Store properties of instrument %s",
                    instr_id,
                )
                if self.device_id(instr_id) is not None:
                    self._update_instr(is_id, instr_id, payload)
                else:
                    self._add_instr(is_id, instr_id, payload)
            else:
                logger.warning(
                    "[+/meta] Received a meta message of instr. %s from IS %s not added before",
                    instr_id,
                    is_id,
                )
        elif payload["State"] in (0, 10):
            logger.debug("disconnection message")
            try:
                self._rm_instr(is_id, instr_id)
                logger.debug(
                    "[+/meta] Remove instrument %s from IS %s",
                    instr_id,
                    is_id,
                )
            except KeyError:
                logger.warning(
                    "[+/meta] Subscriber received disconnect of unknown instrument %s from IS %s",
                    instr_id,
                    is_id,
                )
        else:
            logger.warning(
                "[+/meta] Subscriber received unknown state of unknown instrument %s from IS %s",
                instr_id,
                is_id,
            )

    def on_instr_reserve(self, _client, _userdata, message):
        """Handler for all messages of topic +/+/+/reservation"""
        logger.debug("[on_instr_reserve] %s, %s", message.topic, message.payload)
        try:
            _payload = json.loads(message.payload)
        except (TypeError, json.decoder.JSONDecodeError):
            logger.warning(
                "Cannot decode %s at topic %s", message.payload, message.topic
            )
            return
        instr_id = message.topic.split("/")[2]
        is_id = message.topic.split("/")[1]
        device_id = self.device_id_2(is_id, instr_id)
        for child_id, device_actor in self.child_actors.items():
            if child_id == device_id:
                self.send(
                    device_actor["actor_address"],
                    MqttReceiveMsg(topic=message.topic, payload=message.payload),
                )

    def on_instr_msg(self, _client, _userdata, message):
        """Handler for all messages of topic +/+/+/msg"""
        logger.debug("[on_instr_msg] %s, %s", message.topic, message.payload)
        instr_id = message.topic.split("/")[2]
        is_id = message.topic.split("/")[1]
        device_id = self.device_id_2(is_id, instr_id)
        for child_id, device_actor in self.child_actors.items():
            if child_id == device_id:
                self.send(
                    device_actor["actor_address"],
                    MqttReceiveMsg(topic=message.topic, payload=message.payload),
                )

    @overrides
    def on_connect(self, client, userdata, flags, reason_code):
        super().on_connect(client, userdata, flags, reason_code)
        self.mqttc.subscribe("+/+/meta", 2)

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward a rescan command to the remote Instrument Server"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for is_id, host_descr in self._hosts.items():
            if (msg.host is None) or (msg.host == host_descr.get("Host")):
                host_descr["rescan_lock"] = datetime.now()
                self.wakeupAfter(RESCAN_TIMEOUT, ("rescan_timeout", is_id))
                self.mqttc.publish(
                    topic=f"{self.group}/{is_id}/cmd",
                    payload="scan",
                    qos=self.qos,
                    retain=False,
                )

    def receiveMsg_ShutdownMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forward a shutdown command to the remote Instrument Server"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for is_id, host_descr in self._hosts.items():
            if (msg.host is None) or (msg.host == host_descr.get("Host")):
                host_descr["shutdown_lock"] = datetime.now()
                self.wakeupAfter(RESCAN_TIMEOUT, ("shutdown_timeout", is_id))
                self.mqttc.publish(
                    topic=f"{self.group}/{is_id}/cmd",
                    payload="shutdown",
                    qos=self.qos,
                    retain=False,
                )

    def receiveMsg_GetHostInfoMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for GetHostInfoMsg asking for an updated list of connected hosts"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        hosts = []
        for is_id, host_info in self._hosts.items():
            hosts.append(self._host_dict_to_object(is_id, host_info))
        self.send(sender, HostInfoMsg(hosts=hosts))

    def receiveMsg_ResurrectMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for ResurrectMsg asking for resurrect a killed Device Actor (child)"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.resurrect_msg = msg

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)
        if self.resurrect_msg:
            self._add_instr(
                self.is_id,
                self.resurrect_msg.instr_id,
                self.resurrect_msg.device_status,
                resurrect=True,
            )
            self.resurrect_msg = False

    def receiveMsg_MqttSubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for MqttSubscribeMsg from MQTT Device Actor (child)"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for subscription in msg.sub_info:
            self.mqttc.subscribe(subscription[0], subscription[1])

    def receiveMsg_MqttUnsubscribeMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for MqttUnsubscribeMsg from MQTT Device Actor (child)"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for topic in msg.topics:
            self.mqttc.unsubscribe(topic)

    def receiveMsg_MqttPublishMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for MqttPublishMsg from MQTT Device Actor (child)"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.mqttc.publish(
            topic=msg.topic, payload=msg.payload, qos=msg.qos, retain=msg.retain
        )

    @overrides
    def receiveMsg_WakeupMessage(self, msg, sender):
        super().receiveMsg_WakeupMessage(msg, sender)
        key = msg.payload[0]
        is_id = msg.payload[1]
        if self._hosts.get(is_id):
            rescan_lock = self._hosts[is_id].get("rescan_lock")
            shutdown_lock = self._hosts[is_id].get("rescan_lock")
        if ((key == "rescan_timeout") and rescan_lock) or (
            (key == "shutdown_timeout") and shutdown_lock
        ):
            if key == "rescan_timeout":
                self._hosts[is_id]["rescan_lock"] = False
            elif key == "shutdown_timeout":
                self._hosts[is_id]["shutdown_lock"] = False
            logger.info("Cannot reach host %s. Removing retained messages.", is_id)
            self.mqttc.publish(
                topic=f"{self.group}/{is_id}/meta",
                payload="",
                qos=2,
                retain=True,
            )
            self._rm_host(is_id, 10)
