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
from typing import Any, Dict

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, PrepareMqttActorMsg,
                                               SetDeviceStatusMsg)
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.mqtt.mqtt_actor import MqttActor
from registrationserver.modules.mqtt.mqtt_base_actor import MqttBaseActor

logger.debug("%s -> %s", __package__, __file__)


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

    def device_id(self, instr_id):
        """Deliver device_id belonging to the instr_id in the argument."""
        for device_id in self.child_actors:
            if instr_id in device_id:
                return device_id
        return None

    @overrides
    def __init__(self):
        super().__init__()
        self._hosts = {}  # {is_id: {"meta": <data>, "instr_ids": [instr_id, ...]}}

    @overrides
    def receiveMsg_PrepareMqttActorMsg(self, msg, sender):
        super().receiveMsg_PrepareMqttActorMsg(msg, sender)
        self.mqttc.message_callback_add("+/meta", self.on_is_meta)
        self.mqttc.message_callback_add("+/+/meta", self.on_instr_meta)

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
        device_id = instr_id + "." + sarad_type + ".mqtt"
        try:
            self._hosts[is_id]["instr_ids"].append(instr_id)
        except KeyError:
            logger.warning("Unknown host.")
            self._hosts[is_id] = {"meta": None, "instr_ids": [instr_id]}
        logger.info(
            "[add_instr] Instrument ID %s, actorname %s",
            instr_id,
            device_id,
        )
        device_actor = self._create_actor(MqttActor, device_id)
        self.send(device_actor, SetDeviceStatusMsg(device_status=payload))
        client_id = f"{device_id}.client"
        self.send(
            device_actor,
            PrepareMqttActorMsg(is_id, client_id),
        )

    def _rm_instr(self, is_id, instr_id) -> None:
        logger.debug("[rm_instr] %s, %s", is_id, instr_id)
        device_id = self.device_id(instr_id)
        if device_id is None:
            logger.debug("Instrument unknown")
            return
        logger.info("[rm_instr] %s", instr_id)
        device_actor = self.child_actors[device_id]
        self.send(device_actor, KillMsg())

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        instr_id = short_id(msg.childAddress)
        for host in self._hosts.values():
            active_instr_s = host["instr_ids"]
            if instr_id in active_instr_s:
                host["instr_ids"] = active_instr_s.remove(instr_id)
        super().receiveMsg_ChildActorExited(msg, sender)

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
        logger.info("[update_instr] %s", instr_id)
        device_actor = self.child_actors[device_id]
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
        self._hosts[is_id] = {"meta": data, "instr_ids": []}
        self._subscribe_topic([(is_id + "/+/meta", 0)])
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
        self._hosts[is_id]["meta"] = data
        return

    def _rm_host(self, is_id) -> None:
        logger.debug("[Remove Host] %s", is_id)
        self._unsubscribe_topic(is_id + "/+/meta")
        instruments_to_remove: Dict[str, Any] = {}
        instruments_to_remove[is_id] = {}
        for instr_id in self._hosts[is_id]["instr_ids"]:
            logger.info("[Remove Host] Remove %s", instr_id)
            self._rm_instr(is_id, instr_id)
        del self._hosts[is_id]

    def on_is_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/meta."""
        topic_parts = message.topic.split("/")
        is_id = topic_parts[0]
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
                "[+/meta] Store the properties of cluster %s",
                is_id,
            )
            if is_id not in self._hosts:
                self._add_host(is_id, payload)
            else:
                self._update_host(is_id, payload)
        elif payload["State"] == 0:
            if is_id in self._hosts:
                logger.debug(
                    "[+/meta] Remove host file for cluster %s",
                    is_id,
                )
                self._rm_host(is_id)
            else:
                logger.warning(
                    "[+/meta] Subscriber disconnected from unknown IS %s",
                    is_id,
                )
        else:
            logger.warning(
                "[+/meta] Subscriber received a meta message of an unknown cluster %s",
                is_id,
            )

    def on_instr_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/+/meta."""
        logger.debug("[on_instr_meta] %s, %s", message.topic, message.payload)
        topic_parts = message.topic.split("/")
        is_id = topic_parts[0]
        instr_id = topic_parts[1]
        payload = json.loads(message.payload)
        if "State" not in payload:
            logger.warning(
                "[+/+/meta] State of instrument %s missing in meta message from IS %s",
                instr_id,
                is_id,
            )
            return
        if payload.get("State") is None:
            logger.error(
                "[+/+/meta] None state of instrument %s in meta message from IS %s",
                instr_id,
                is_id,
            )
            return
        if payload["State"] in (2, 1):
            if is_id in self._hosts:
                logger.debug(
                    "[+/+/meta] Store properties of instrument %s",
                    instr_id,
                )
                if instr_id in self._hosts[is_id]["instr_ids"]:
                    self._update_instr(is_id, instr_id, payload)
                else:
                    self._add_instr(is_id, instr_id, payload)
            else:
                logger.warning(
                    "[+/+/meta] Received a meta message of instr. %s from IS %s not added before",
                    instr_id,
                    is_id,
                )
        elif payload["State"] == 0:
            logger.debug("disconnection message")
            try:
                self._rm_instr(is_id, instr_id)
                logger.debug(
                    "[+/+/meta] Remove instrument %s from IS %s",
                    instr_id,
                    is_id,
                )
            except KeyError:
                logger.warning(
                    "[+/+/meta] Subscriber received disconnect of unknown instrument %s from IS %s",
                    instr_id,
                    is_id,
                )
        else:
            logger.warning(
                "[+/+/meta] Subscriber received unknown state of unknown instrument %s from IS %s",
                instr_id,
                is_id,
            )

    @overrides
    def on_connect(self, client, userdata, flags, result_code):
        super().on_connect(client, userdata, flags, result_code)
        self._subscribe_topic([("+/meta", 0)])
