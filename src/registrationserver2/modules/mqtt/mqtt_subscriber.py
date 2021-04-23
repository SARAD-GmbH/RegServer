"""Listening for MQTT topics announcing the existance of a new SARAD instrument
in the MQTT network

Created
    2021-03-10

Author
    Yang, Yixiang

.. uml :: uml-mqtt_subscriber.puml

Todo:
    * uml-mqtt_subscriber.puml is only a copy of uml-mdns_listener.puml. It has to
      be updated.
    * too many lines of code

"""
# import json
import os
import threading
import time
import traceback
import paho.mqtt.client as MQTT  # type: ignore
from pathlib import Path
from overrides import overrides  # type: ignore

import registrationserver2
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES  # , MQTT_ACTOR_REQUESTs, MQTT_ACTOR_ADRs, IS_ID_LIST
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
#from registrationserver2.modules.mqtt.mqtt_client_actor import MqttClientActor
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem, WakeupMessage

logger.info("%s -> %s", __package__, __file__)


class SaradMqttSubscriber(Actor):
    """
    classdocs

    connected_instruments is mainly used for distinguishing __add_instr__() and __update_instr__().
    
    Basic flows:
    1) when an IS MQTT 'IS1_ID' is connected -> _add_host, connected_instruments[IS1_ID] = []
    2) when the ID of this IS MQTT is a key of connected_instruments -> _update_host
    3) disconnection and the ID is a key -> _rm_host, del connected_instruments[IS1_ID]
    4) when an instrument 'Instr_ID11' is connected & the ID of its IS is a key -> _add_instr, connected_istruments[IS1_ID].append(Instr_ID11)
    5) when the ID of this instrument exists in the list mapping the ID of its IS MQTT -> _update_instr
    6) disconnection and the instrument ID exists in the list -> _rm_host 

    Struture of connected_instruments:
    connected_instruments = {
       IS1_ID: [
           Instr_ID11,
           Instr_ID12,
           Instr_ID13,
           ...
       ],
       IS2_ID: [
           ...
       ],
        ...
    }
    """

    ACCEPTED_COMMANDS = {
        # "KILL": "_kill",  # Kill this actor itself
        "SETUP": "_setup",
        # Delete the link of the description file of a host from "available" to "history"
        "RM_HOST": "_rm_host",
        # Create the link of the description file of a host from "available" to "history"
        "ADD_HOST": "_add_host",
        # Delete the link of the description file of an instrument from "available" to "history"
        "RM_DEVICE": "_rm_instr",
        # Update the description file of a host
        "UP_HOST": "_update_host",
        # Delete the link of the description file of a instrument from "available" to "history"
        "ADD_DEVICE": "_add_instr",
        # Update the description file of an instrument
        "UP_DEVICE": "_update_instr",
        "PARSE": "_parse",
    }
    ACCEPTED_RETURNS = {
        # "SEND": "_receive_loop",
    }

    @overrides
    def __init__(self):
        super().__init__()
        self.mqtt_cid: str = None  # MQTT client Id
        self.mqtt_broker: str = None
        self.my_client = None
        self.port = None
        self.connected_instruments = {}
        self.work_state = "IDLE"
        self.ungr_disconn = 2
        self.error_code_switcher = {
            "SETUP": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
            "CONNECT": RETURN_MESSAGES["CONNECTION_FAILURE"]["ERROR_CODE"],
            "SUBSCRIBE": RETURN_MESSAGES["SUBSCRIBE_FAILURE"]["ERROR_CODE"],
            "UNSUBSCRIBE": RETURN_MESSAGES["UNSUBSCRIBE_FAILURE"]["ERROR_CODE"],
        }
        self.flag_switcher = {
            "CONNECT": None,
            "SUBSCRIBE": None,
            "DISCONNECT": None,
            "UNSUBSCRIBE": None,
        }
        self.mid = {
            "SUBSCRIBE": None,
            "UNSUBSCRIBE": None,
        }
        self.__lock = threading.Lock()
        with self.__lock:
            self.__folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
            self.__folder_available = (
                f"{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}"
            )
            self.__folder2_history = (
                f"{registrationserver2.HOSTS_FOLDER_HISTORY}{os.path.sep}"
            )
            self.__folder2_available = (
                f"{registrationserver2.HOSTS_FOLDER_AVAILABLE}{os.path.sep}"
            )
            if not os.path.exists(self.__folder_history):
                os.makedirs(self.__folder_history)
            if not os.path.exists(self.__folder_available):
                os.makedirs(self.__folder_available)
            if not os.path.exists(self.__folder2_history):
                os.makedirs(self.__folder2_history)
            if not os.path.exists(self.__folder2_available):
                os.makedirs(self.__folder2_available)
            logger.debug("For instruments, output to: %s", self.__folder_history)
            logger.debug("For hosts, output to: %s", self.__folder2_history)

    @overrides
    def receiveMessage(self, msg, sender):
        """ Handles received Actor messages / verification of the message format"""
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, dict):
            return_key = msg.get("RETURN", None)
            cmd_key = msg.get("CMD", None)
            if ((return_key is None) and (cmd_key is None)) or (
                (return_key is not None) and (cmd_key is not None)
            ):
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_MESSAGE"])
                return
            if cmd_key is not None:
                cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
                if cmd_function is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.", msg, sender
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                    )
                    return
                if getattr(self, cmd_function, None) is None:
                    logger.critical(
                        "Received %s from %s. This should never happen.", msg, sender
                    )
                    logger.critical(
                        RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                    )
                    return
                getattr(self, cmd_function)(msg, sender)
            elif return_key is not None:
                return_function = self.ACCEPTED_RETURNS.get(return_key, None)
                if return_function is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                if getattr(self, return_function, None) is None:
                    logger.debug("Received return %s from %s.", msg, sender)
                    return
                getattr(self, return_function)(msg, sender)
        else:
            if isinstance(msg, ActorExitRequest):
                self._kill(msg, sender)
                return
            if isinstance(msg, WakeupMessage):
                if msg.payload == "Parse":
                    self.__mqtt_parse(None, None)
                else:
                    logger.debug("Received an unknown wakeup message")
                return
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return

    def _add_instr(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        instr_id = msg.get("PAR", None).get("instr_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (instr_id is None) or (data is None):
            logger.warning(
                "[Add Instrument]: one or both of the Instrument Server ID and Instrument ID"
                " are none or the meta message is none"
            )
            return
        if (
            is_id not in self.connected_instruments.keys()
            or instr_id not in self.connected_instruments[is_id].keys()
        ):
            logger.warning(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        family_ = msg.get("PAR", None).get("payload", None).get("Family", None)
        type_ = msg.get("PAR", None).get("payload", None).get("Type", None)
        if family_ is None or type_ is None:
            logger.warning(
                "[Add Instrument]: One or both of the family and type of the instrument are missed"
            )
            return
        if family_ == 1:
            sarad_type = "sarad-1688"
        elif family_ == 2:
            sarad_type = "sarad-1688"
        elif family_ == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.warning(
                "[Add]: Found Unknown family (index: %s) of instrument", family_
            )
            return
        name_ = instr_id + "." + sarad_type + ".mqtt"
        self.connected_instruments[is_id][instr_id]["Actor"] = name_
        with self.__lock:
            logger.info("[Add]:Instrument ID - '%s'", instr_id)

            this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
            setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": data})
            logger.info(setup_return)
            if not setup_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.warning(setup_return)
                logger.critical(
                    "Failed to setup a new MQTT Actor. Kill this device actor."
                )
                self.send(this_actor, ActorExitRequest())
                self.connected_instruments[is_id][instr_id]["Status"] = "Removed"
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
            if not prep_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.warning(prep_return)
                logger.critical("This MQTT Actor failed to prepare itself. Kill it.")
                self.send(this_actor, ActorExitRequest())
                self.connected_instruments[is_id][instr_id]["Status"] = "Removed"
                return
            logger.info(
                "[Add Instrument]: Add the information of the instrument and create the actor '%s' for it successfully",
                name_,
            )
            self.connected_instruments[is_id][instr_id]["Status"] = "Added"
            return

    def _rm_instr(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        instr_id = msg.get("PAR", None).get("instr_id", None)
        if (is_id is None) or (instr_id is None):
            logger.warning(
                "[Remove Instrument]: one or both of the Instrument Server ID "
                "and Instrument ID are none"
            )
            return
        if (
            is_id not in self.connected_instruments.keys()
            or instr_id not in self.connected_instruments[is_id].keys()
        ):
            logger.warning(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.connected_instruments[is_id][instr_id]["Actor"]
        with self.__lock:
            logger.info("[Remove]: Instrument ID - '%s'", instr_id)
            this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
            kill_return = ActorSystem().ask(this_actor, ActorExitRequest())
            if not kill_return["ERROR_CODE"] == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
                logger.critical("Killing the device actor failed.")
                return
            del self.connected_instruments[is_id][instr_id]
            logger.info(
                "[Remove Instrument]: Remove the information of the instrument and kill the actor '%s' for it successfully",
                name_,
            )
            return

    def _update_instr(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        instr_id = msg.get("PAR", None).get("instr_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (instr_id is None) or (data is None):
            logger.warning(
                "[Update Instrument]: one or both of the Instrument Server ID "
                "and Instrument ID are none or the meta message is none"
            )
            return
        if (
            is_id not in self.connected_instruments.keys()
            or instr_id not in self.connected_instruments[is_id].keys()
        ):
            logger.warning(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.connected_instruments[is_id][instr_id]["Actor"]
        with self.__lock:
            logger.info("[Update]: Instrument ID - '%s'", instr_id)
            this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
            setup_return = ActorSystem().ask(this_actor, {"CMD": "SETUP", "PAR": data})
            logger.info(setup_return)
            if not setup_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            ):
                logger.warning(setup_return)
                logger.critical(
                    "Failed to setup a new MQTT Actor. Kill this device actor."
                )
                self.send(this_actor, ActorExitRequest())
                self.connected_instruments[is_id][instr_id]["Status"] = "Removed"
                return
            logger.info(
                "[Update Instrument]: Update the information of the instrument successfully, which has a device actor '%s'",
                name_,
            )
            self.connected_instruments[is_id][instr_id]["Status"] = "Added"
            return

    def _add_host(self, msg: dict) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (data is None):
            logger.warning(
                "[Add Host]: one or both of the Instrument Server ID and the meta message are none"
            )
            return
        with self.__lock:
            logger.info(
                "[Add]: Found a new connected host with Instrument Server ID '%s'",
                is_id,
            )
            filename = fr"{self.__folder2_history}{is_id}"
            link = fr"{self.__folder2_available}{is_id}"
            try:
                with open(filename, "w+") as file_stream:
                    file_stream.write(data)
                if not os.path.exists(link):
                    logger.info("Linking %s to %s", link, filename)
                    os.link(filename, link)
                self.connected_instruments[is_id] = []
                _msg = {
                    "CMD": "SUBSCRIBE",
                    "PAR": {
                        "INFO": [
                            (is_id+"/+/meta", 0),
                        ],
                    },
                }
                """
                while not self._subscribe(_msg)["ERROR_CODE"] in (
                    RETURN_MESSAGES["OK"]["ERROR_CODE"],
                    RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                ):
                    time.sleep(0.01)
                logger.info("Successfully subscribed to the '%s/+/meta' topic", is_id)
                """
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    "[Add]:\t %s\t%s\t%s\t%s",
                    type(error),
                    error,
                    vars(error) if isinstance(error, dict) else "-",
                    traceback.format_exc(),
                )
                return
            except:  # pylint: disable=W0702
                logger.error(
                    "[Add]: Could not write properties of instrument server with ID: %s",
                    is_id,
                )
                return
        logger.info(
            "[Add Host]: Add the information of the instrument server successfully, the ID of which is '%s'",
            is_id,
        )
        return

    def _rm_host(self, msg: dict, _sender) -> None:
        is_id = msg.get("PAR", None).get("is_id", None)
        data = msg.get("PAR", None).get("payload")
        if (is_id is None) or (data is None):
            logger.warning(
                "[Remove Host]: one or both of the Instrument Server ID "
                "and the meta message are none"
            )
            return
        with self.__lock:
            logger.info("[Remove]: Remove a host with Instrument Server ID '%s'", is_id)
            logger.info(
                "To kill all the instrument controlled by the instrument server with ID '%s'",
                is_id,
            )
            for _instr_id in self.connected_instruments[is_id].keys():
                rm_msg = {
                    "PAR": {
                        "is_id": is_id,
                        "instr_id": _instr_id,
                    }
                }
                logger.info("To kill the instrument with ID '%s'", _instr_id)
                self._rm_instr(rm_msg)
            filename = fr"{self.__folder2_history}{is_id}"
            link = fr"{self.__folder2_available}{is_id}"
            if os.path.exists(link):
                os.unlink(link)
        logger.info(
            "[Remove Host]: Remove the link to the information of the instrument server successfully, the ID of which is '%s'",
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
        with self.__lock:
            logger.info(
                "[Update]: Update a already connected host with Instrument Server ID '%s'",
                is_id,
            )
            filename = fr"{self.__folder2_history}{is_id}"
            link = fr"{self.__folder2_available}{is_id}"
            try:
                with open(filename, "w+") as file_stream:
                    file_stream.write(data)
                if not os.path.exists(link):
                    logger.info("Linking %s to %s", link, filename)
                    os.link(filename, link)
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    "[Update]:\t %s\t%s\t%s\t%s",
                    type(error),
                    error,
                    vars(error) if isinstance(error, dict) else "-",
                    traceback.format_exc(),
                )
                return
            except:  # pylint: disable=W0702
                logger.error(
                    "[Update]: Could not write properties of instrument server with ID: %s",
                    is_id,
                )
                return
        logger.info(
            "[Update Host]: Remove the information of the instrument server successfully, the ID of which is '%s'",
            is_id,
        )
        return
    

    def _kill(self, _msg, sender):
        self.send(self.my_client, ActorExitRequest())
        for _is_id in self.connected_instruments.keys():
            logger.info("To remove the instrument server with ID '%s'", _is_id)
            self._rm_host({"CMD": "RM_HOST", "PAR": {"is_id": _is_id}})
        self.connected_instruments = None
        if sender is not None:
            self.send(
                sender,
                {
                    "RETURN": "KILL",
                    "ERROR_CODE": RETURN_MESSAGES.get("OK_SKIPPED", None).get(
                        "ERROR_CODE", None
                    ),
                },
            )
        logger.info("Already killed the subscriber")

    def _setup(self, msg: dict, sender) -> None:
        self.work_state == "SETUP"
        logger.info("Subscriber's address is: %s", self.myAddress)
        self.mqtt_cid = msg.get("PAR", None).get("client_id", None)
        self.mqtt_broker = msg.get("PAR", None).get("mqtt_broker", None)
        self.port = msg.get("PAR", None).get("port", None)
        if self.mqtt_cid is None:
            self.mqtt_cid = "sarad_subscriber"
            logger.info(
                "[Setup]: The client ID of the MQTT Subscriber is not given, then the default client ID '%s' would be used",
                self.mqtt_cid,
            )
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            self.work_state == "STANDBY"
            return
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
            logger.infor("Using the local host: 127.0.0.1")
        if self.port is None:
            self.port = 1883
            logger.info("Using the ddefault port: 1883")
        _re = self._connect(False)
        if not _re["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical(
                "Failed to setup the client actor because of failed connection. "
            )
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": _re["ERROR_CODE"],
                },
            )
            return
        logger.info("[CONN]: The client '%s': %s", self.mqtt_cid, _re)
        time.sleep(0.01)
        _msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": ["+/meta", "+/+/meta"],
            },
        }
        _re = self._unsubscribe(_msg)
        if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor because of failed unsubscription.")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": _re["ERROR_CODE"]})
            return

        _msg = {
            "CMD": "SUBSCRIBE",
            "PAR": {
                "INFO": [
                    ("+/meta", 0),
                    ("+/+/meta", 0),
                ],
            },
        }
        _re = self._subscribe(_msg)
        if not _re["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor because of failed subscription.")
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": _re["ERROR_CODE"]})
            return

        self.send(
            sender,
            {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            },
        )
        self.work_state == "STANDBY"
        return

    def _parse(self, msg, sender) -> None:
        logger.info("PARSE")
        topic = msg.get("PAR", None).get("topic", None)
        payload = msg.get("PAR", None).get("payload", None)
        if topic is None or payload is None:
            logger.warning(
                "The topic or payload is none; topic: %s, payload: %s", topic, payload
            )
            return
        topic_parts = topic.split("/")
        split_len = len(topic_parts)
        if split_len == 2:  # topics related to a cluster namely IS MQTT
            if topic_parts[1] == "meta":
                if "State" not in payload:
                    logger.warning("Received a meta message not including state of the instrument server '%s'", topic_parts[0])
                    return
                if payload.get("State", None) is None:
                    logger.warning ("Received a meta message from the instrument server '%s', including a none state", topic_parts[0])
                    return
                if payload.get("State", None) in (2, 1):
                    filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                    logger.info(
                        "To write the properties of this cluster (%s) into file system",
                        topic_parts[0],
                    )
                    _msg = {
                        "CMD": None,
                        "PAR": {
                            "is_id": topic_parts[0],
                            "payload": payload,
                        },
                    }
                    if not Path(filename_).is_file():
                        open(filename_, "w+")
                        _msg["CMD"] = "ADD_HOST"
                    else:
                        _msg["CMD"] = "UP_HOST"
                    
                    self.send(self.myAddress, _msg)
                    return                        
                elif payload.get("State", None) == 0:
                    filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                    if Path(filename_).is_file():
                        _msg = {
                            "CMD": "RM_HOST",
                            "PAR": {
                                "is_id": topic_parts[0],
                            },
                        }
                        logger.info(
                            "[RM_HOST]\tTo remove the cluster (%s) from file system",
                            topic_parts[0],
                        )
                        self.send(self.myAddress, _msg)
                    else:
                        logger.warning(
                            "SARAD_Subscriber has received disconnection message from an unknown instrument server (%s)",
                            topic_parts[0],
                        )
                else:
                    logger.warning(
                        "SARAD_Subscriber has received a meta message of an unknown cluster (%s)",
                        topic_parts[0],
                    )
            else:
                logger.warning(
                    "SARAD_Subscriber has received an illegal message '%S' under the topic '%s' from the instrument server '%s'",
                    topic, payload, topic_parts[0],
                )
        elif split_len == 3:  # topics related to an instrument
            if topic_parts[2] == "meta":
                if "State" not in payload:
                    logger.warning("Received a meta message not including state of the instrument '%s' controlled by the instrument server '%S'", topic_parts[1], topic_parts[0])
                    return
                if payload.get("State", None) is None:
                    logger.warning ("Received a meta message from the instrument '%s' controlled by the instrument server '%S', including a none state", topic_parts[1], topic_parts[0])
                    return
                if payload.get("State", None) in (2, 1):
                    filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                    if Path(filename_).is_file():  # the IS MQTT has been added, namely topic_parts[0] in self.connected_instrument
                        logger.info(
                            "To write the properties of this instrument (%s) into file system",
                            topic_parts[1],
                        )
                        _msg = {
                            "CMD": None,
                            "PAR": {
                                "is_id": topic_parts[0],
                                "instr_id": topic_parts[1],
                                "payload": payload,
                            },
                        }
                        if not (
                            topic_parts[1]
                            in self.connected_instruments[topic_parts[0]]
                        ):
                            _msg["CMD"] = "ADD_DEVICE"
                        else:
                            _msg["CMD"] = "UP_DEVICE"
                        
                        self.send(self.myAddress, _msg)
                    else:
                        logger.warning("Received a meta message of an instrument '%s' that is controlled by an instrument server '%s' not added before", topic_parts[1], topic[0])
                elif payload.get("State", None)  == "0":
                    logger.info("disconnection message")
                    if (topic_parts[0] in self.connected_instruments) and (
                        topic_parts[1]
                        in self.connected_instruments[topic_parts[0]]
                    ):
                        logger.info(
                            "[RM_DEVICE]: To remove the instrument: %s under the IS: %s",
                            topic_parts[1],
                            topic_parts[0],
                        )
                        _msg = {
                            "CMD": "RM_DEVICE",
                            "PAR": {
                                "is_id": topic_parts[0],
                                "instr_id": topic_parts[1],
                            },
                        }                    
                        self.send(self.myAddress, _msg)
                    else:
                        logger.warning(
                            "SARAD_Subscriber has received disconnection message from an unknown instrument (%s) controlled by the IS (%s)",
                            topic_parts[1],
                            topic_parts[0],
                        )
                else:
                    logger.warning(
                        "SARAD_Subscriber has received unknown state of an unknown instrument (%s) controlled by the IS (%s)",
                        topic_parts[1],
                        topic_parts[0],
                    )
                
            else:  # Illeagl topics
                logger.warning(
                    "Receive unknown message '%s' under the illegal topic '%s'}, which is related to the instrument '%s'",
                    payload,
                    topic,
                    topic_parts[1],
                )
        else:  # Acceptable topics can be divided into 2 or 3 parts by '/'
            logger.warning(
                "Receive unknown message '%s' under the topic '%s' in illegal format, which is related to the instrument '%s'",
                payload,
                topic,
                topic_parts[1],
            )
    
    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        logger.warning("Disconnected")
        if result_code >= 1:
            self.ungr_disconn = 1
            logger.info(
                "Disconnection from MQTT-broker ungracefully. result_code=%s",
                result_code,
            )
            self._connect(None, None)
        else:
            self.ungr_disconn = 0
            logger.info("Gracefully disconnected from MQTT-broker.")
        self.flag_switcher["DISCONNECT"] = True
        # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")
        # logger.info("[Subscriber]\tTo kill the subscriber")
        # self.send(self.myAddress, ActorExitRequest())

    def on_publish(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_pub = 0
        logger.info("The message with Message-ID %d is published to the broker!\n", mid)
        logger.info("work state = %s", self.work_state)
        if self.work_state == "PUBLISH":
            logger.info("Publish: check the mid")
            if mid == self.mid[self.work_state]:
                logger.info("Publish: mid is matched")
                self.flag_switcher[self.work_state] = True

    def on_subscribe(self, _client, _userdata, mid, _grant_qos):
        """Here should be a docstring."""
        # self.rc_sub = 0
        logger.info("on_subscribe")
        logger.info("mid is %s", mid)
        logger.info("work state = %s", self.work_state)
        logger.info("stored mid is %s", self.mid[self.work_state])
        if self.work_state == "SUBSCRIBE" and mid == self.mid[self.work_state]:
            logger.info("Subscribed to the topic successfully!\n")
            self.flag_switcher[self.work_state] = True
        # self.wakeupAfter(datetime.timedelta(seconds=0.01), payload="STANDBY")

    def on_unsubscribe(self, _client, _userdata, mid):
        """Here should be a docstring."""
        # self.rc_uns = 0
        logger.info("on_unsubscribe")
        logger.info("mid is %s", mid)
        logger.info("work state = %s", self.work_state)
        logger.info("stored mid is %s", self.mid[self.work_state])
        if self.work_state == "UNSUBSCRIBE" and mid == self.mid[self.work_state]:
            logger.info("Unsubscribed to the topic successfully!\n")
            self.flag_switcher[self.work_state] = True

    def on_message(self, _client, _userdata, message):
        """Here should be a docstring."""
        logger.info("message received: %s", str(message.payload.decode("utf-8")))
        logger.info("message topic: %s", message.topic)
        logger.info("message qos: %s", message.qos)
        logger.info("message retain flag: %s", message.retain)
        msg_buf = {
            "topic": message.topic,
            "payload": message.payload,
        }
        self._parse(msg_buf)

                    
    def _connect(self, lwt_set: bool) -> dict:
        # logger.info("Work state: connect")
        self.work_state == "CONNECT"
        self.mqttc = MQTT.Client(self.mqtt_cid)

        self.mqttc.reinitialise()

        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe
        logger.info("Try to connect to the mqtt broker")
        if lwt_set:
            logger.info("Set will")
            self.mqttc.will_set(
                self.lwt_topic, payload=self.lwt_payload, qos=self.lwt_qos, retain=True
            )
        self.mqttc.connect(self.mqtt_broker, port=self.port)
        self.mqttc.loop_start()
        while True:
            if self.flag_switcher["CONNECT"] is not None:
                if self.flag_switcher[self.work_state]:
                    _re = {
                        "RETURN": "CONNECT",
                        "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                    }
                    break
                elif not self.flag_switcher["CONNECT"]:
                    _re = {
                        "RETURN": "CONNECT",
                        "ERROR_CODE": self.error_code_switcher["CONNECT"],
                    }
                    break
        self.work_state == "STANDBY"
        return _re

    def _disconnect(self):
        if self.ungr_disconn == 2:
            logger.info("To disconnect from the MQTT-broker!")
            self.mqttc.disconnect()
        elif self.ungr_disconn == 1 or self.ungr_disconn == 0:
            self.ungr_disconn = 2
            logger.info("Already disconnected")
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("Disconnection gracefully: %s", RETURN_MESSAGES.get("OK_SKIPPED"))

    def _subscribe(self, msg: dict) -> None:
        self.work_state == "SUBSCRIBE"
        logger.info("Work state: subscribe")
        if self.flag_switcher["DISCONNECT"]:
            logger.warning(
                "Failed to subscribe to the topic(s) because of disconnection"
            )
            _re = {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["SUBSCRIBE"],
            }
            self._connect(True, self.myAddress)
            self.work_state == "STANDBY"
            return _re
        sub_info = msg.get("PAR", None).get("INFO", None)
        if sub_info is None:
            logger.warning("[Subscribe]: the INFO for subscribe is none")
            _re = {
                "RETURN": "SUBSCRIBE",
                "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_CODE"],
            }
            self.work_state == "STANDBY"
            return _re
        if isinstance(sub_info, list):
            for ele in sub_info:
                if not isinstance(ele, tuple):
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list "
                        "while it contains a non-tuple element"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    self.work_state == "STANDBY"
                    return _re
                if len(ele) != 2:
                    logger.warning(
                        "[Subscribe]: the INFO for subscribe is a list while it contains "
                        "a tuple elemnt whose length is not equal to 2"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    self.work_state == "STANDBY"
                    return _re
                if len(ele) == 2 and ele[0] is None:
                    logger.warning(
                        "[Subscribe]: the first element of one tuple namely the 'topic' is None"
                    )
                    _re = {
                        "RETURN": "SUBSCRIBE",
                        "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"][
                            "ERROR_CODE"
                            ],
                    }
                    self.work_state == "STANDBY"
                    return _re
            info = self.mqttc.subscribe(sub_info)
            logger.info("Subscribe return: %s", info)
            if info[0] != MQTT.MQTT_ERR_SUCCESS:
                logger.warning("Subscribe failed; result code is: %s", info[0])
                _re = {
                    "RETURN": "SUBSCRIBE",
                    "ERROR_CODE": self.error_code_switcher["SUBSCRIBE"],
                }
            else:
                self.mid[self.work_state] = info[1]
                while True:
                    if self.flag_switcher["SUBSCRIBE"] != None:
                        if self.flag_switcher["SUBSCRIBE"]:
                            _re = {
                                "RETURN": "SUBSCRIBE",
                                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                                    "ERROR_CODE"
                                    ],
                            }
                            self.flag_switcher["SUBSCRIBE"] = None
                            break
                        if not self.flag_switcher["SUBSCRIBE"]:
                            _re = {
                                "RETURN": "SUBSCRIBE",
                                "ERROR_CODE": self.error_code_switcher["SUBSCRIBE"],
                            }
                            self.flag_switcher["SUBSCRIBE"] = None
                            break
            self.work_state == "STANDBY"
            return _re

    def _unsubscribe(self, msg: dict) -> dict:
        self.work_state == "UNSUBSCRIBE"
        self.mqtt_topic = msg.get("PAR", None).get("INFO", None)
        logger.info(self.mqtt_topic)
        if not self.flag_switcher["CONNECT"]:
            logger.warning(
                "Failed to unsubscribe to the topic(s) because of disconnection"
            )
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
            self._connect()
            return _re
        if (
            self.mqtt_topic is None
            and not isinstance(self.mqtt_topic, list)
            and not isinstance(self.mqtt_topic, str)
        ):
            logger.warning(
                "[Unsubscribe]: The topic is none or it is neither a string nor a list "
            )
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
            self.work_state == "STANDBY"
            return _re
        info = self.mqttc.unsubscribe(self.mqtt_topic)
        logger.info("Unsubscribe return: %s", info)
        if info[0] != MQTT.MQTT_ERR_SUCCESS:
            logger.warning("Unsubscribe failed; result code is: %s", info.rc)
            _re = {
                "RETURN": "UNSUBSCRIBE",
                "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
            }
        else:
            self.mid["UNSUBSCRIBE"] = info[1]
            while True:
                if self.flag_switcher["UNSUBSCRIBE"] is not None:
                    if self.flag_switcher["UNSUBSCRIBE"]:
                        _re = {
                            "RETURN": "UNSUBSCRIBE",
                            "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"][
                                "ERROR_CODE"
                                ],
                        }
                        self.flag_switcher["UNSUBSCRIBE"] = None
                        break
                    if not self.flag_switcher["UNSUBSCRIBE"]:
                        _re = {
                            "RETURN": "UNSUBSCRIBE",
                            "ERROR_CODE": self.error_code_switcher["UNSUBSCRIBE"],
                        }
                        self.flag_switcher["UNSUBSCRIBE"] = None
                        break
        self.work_state == "STANDBY"
        return _re
        



def __test__():
    # ActorSystem(
    #    systemBase=config["systemBase"],
    #    capabilities=config["capabilities"],
    # )
    logger.info("Subscriber")
    sarad_mqtt_subscriber = ActorSystem().createActor(
        SaradMqttSubscriber, globalName="SARAD_Subscriber"
    )
    ask_return = ActorSystem().ask(
        sarad_mqtt_subscriber,
        {
            "CMD": "SETUP",
            "PAR": {
                "client_id": "sarad-mqtt_subscriber-client",
                "mqtt_broker": "127.0.0.1",
                "port": 1883,
            },
        },
    )
    if ask_return["ERROR_CODE"] in (
        RETURN_MESSAGES["OK"]["ERROR_CODE"],
        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
    ):
        logger.info("SARAD MQTT Subscriber is setup correctly!")
        #input("Press Enter to End")
        #ActorSystem().tell(sarad_mqtt_subscriber, ActorExitRequest())
        logger.info("!")
    else:
        logger.warning("SARAD MQTT Subscriber is not setup!")
        logger.error(ask_return)
        #input("Press Enter to End")
        logger.info("!!")
    while True:
        input("Press Enter to End")
        break
    time.sleep(10)
    ActorSystem().tell(sarad_mqtt_subscriber, ActorExitRequest())
    time.sleep(10)
    ActorSystem().shutdown()


if __name__ == "__main__":
    __test__()
