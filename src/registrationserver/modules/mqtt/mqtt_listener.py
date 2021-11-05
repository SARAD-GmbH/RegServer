"""Listening for MQTT topics announcing the existence of a new SARAD instrument
in the MQTT network

Created
    2021-03-10

Author
    Yang, Yixiang
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_listener.puml
"""
import json
import os
import time

import paho.mqtt.client as MQTT  # type: ignore
from registrationserver.config import config, mqtt_config
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.modules.mqtt.mqtt_actor import MqttActor
from thespian.actors import ActorSystem  # type: ignore
from thespian.actors import ActorExitRequest

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

    @staticmethod
    def _update_host(is_id, data) -> None:
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
        filename = fr"{config['IC_HOSTS_FOLDER']}{os.path.sep}{is_id}"
        try:
            with open(filename, "w+", encoding="utf8") as file_stream:
                file_stream.write(json.dumps(data))
                logger.debug("Hosts file %s updated", filename)
        except Exception:  # pylint: disable=broad-except
            logger.critical("[Update Host] Fatal error")
        return

    def __init__(self):
        self.mqtt_broker = mqtt_config.get("MQTT_BROKER", "127.0.0.1")
        self.port = mqtt_config.get("PORT", 1883)
        self.connected_instruments = {}
        self.ungr_disconn = 2
        self.is_connected = False
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
        self.mqttc = MQTT.Client(mqtt_cid)
        self.mqttc.reinitialise()
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        self.mqttc.message_callback_add("+/meta", self.on_is_meta)
        self.mqttc.message_callback_add("+/+/meta", self.on_instr_meta)

        ic_hosts_folder = f"{config['IC_HOSTS_FOLDER']}{os.path.sep}"
        if not os.path.exists(ic_hosts_folder):
            os.makedirs(ic_hosts_folder)

        self._connect()

    def _connect(self):
        success = False
        retry_interval = mqtt_config.get("RETRY_INTERVAL", 60)

        while not success and self.ungr_disconn > 0:
            try:
                logger.info(
                    "Attempting to connect to broker %s: %s",
                    self.mqtt_broker,
                    self.port,
                )
                self.mqttc.connect(self.mqtt_broker, port=self.port)
                success = True
            except Exception as exception:  # pylint: disable=broad-except
                logger.error("Could not connect to Broker, retrying...: %s", exception)
                time.sleep(retry_interval)

    def mqtt_loop(self):
        """Running one cycle of the MQTT loop"""
        self.mqttc.loop()

    def _add_instr(self, is_id, instr_id, payload) -> None:
        # pylint: disable=too-many-return-statements
        logger.debug("[add_instr] %s", payload)
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[add_instr] one or both of the IS ID and Instrument ID"
                " are none or the meta message is none."
            )
            return
        if is_id not in self.connected_instruments.keys():
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
        ac_name = instr_id + "." + sarad_type + ".mqtt"
        self.connected_instruments[is_id][instr_id] = ac_name
        logger.info(
            "[add_instr] Instrument ID %s, actorname %s",
            instr_id,
            ac_name,
        )
        this_actor = ActorSystem().createActor(MqttActor, globalName=ac_name)
        data = json.dumps(payload)
        setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": data})
        logger.debug("SETUP returns: %s", setup_return)
        if not setup_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.debug("[add_instr] %s", setup_return)
            ActorSystem().ask(this_actor, ActorExitRequest())
            del self.connected_instruments[is_id][instr_id]
            return
        prep_msg = {
            "CMD": "PREPARE",
            "PAR": {
                "is_id": is_id,
                "mqtt_broker": self.mqtt_broker,
                "port": self.port,
            },
        }
        prep_return = ActorSystem().ask(this_actor, prep_msg)
        logger.debug(prep_return)
        if not prep_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.debug("[add_instr] %s", prep_return)
            logger.critical("[add_instr] MQTT actor failed to prepare itself. Kill it.")
            ActorSystem().ask(this_actor, ActorExitRequest())
            del self.connected_instruments[is_id][instr_id]
            return
        return

    def _rm_instr(self, is_id, instr_id) -> None:
        logger.debug("rm_instr")
        if (is_id is None) or (instr_id is None):
            logger.warning(
                "[rm_instr] One or both of the IS ID " "and Instrument ID are None."
            )
            return
        if (
            is_id not in self.connected_instruments
            or instr_id not in self.connected_instruments[is_id]
        ):
            logger.debug(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.connected_instruments[is_id][instr_id]
        logger.info("[rm_instr] %s", instr_id)
        this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
        ActorSystem().ask(this_actor, ActorExitRequest())
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
            logger.warning("[update_instr] %s", RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.connected_instruments[is_id][instr_id]
        logger.info("[update_instr] %s", instr_id)
        this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
        setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": payload})
        logger.debug(setup_return)
        if not setup_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
        ):
            logger.debug(setup_return)
            ActorSystem().ask(this_actor, ActorExitRequest())
            del self.connected_instruments[is_id][instr_id]
            return
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
        ic_hosts_folder = f"{config['IC_HOSTS_FOLDER']}{os.path.sep}"
        if not os.path.exists(ic_hosts_folder):
            os.makedirs(ic_hosts_folder)
        filename = fr"{ic_hosts_folder}{is_id}"
        try:
            with open(filename, "w+", encoding="utf8") as file_stream:
                file_stream.write(json.dumps(data))
                logger.debug("New host file %s created", filename)
            self.connected_instruments[is_id] = {}
            self._subscribe(is_id + "/+/meta", 0)
            logger.info("[Add Host] IS %s added", is_id)
            return
        except Exception:  # pylint: disable=broad-except
            logger.critical("Fatal error")

    def _rm_host(self, is_id) -> None:
        logger.debug("[Remove Host] %s", is_id)
        self._unsubscribe(is_id + "/+/meta")
        for instr_id in self.connected_instruments[is_id]:
            logger.info("[Remove Host] Remove instrument %s", instr_id)
            self._rm_instr(is_id, instr_id)
        del self.connected_instruments[is_id]
        filename = f"{config['IC_HOSTS_FOLDER']}{os.path.sep}{is_id}"
        if os.path.exists(filename):
            os.remove(filename)
        logger.info("[Remove Host] Host file for %s removed", is_id)

    def stop(self):
        """Has to be performed when closing the main module
        in order to clean up the open connections to the MQTT broker."""
        logger.info("[Disconnect] %s", self.connected_instruments)
        if os.path.exists(config["IC_HOSTS_FOLDER"]):
            for root, _, files in os.walk(config["IC_HOSTS_FOLDER"]):
                for name in files:
                    filename = os.path.join(root, name)
                    logger.debug("[Del] %s removed", name)
                    os.remove(filename)
        self.connected_instruments = None
        self._disconnect()

    def on_is_meta(self, _client, _userdata, message):
        """Handler for all messages of topic +/meta."""
        topic_parts = message.topic.split("/")
        is_id = topic_parts[0]
        payload = message.payload
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
                "[+/meta] Write the properties of cluster %s into file",
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
        payload = message.payload
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
                    "[+/+/meta] Write properties of instrument %s into file",
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
            self.is_connected = True
            logger.info("[on_connect] Connected with MQTT broker.")
            self._subscribe("+/meta", 0)
        else:
            self.is_connected = False
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
        self.is_connected = False

        if self.ungr_disconn > 0:
            self._connect()

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

    def _subscribe(self, topic: str, qos: int) -> dict:
        logger.debug("[Subscribe]")
        result_code, self.msg_id["SUBSCRIBE"] = self.mqttc.subscribe(topic, qos)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Subscribe] failed with result code %s", result_code)
            return {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE"]["ERROR_CODE"],
            }
        logger.info("[Subscribe] Subscribed to topic %s", topic)
        return {
            "RETURN": "SUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }

    def _unsubscribe(self, topic: str) -> dict:
        logger.debug("[Unsubscribe]")
        result_code, self.msg_id["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topic)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("[Unsubscribe] failed with result code %s", result_code)
            return {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
            }
        logger.info("[Unsubscribe] Unsubscribed topic %s", topic)
        return {
            "RETURN": "UNSUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
