"""Listening for MQTT topics announcing the existance of a new SARAD instrument
in the MQTT network

Created
    2021-03-10

Author
    Yang, Yixiang
    Michael Strey <strey@sarad.de>

.. uml :: uml-mqtt_subscriber.puml
"""
import json
import os

import paho.mqtt.client as MQTT  # type: ignore
from registrationserver2 import (HOSTS_FOLDER_AVAILABLE, HOSTS_FOLDER_HISTORY,
                                 logger)
from registrationserver2.config import mqtt_config
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore

logger.info("%s -> %s", __package__, __file__)


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

    Struture of connected_instruments::

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
        self.is_connected = False
        self.mid = {
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }  # store the current message ID to check
        mqtt_cid = mqtt_config.get("MQTT_CLIENT_ID", "sarad_subscriber")
        logger.info(
            "[Setup]: Connect to MQTT broker at %s, port %d, with client %s",
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
        self.mqttc.connect(self.mqtt_broker, port=self.port)
        self.mqttc.loop_start()

    def _add_instr(self, instr: dict) -> None:
        is_id = instr.get("is_id", None)
        instr_id = instr.get("instr_id", None)
        payload = instr.get("payload")
        logger.debug("[Add Instrument]: %s", payload)
        if (is_id is None) or (instr_id is None) or (payload is None):
            logger.debug(
                "[Add Instrument]: one or both of the Instrument Server ID and Instrument ID"
                " are none or the meta message is none."
            )
            return
        if is_id not in self.connected_instruments.keys():
            logger.debug(
                (
                    "[Add Instrument]: Unknown instrument '%s' "
                    "controlled by unknown instrument server '%s'"
                ),
                instr_id,
                is_id,
            )
            return
        try:
            family = payload["Identification"]["Family"]
        except IndexError:
            logger.debug("[Add Instrument]: Family of the instrument missed")
            return
        if family == 1:
            sarad_type = "sarad-1688"
        elif family == 2:
            sarad_type = "sarad-1688"
        elif family == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.debug(
                "[Add Instrument]: Found Unknown family (index: %s) of instrument",
                family,
            )
            return
        ac_name = instr_id + "." + sarad_type + ".mqtt"
        self.connected_instruments[is_id][instr_id] = ac_name
        logger.info("[Add Instrument]: Instrument ID - '%s'", instr_id)
        this_actor = ActorSystem().createActor(MqttActor, globalName=ac_name)
        data = json.dumps(payload)
        setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": data})
        logger.info(setup_return)
        if not setup_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.debug("[Add Instrument]: %s", setup_return)
            ActorSystem().tell(this_actor, ActorExitRequest())
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
        logger.info(prep_return)
        if not prep_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.debug("[Add Instrument]: %s", prep_return)
            logger.critical(
                "[Add Instrument]: This MQTT Actor failed to prepare itself. Kill it."
            )
            ActorSystem().tell(this_actor, ActorExitRequest())
            del self.connected_instruments[is_id][instr_id]
            return
        return

    def _rm_instr(self, msg: dict) -> None:
        logger.info("RM_INSTRUMENT")
        is_id = msg.get("PAR", None).get("is_id", None)
        instr_id = msg.get("PAR", None).get("instr_id", None)
        if (is_id is None) or (instr_id is None):
            logger.debug(
                "[Remove Instrument]: one or both of the Instrument Server ID "
                "and Instrument ID are none"
            )
            return
        if (
            is_id not in self.connected_instruments
            or instr_id not in self.connected_instruments[is_id]
        ):
            logger.debug(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.connected_instruments[is_id][instr_id]
        logger.info("[Remove Instrument]: Instrument ID - '%s'", instr_id)
        this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
        ActorSystem().tell(this_actor, ActorExitRequest())
        return

    def _update_instr(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        instr_id = msg.get("PAR", None).get("instr_id", None)
        data = json.dumps(msg.get("PAR", None).get("payload"))
        if (is_id is None) or (instr_id is None) or (data is None):
            logger.debug(
                "[Update Instrument]: one or both of the Instrument Server ID "
                "and Instrument ID are none or the meta message is none"
            )
            return
        if (
            is_id not in self.connected_instruments
            or instr_id not in self.connected_instruments[is_id]
        ):
            logger.warning(
                "[Update Instrument]: %s", RETURN_MESSAGES["INSTRUMENT_UNKNOWN"]
            )
            return
        name_ = self.connected_instruments[is_id][instr_id]
        logger.info("[Update Instrument]: Instrument ID - '%s'", instr_id)
        this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
        setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": data})
        logger.info(setup_return)
        if not setup_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.debug(setup_return)
            ActorSystem().tell(this_actor, ActorExitRequest())
            del self.connected_instruments[is_id][instr_id]
            return
        return

    def _add_host(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (data is None):
            logger.debug(
                "[Add Host]: one or both of the Instrument Server ID and the meta message are none"
            )
            return
        logger.info(
            "[Add Host]: Found a new connected host with Instrument Server ID '%s'",
            is_id,
        )
        folder_hosts_history = f"{HOSTS_FOLDER_HISTORY}{os.path.sep}"
        folder_hosts_available = f"{HOSTS_FOLDER_AVAILABLE}{os.path.sep}"
        if not os.path.exists(folder_hosts_history):
            os.makedirs(folder_hosts_history)
        if not os.path.exists(folder_hosts_available):
            os.makedirs(folder_hosts_available)
        filename = fr"{folder_hosts_history}{is_id}"
        link = fr"{folder_hosts_available}{is_id}"
        try:
            with open(filename, "w+") as file_stream:
                file_stream.write(json.dumps(data))
            if not os.path.exists(link):
                logger.info("Linking %s to %s", link, filename)
                os.link(filename, link)
            self.connected_instruments[is_id] = {}
            self._subscribe(is_id + "/+/meta", 0)
            logger.info(
                (
                    "[Add Host]: Add the information of the instrument server successfully, "
                    "the ID of which is '%s'"
                ),
                is_id,
            )
            return
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")

    def _rm_host(self, msg: dict) -> None:
        try:
            is_id = msg["PAR"]["is_id"]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
            return
        logger.info(
            "[Remove Host]: Remove a host with Instrument Server ID '%s'", is_id
        )
        self._unsubscribe(is_id + "/+/meta")
        logger.info(
            (
                "[Remove Host]: To kill all the instruments "
                "controlled by the instrument server with ID '%s'"
            ),
            is_id,
        )
        for _instr_id in self.connected_instruments[is_id]:
            rm_msg = {
                "PAR": {
                    "is_id": is_id,
                    "instr_id": _instr_id,
                }
            }
            logger.info("[Remove Host]: To kill the instrument with ID '%s'", _instr_id)
            self._rm_instr(rm_msg)
        del self.connected_instruments[is_id]
        folder_hosts_available = f"{HOSTS_FOLDER_AVAILABLE}{os.path.sep}"
        link = fr"{folder_hosts_available}{is_id}"
        if os.path.exists(link):
            os.unlink(link)
        logger.info(
            (
                "[Remove Host]: Remove the link to the information of the instrument server "
                "successfully, the ID of which is '%s'"
            ),
            is_id,
        )
        return

    def _update_host(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (data is None):
            logger.warning(
                "[Update Host]: one or both of the Instrument Server ID "
                "and the meta message are none"
            )
            return
        logger.info(
            "[Update Host]: Update a already connected host with Instrument Server ID '%s'",
            is_id,
        )
        folder_hosts_history = f"{HOSTS_FOLDER_HISTORY}{os.path.sep}"
        folder_hosts_available = f"{HOSTS_FOLDER_AVAILABLE}{os.path.sep}"
        filename = fr"{folder_hosts_history}{is_id}"
        link = fr"{folder_hosts_available}{is_id}"
        try:
            with open(filename, "w+") as file_stream:
                file_stream.write(json.dumps(data))
            if not os.path.exists(link):
                logger.info("Linking %s to %s", link, filename)
                os.link(filename, link)
            logger.info(
                (
                    "[Update Host]: Remove the information of the instrument server "
                    "successfully, the ID of which is '%s'"
                ),
                is_id,
            )
            return
        except Exception:  # pylint: disable=W0703
            logger.Exception("[Update Host]: Fatal error")
            return

    def stop(self):
        """Has to be performed when closing the main module
        in order to clean up the open connections to the MQTT broker."""
        logger.info(
            "[Disconnect]: list of connected instruments -> %s",
            self.connected_instruments,
        )
        if os.path.exists(HOSTS_FOLDER_AVAILABLE):
            for root, _, files in os.walk(HOSTS_FOLDER_AVAILABLE):
                for name in files:
                    link = os.path.join(root, name)
                    logger.debug("[Del]:\tRemoved: %s", name)
                    os.unlink(link)
        self.connected_instruments = None
        self._disconnect()

    def _parse(self, msg) -> None:
        logger.info("PARSE")
        topic = msg.get("PAR", None).get("topic", None)
        payload = msg.get("PAR", None).get("payload", None)
        if topic is None or payload is None:
            logger.warning(
                "[Parse]: The topic or payload is none; topic: %s, payload: %s",
                topic,
                payload,
            )
            return
        topic_parts = topic.split("/")
        split_len = len(topic_parts)
        if split_len == 2:  # topics related to a cluster namely IS MQTT
            if topic_parts[1] == "meta":
                if "State" not in payload:
                    logger.warning(
                        "[Parse]: Received a meta message not including state of the instrument server '%s'",
                        topic_parts[0].decode("utf-8"),
                    )
                    return
                if payload.get("State", None) is None:
                    logger.warning(
                        "[Parse]: Received a meta message from the instrument server '%s', including a none state",
                        topic_parts[0],
                    )
                    return
                if payload.get("State", None) in (2, 1):
                    folder_hosts_history = f"{HOSTS_FOLDER_HISTORY}{os.path.sep}"
                    filename_ = fr"{folder_hosts_history}{topic_parts[0]}"
                    logger.info(
                        "[Parse]: To write the properties of this cluster (%s) into file system",
                        topic_parts[0],
                    )
                    _msg = {
                        "PAR": {
                            "is_id": topic_parts[0],
                            "payload": payload,
                        },
                    }
                    if topic_parts[0] not in self.connected_instruments:
                        open(filename_, "w+")
                        self._add_host(_msg)
                    else:
                        self._update_host(_msg)
                elif payload.get("State", None) == 0:
                    if topic_parts[0] in self.connected_instruments:
                        _msg = {
                            "PAR": {
                                "is_id": topic_parts[0],
                            },
                        }
                        logger.info(
                            "[Parse]: To remove the cluster (%s) from file system",
                            topic_parts[0],
                        )
                        self._rm_host(_msg)
                    else:
                        logger.warning(
                            "[Parse]: SARAD_Subscriber has received disconnection message from an unknown instrument server (%s)",
                            topic_parts[0],
                        )
                else:
                    logger.warning(
                        "[Parse]: SARAD_Subscriber has received a meta message of an unknown cluster (%s)",
                        topic_parts[0],
                    )
            else:
                logger.warning(
                    "[Parse]: SARAD_Subscriber has received an illegal message '%s' under the topic '%s' from the instrument server '%s'",
                    topic,
                    payload,
                    topic_parts[0],
                )
        elif split_len == 3:  # topics related to an instrument
            if topic_parts[2] == "meta":
                if "State" not in payload:
                    logger.warning(
                        "[Parse]: Received a meta message not including state of the instrument '%s' controlled by the instrument server '%s'",
                        topic_parts[1],
                        topic_parts[0],
                    )
                    return
                if payload.get("State", None) is None:
                    logger.warning(
                        "[Parse]: Received a meta message from the instrument '%s' controlled by the instrument server '%s', including a none state",
                        topic_parts[1],
                        topic_parts[0],
                    )
                    return
                if payload.get("State", None) in (2, 1):
                    if (
                        topic_parts[0] in self.connected_instruments
                    ):  # the IS MQTT has been added, namely topic_parts[0] in self.connected_instrument
                        logger.info(
                            "[Parse]: To write the properties of this instrument (%s) into file system",
                            topic_parts[1],
                        )
                        instr = {
                            "is_id": topic_parts[0],
                            "instr_id": topic_parts[1],
                            "payload": payload,
                        }
                        if not (
                            topic_parts[1] in self.connected_instruments[topic_parts[0]]
                        ):
                            self._add_instr(instr)
                        else:
                            self._update_instr(instr)
                    else:
                        logger.warning(
                            "[Parse]: Received a meta message of an instrument '%s' that is controlled by an instrument server '%s' not added before",
                            topic_parts[1],
                            topic_parts[0],
                        )
                elif payload.get("State", None) == "0":
                    logger.info("disconnection message")
                    if (topic_parts[0] in self.connected_instruments) and (
                        topic_parts[1] in self.connected_instruments[topic_parts[0]]
                    ):
                        logger.info(
                            "[Parse]: To remove the instrument: %s under the IS: %s",
                            topic_parts[1],
                            topic_parts[0],
                        )
                        _msg = {
                            "PAR": {
                                "is_id": topic_parts[0],
                                "instr_id": topic_parts[1],
                            },
                        }
                        self._rm_instr(_msg)
                    else:
                        logger.warning(
                            "[Parse]: SARAD_Subscriber has received disconnection message from an unknown instrument (%s) controlled by the IS (%s)",
                            topic_parts[1],
                            topic_parts[0],
                        )
                else:
                    logger.warning(
                        "[Parse]: SARAD_Subscriber has received unknown state of an unknown instrument (%s) controlled by the IS (%s)",
                        topic_parts[1],
                        topic_parts[0],
                    )

            else:  # Illeagl topics
                logger.warning(
                    "[Parse]: Receive unknown message '%s' under the illegal topic '%s'}, which is related to the instrument '%s'",
                    payload,
                    topic,
                    topic_parts[1],
                )
        else:  # Acceptable topics can be divided into 2 or 3 parts by '/'
            logger.warning(
                "[Parse]: Receive unknown message '%s' under the topic '%s' in illegal format, which is related to the instrument '%s'",
                payload,
                topic,
                topic_parts[1],
            )

    def on_connect(self, client, userdata, flags, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        logger.info("on_connect")
        if result_code == 0:
            self.is_connected = True
            logger.info("[on_connect]: Connected with MQTT broker.")
            self._subscribe("+/meta", 0)
        else:
            self.is_connected = False
            logger.info(
                "[on_connect]: Connection to MQTT self.mqtt_broker failed. result_code=%s",
                result_code,
            )

    def on_disconnect(self, client, userdata, result_code):
        # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        logger.warning("on_disconnect")
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.info(
                "[on_disconnect]: Disconnection from MQTT-broker ungracefully. result_code=%s",
                result_code,
            )
        else:
            self.ungr_disconn = 0
            logger.info("[on_disconnect]: Gracefully disconnected from MQTT-broker.")
        self.is_connected = False

    def on_subscribe(self, _client, _userdata, mid, _grant_qos):
        """Here should be a docstring."""
        logger.info("[on_subscribe]: mid is %s", mid)
        logger.info("stored mid is %s", self.mid["SUBSCRIBE"])
        if mid == self.mid["SUBSCRIBE"]:
            logger.info("Subscribed to the topic successfully!\n")

    def on_unsubscribe(self, _client, _userdata, mid):
        """Here should be a docstring."""
        logger.info("[on_unsubscribe]: mid is %s", mid)
        logger.info("[on_unsubscribe]: stored mid is %s", self.mid["UNSUBSCRIBE"])
        if mid == self.mid["UNSUBSCRIBE"]:
            logger.info("[on_unsubscribe]: Unsubscribed to the topic successfully!")

    def on_message(self, _client, _userdata, message):
        """Here should be a docstring."""
        logger.info("message received: %s", str(message.payload.decode("utf-8")))
        logger.info("message topic: %s", message.topic)
        logger.info("message qos: %s", message.qos)
        logger.info("message retain flag: %s", message.retain)
        if message.payload is None:
            logger.error("The payload is none")
        else:
            msg_buf = {
                "CMD": "PARSE",
                "PAR": {
                    "topic": message.topic,
                    "payload": json.loads(message.payload),
                },
            }
            self._parse(msg_buf)

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("[Disconnect]: To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.info("[Disconnect]: Already disconnected ungracefully")
        logger.info("[Disconnect]: To stop the MQTT thread!")
        self.mqttc.loop_stop()

    def _subscribe(self, topic: str, qos: int) -> dict:
        logger.info("Work state: subscribe")
        result_code, self.mid["SUBSCRIBE"] = self.mqttc.subscribe(topic, qos)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning(
                "[Subscribe]: Subscribe failed; result code is: %s", result_code
            )
            return {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["SUBSCRIBE"]["ERROR_CODE"],
            }
        return {
            "RETURN": "SUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }

    def _unsubscribe(self, topic: str) -> dict:
        result_code, self.mid["UNSUBSCRIBE"] = self.mqttc.unsubscribe(topic)
        if result_code != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Unsubscribe failed; result code is: %s", result_code)
            return {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.RETURN_MESSAGES["UNSUBSCRIBE"]["ERROR_CODE"],
            }
        return {
            "RETURN": "UNSUBSCRIBE",
            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        }
