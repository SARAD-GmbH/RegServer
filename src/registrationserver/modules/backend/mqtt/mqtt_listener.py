"""Listening for MQTT topics announcing the existence of a new SARAD instrument
in the MQTT network

:Created:
    2021-03-10

:Authors:
    | Yang, Yixiang
    | Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_listener.puml
"""
import json

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (ActorType, KillMsg,
                                               MqttConnectMsg,
                                               PrepareMqttActorMsg,
                                               SetDeviceStatusMsg)
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.backend.mqtt.mqtt_actor import MqttActor
from registrationserver.modules.backend.mqtt.mqtt_base_actor import \
    MqttBaseActor

# logger.debug("%s -> %s", __package__, __file__)


class MqttListener(MqttBaseActor):
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

    def device_id(self, is_id, instr_id):
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

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add("+/+/meta", self.on_is_meta)
        self.mqttc.message_callback_add("+/+/+/meta", self.on_instr_meta)

    def _add_instr(self, is_id, instr_id, payload: dict) -> None:
        # pylint: disable=too-many-return-statements
        logger.debug("[add_instr] %s", payload)
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[add_instr] one or both of the IS ID and Instrument ID"
                " are none or the meta message is none."
            )
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
        logger.info(
            "[add_instr] Instrument ID %s, actorname %s",
            instr_id,
            device_id,
        )
        if device_id in self.child_actors:
            logger.warning("%s already exists. Nothing to do.", device_id)
        else:
            device_actor = self._create_actor(MqttActor, device_id, None)
            self.child_actors[device_id]["host"] = is_id
            self.send(device_actor, SetDeviceStatusMsg(device_status=payload))
            client_id = f"{device_id}.client"
            self.send(
                device_actor,
                PrepareMqttActorMsg(is_id, client_id, self.group),
            )
            self.send(
                device_actor,
                MqttConnectMsg(),
            )

    def _rm_instr(self, is_id, instr_id) -> None:
        logger.debug("[rm_instr] %s, %s", is_id, instr_id)
        device_id = self.device_id(is_id, instr_id)
        if device_id is None:
            logger.debug("Instrument unknown")
            return
        logger.info("[rm_instr] %s", device_id)
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
        device_id = self.device_id(is_id, instr_id)
        if device_id is None:
            logger.warning("[update_instr] Instrument unknown")
            return
        logger.info("[update_instr] %s", device_id)
        device_actor = self.child_actors[device_id]["actor_address"]
        self.send(device_actor, SetDeviceStatusMsg(device_status=payload))

    def _add_host(self, is_id, data) -> None:
        if (is_id is None) or (data is None):
            logger.error(
                "[Add Host] One or both of the IS ID and the meta message are None."
            )
            return
        logger.debug(
            "[Add Host] Found a new connected host with IS ID %s",
            is_id,
        )
        self._hosts[is_id] = data
        self._subscribe_topic([(f"{self.group}/{is_id}/+/meta", 0)])
        logger.info("[Add Host] IS %s added", is_id)

    def _update_host(self, is_id, data) -> None:
        if (is_id is None) or (data is None):
            logger.warning(
                "[Update Host] one or both of the IS ID "
                "and the meta message are none"
            )
            return
        logger.info(
            "[Update Host] Update an already connected host with IS ID %s",
            is_id,
        )
        self._hosts[is_id] = data
        return

    def _rm_host(self, is_id) -> None:
        logger.debug("[_rm_host] %s", is_id)
        self._unsubscribe_topic([f"{self.group}/{is_id}/+/meta"])
        instr_to_remove = []
        for device_id, description in self.child_actors.items():
            if description["host"] == is_id:
                logger.debug("[_rm_host] Remove %s", device_id)
                instr_to_remove.append([is_id, short_id(device_id)])
        for instr in instr_to_remove:
            self._rm_instr(instr[0], instr[1])
        logger.info("[Remove Host] IS %s removed", self._hosts[is_id].get("Host"))
        del self._hosts[is_id]

    def on_is_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/meta."""
        topic_parts = message.topic.split("/")
        is_id = topic_parts[1]
        payload = json.loads(message.payload)
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
        elif payload["State"] == 0:
            if is_id in self._hosts:
                logger.debug(
                    "[+/meta] Remove host file for %s",
                    is_id,
                )
                self._rm_host(is_id)
            else:
                logger.info(
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
        payload = json.loads(message.payload)
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
                if self.device_id(is_id, instr_id) is not None:
                    self._update_instr(is_id, instr_id, payload)
                else:
                    self._add_instr(is_id, instr_id, payload)
            else:
                logger.warning(
                    "[+/meta] Received a meta message of instr. %s from IS %s not added before",
                    instr_id,
                    is_id,
                )
        elif payload["State"] == 0:
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

    @overrides
    def on_connect(self, client, userdata, flags, reason_code):
        super().on_connect(client, userdata, flags, reason_code)
        self._subscribe_topic([("+/+/meta", 0)])

    def receiveMsg_RescanMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Forware a rescan command to the remote Instrument Server"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        for is_id in self._hosts:
            self._publish(
                {
                    "topic": f"{self.group}/{is_id}/cmd",
                    "payload": "scan",
                    "qos": self.qos,
                }
            )
