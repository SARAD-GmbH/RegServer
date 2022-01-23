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
import os
import socket
import ssl
import time
from typing import Any, Dict

import paho.mqtt.client as MQTT  # type: ignore
from registrationserver.actor_messages import (AppType, PrepareMqttActorMsg,
                                               SetDeviceStatusMsg, SetupMsg)
from registrationserver.config import mqtt_config
from registrationserver.helpers import get_device_actor
from registrationserver.logger import logger
from registrationserver.modules.mqtt.mqtt_actor import MqttActor
from registrationserver.shutdown import system_shutdown
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore

logger.debug("%s -> %s", __package__, __file__)


class SaradMqttSubscriber:
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

    def __init__(self):
        self.mqtt_broker = mqtt_config.get("MQTT_BROKER", "127.0.0.1")
        self.port = mqtt_config.get("PORT", 1883)
        self.connected_instruments = {}
        self.ungr_disconn = 2
        self._is_connected = False
        self.msg_id = {
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check
        mqtt_cid = mqtt_config.get("MQTT_CLIENT_ID", "sarad_subscriber")
        logger.info(
            "[Setup] Connect to MQTT broker at %s, port %d as %s",
            self.mqtt_broker,
            self.port,
            mqtt_cid,
        )
        self._subscriptions = {}
        self._hosts = {}
        self.mqttc = MQTT.Client(mqtt_cid)
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        self.mqttc.message_callback_add("+/meta", self.on_is_meta)
        self.mqttc.message_callback_add("+/+/meta", self.on_instr_meta)

    @property
    def is_connected(self) -> bool:
        """Indicates the connection to the broker

        self._is_connected will be set in the on_connect handler."""
        return self._is_connected

    def connect(self):
        """Try to connect the MQTT broker

        Give up after 3 attempts with RETRY_INTERVAL.
        Give up, if TLS files are not available.
        """
        retry_interval = mqtt_config["RETRY_INTERVAL"]
        for retry_counter in range(3, 0, -1):
            try:
                logger.info(
                    "Attempting to connect to broker %s: %s",
                    self.mqtt_broker,
                    self.port,
                )
                if mqtt_config["TLS_USE_TLS"] and self.mqttc._ssl_context is None:
                    ca_certs = os.path.expanduser(mqtt_config["TLS_CA_FILE"])
                    certfile = os.path.expanduser(mqtt_config["TLS_CERT_FILE"])
                    keyfile = os.path.expanduser(mqtt_config["TLS_KEY_FILE"])
                    logger.info(
                        "Setting up TLS: %s | %s | %s", ca_certs, certfile, keyfile
                    )
                    self.mqttc.tls_set(
                        ca_certs=ca_certs,
                        certfile=certfile,
                        keyfile=keyfile,
                        cert_reqs=ssl.CERT_REQUIRED,
                    )
                self.mqttc.connect(self.mqtt_broker, port=self.port)
                logger.debug("We are connected.")
                return True
            except FileNotFoundError:
                logger.critical(
                    "Cannot find files expected in %s, %s, %s",
                    mqtt_config["TLS_CA_FILE"],
                    mqtt_config["TLS_CERT_FILE"],
                    mqtt_config["TLS_KEY_FILE"],
                )
                return False
            except socket.gaierror:
                logger.error("We are offline and can handle only local instruments.")
                logger.info(
                    "Check your network connection and IP address in config_windows.toml!"
                )
                logger.info(
                    "I will be waiting %d x %d seconds, then I will give up.",
                    retry_counter,
                    retry_interval,
                )
            except OSError as exception:  # pylint: disable=broad-except
                logger.error("%s. Check port in config_windows.toml!", exception)
                return False
            time.sleep(retry_interval)
        return False

    def mqtt_loop(self):
        """Running one cycle of the MQTT loop"""
        self.mqttc.loop()

    def _add_instr(self, is_id, instr_id, payload: dict) -> None:
        # pylint: disable=too-many-return-statements
        logger.debug("[add_instr] %s", payload)
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[add_instr] one or both of the IS ID and Instrument ID"
                " are none or the meta message is none."
            )
            return
        if is_id not in self.connected_instruments:
            logger.debug(
                "[add_instr] Unknown instrument %s from unknown IS %s",
                instr_id,
                is_id,
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
        actor_id = instr_id + "." + sarad_type + ".mqtt"
        self.connected_instruments[is_id][instr_id] = actor_id
        logger.info(
            "[add_instr] Instrument ID %s, actorname %s",
            instr_id,
            actor_id,
        )
        this_actor = ActorSystem().createActor(MqttActor)
        ActorSystem().tell(
            this_actor, SetupMsg(actor_id, "actor_system", AppType.ISMQTT)
        )
        ActorSystem().tell(this_actor, SetDeviceStatusMsg(device_status=payload))
        ActorSystem().tell(
            this_actor, PrepareMqttActorMsg(is_id, self.mqtt_broker, self.port)
        )

    def _rm_instr(self, is_id, instr_id) -> None:
        logger.debug("[rm_instr] %s, %s", is_id, instr_id)
        if (is_id is None) or (instr_id is None):
            logger.warning(
                "[rm_instr] One or both of the IS ID " "and Instrument ID are None."
            )
            return
        if (
            is_id not in self.connected_instruments
            or instr_id not in self.connected_instruments[is_id]
        ):
            logger.debug("Instrument unknown")
            return
        device_id = self.connected_instruments[is_id][instr_id]
        logger.info("[rm_instr] %s", instr_id)
        device_actor = get_device_actor(device_id)
        ActorSystem().tell(device_actor, ActorExitRequest())
        del self.connected_instruments[is_id][instr_id]
        return

    def _update_instr(self, is_id, instr_id, payload) -> None:
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[update_instr] one or both of the IS ID "
                "and Instrument ID are None or the meta message is None."
            )
            return
        if (
            is_id not in self.connected_instruments
            or instr_id not in self.connected_instruments[is_id]
        ):
            logger.warning("[update_instr] Instrument unknown")
            return
        device_id = self.connected_instruments[is_id][instr_id]
        logger.info("[update_instr] %s", instr_id)
        device_actor = get_device_actor(device_id)
        ActorSystem().tell(device_actor, SetDeviceStatusMsg(device_status=payload))
        return

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
        self.connected_instruments[is_id] = {}
        self._subscribe(is_id + "/+/meta", 0)
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
        logger.debug("[Remove Host] %s", is_id)
        self._unsubscribe(is_id + "/+/meta")
        instruments_to_remove: Dict[str, Any] = {}
        instruments_to_remove[is_id] = {}
        for instr_id in self.connected_instruments[is_id]:
            logger.info("[Remove Host] Mark %s for removal", instr_id)
            instruments_to_remove[is_id][instr_id] = self.connected_instruments[is_id][
                instr_id
            ]
        logger.debug("Instruments to be removed: %s", instruments_to_remove)
        logger.debug("Connected instruments: %s", self.connected_instruments)
        try:
            for instr_id in instruments_to_remove[is_id]:
                self._rm_instr(is_id, instr_id)
        except KeyError:
            logger.debug("No instrument to remove.")
        try:
            del self.connected_instruments[is_id]
            del self._hosts[is_id]
        except KeyError:
            logger.critical("List of connected hosts corrupted.")
            system_shutdown()

    def stop(self):
        """Has to be performed when closing the main module
        in order to clean up the open connections to the MQTT broker."""
        logger.info("[Disconnect] %s", self.connected_instruments)
        self.connected_instruments = None
        self._disconnect()

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
            if is_id not in self.connected_instruments:
                self._add_host(is_id, payload)
            else:
                self._update_host(is_id, payload)
        elif payload["State"] == 0:
            if is_id in self.connected_instruments:
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
            if is_id in self.connected_instruments:
                logger.debug(
                    "[+/+/meta] Store properties of instrument %s",
                    instr_id,
                )
                if instr_id in self.connected_instruments[is_id]:
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
            if (is_id in self.connected_instruments) and (
                instr_id in self.connected_instruments[is_id]
            ):
                logger.debug(
                    "[+/+/meta] Remove instrument %s from IS %s",
                    instr_id,
                    is_id,
                )
                self._rm_instr(is_id, instr_id)
            else:
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

    def on_connect(self, client, userdata, flags, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        logger.debug("on_connect")
        if result_code == 0:
            self._is_connected = True
            logger.info("[on_connect] Connected with MQTT broker.")
            self.mqttc.subscribe("+/meta", 0)
            for topic, qos in self._subscriptions.items():
                logger.debug("Restore subscription to %s", topic)
                self.mqttc.subscribe(topic, qos)
        else:
            self._is_connected = False
            logger.error(
                "[on_connect] Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
            )

    def on_disconnect(self, client, userdata, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        logger.debug("on_disconnect")
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.warning(
                "[on_disconnect] Disconnection from MQTT broker ungracefully. result_code=%s",
                result_code,
            )
        else:
            self.ungr_disconn = 0
            logger.info("[on_disconnect] Gracefully disconnected from MQTT broker.")
        self._is_connected = False

        if self.ungr_disconn > 0:
            self.connect()

    def on_subscribe(self, _client, _userdata, msg_id, _grant_qos):
        """Here should be a docstring."""
        logger.debug("[on_subscribe] msg_id is %s", msg_id)
        logger.debug("stored msg_id is %s", self.msg_id["SUBSCRIBE"])
        if msg_id == self.msg_id["SUBSCRIBE"]:
            logger.debug("Subscribed to topic")

    def on_unsubscribe(self, _client, _userdata, msg_id):
        """Here should be a docstring."""
        logger.debug("[on_unsubscribe] msg_id is %s", msg_id)
        logger.debug("[on_unsubscribe] stored msg_id is %s", self.msg_id["UNSUBSCRIBE"])
        if msg_id == self.msg_id["UNSUBSCRIBE"]:
            logger.debug("[on_unsubscribe] Unsubscribed from topic")

    @staticmethod
    def on_message(_client, _userdata, message):
        """Handle MQTT messages that are not handled by the special message_callback
        functions on_is_meta and on_instr_meta."""
        logger.debug("message received: %s", message.payload)
        logger.debug("message topic: %s", message.topic)
        logger.debug("message qos: %s", message.qos)
        logger.debug("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.warning("The payload is none")
        else:
            logger.warning("Unknown message")

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("[Disconnect] from MQTT broker")
            self.mqttc.disconnect()
        elif self.ungr_disconn in (1, 0):
            self.ungr_disconn = 2
            logger.warning("[Disconnect] Already disconnected ungracefully")
        else:
            logger.warning("[Disconnect] Called but nothing to do")

        self.ungr_disconn = 0

    def _subscribe(self, topic: str, qos: int) -> bool:
        logger.debug("[Subscribe]")
        result_code, self.msg_id["SUBSCRIBE"] = self.mqttc.subscribe(topic, qos)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Subscribe] failed with result code %s", result_code)
            return False
        logger.info("[Subscribe] Subscribed to topic %s", topic)
        self._subscriptions[topic] = qos
        return True

    def _unsubscribe(self, topic: str) -> bool:
        logger.debug("[Unsubscribe]")
        result_code, self.msg_id["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topic)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Unsubscribe] failed with result code %s", result_code)
            return False
        logger.info("[Unsubscribe] Unsubscribed topic %s", topic)
        self._subscriptions.pop(topic)
        return True
