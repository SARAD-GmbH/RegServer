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
from pathlib import Path

import registrationserver2
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.mqtt.message import \
    RETURN_MESSAGES  # , MQTT_ACTOR_REQUESTs, MQTT_ACTOR_ADRs, IS_ID_LIST
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from registrationserver2.modules.mqtt.mqtt_client_actor import MqttClientActor
from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem, WakeupMessage

logger.info("%s -> %s", __package__, __file__)


class SaradMqttSubscriber(Actor):
    """
    classdocs

    Instr_CONN_History is mainly used for distinguishing __add_instr__() and __update_instr__().

    Struture of instr_conn_history:
    MQTT_ACTOR_ADRs = {
       IS1_ID: {
           Instr_ID11 : {
               # this instrument has connected but its description message
               # is not added -> __add_instr__()
               "Status": "Not_added",
               "Actor": <Name of the MQTT Actor>,
           }
           Instr_ID12 : {
               # this instrument has connected and its description message
               # is added -> __update_instr__()
               "Status": "Added",
               "Actor": <Name of the MQTT Actor>,
           }
           #Instr_ID13 : {
                 # this instrument has disconnected but the link
                 # to its description message is not removed -> __rm_instr__()
           #    "Status": "Not_removed",
           #    "Actor": <Name of the MQTT Actor>,
           #}
           Instr_ID14 : {
                # this instrument has disconnected and the link
                # to its description message is removed, once connected -> "Not_added"
               "Status": "Removed",
               "Actor": <Name of the MQTT Actor>,
           }
           ...
        },
        IS2_ID: {
           ...
        },
        ...
    }
    """

    ACCEPTED_COMMANDS = {
        # "KILL": "_kill",  # Kill this actor itself
        "SETUP": "_setup",
        # Delete the link of the description file of a host from "available" to "history"
        # "RM_HOST": "_rm_host",
        # Create the link of the description file of a host from "available" to "history"
        # "ADD_HOST": "_add_host",
        # Delete the link of the description file of an instrument from "available" to "history"
        # "RM_DEVICE": "_rm_instr",
        # Update the description file of a host
        # "UP_HOST": "_update_host",
        # Delete the link of the description file of a instrument from "available" to "history"
        # "ADD_DEVICE": "_add_instr",
        # Update the description file of an instrument
        # "UP_DEVICE": "_update_instr",
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
        self.instr_conn_history = {}
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
            is_id not in self.instr_conn_history.keys()
            or instr_id not in self.instr_conn_history[is_id].keys()
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
        self.instr_conn_history[is_id][instr_id]["Actor"] = name_
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
                self.instr_conn_history[is_id][instr_id]["Status"] = "Removed"
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
                self.instr_conn_history[is_id][instr_id]["Status"] = "Removed"
                return
            logger.info(
                "[Add Instrument]: Add the information of the instrument and create the actor '%s' for it successfully",
                name_,
            )
            self.instr_conn_history[is_id][instr_id]["Status"] = "Added"
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
            is_id not in self.instr_conn_history.keys()
            or instr_id not in self.instr_conn_history[is_id].keys()
        ):
            logger.warning(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.instr_conn_history[is_id][instr_id]["Actor"]
        with self.__lock:
            logger.info("[Remove]: Instrument ID - '%s'", instr_id)
            this_actor = ActorSystem().createActor(MqttActor, globalName=name_)
            kill_return = ActorSystem().ask(this_actor, ActorExitRequest())
            if not kill_return["ERROR_CODE"] == RETURN_MESSAGES["OK"]["ERROR_CODE"]:
                logger.critical("Killing the device actor failed.")
                return
            del self.instr_conn_history[is_id][instr_id]
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
            is_id not in self.instr_conn_history.keys()
            or instr_id not in self.instr_conn_history[is_id].keys()
        ):
            logger.warning(RETURN_MESSAGES["INSTRUMENT_UNKNOWN"])
            return
        name_ = self.instr_conn_history[is_id][instr_id]["Actor"]
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
                self.instr_conn_history[is_id][instr_id]["Status"] = "Removed"
                return
            logger.info(
                "[Update Instrument]: Update the information of the instrument successfully, which has a device actor '%s'",
                name_,
            )
            self.instr_conn_history[is_id][instr_id]["Status"] = "Added"
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
            for _instr_id in self.instr_conn_history[is_id].keys():
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
            if os.path.exists(filename):
                os.remove(filename)
        logger.info(
            "[Remove Host]: Remove the information of the instrument server successfully, the ID of which is '%s'",
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
        for _is_id in self.instr_conn_history.keys():
            logger.info("To remove the instrument server with ID '%s'", _is_id)
            self._rm_host({"CMD": "RM_HOST", "PAR": {"is_id": _is_id}})
        self.instr_conn_history = None
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
        logger.info("Subscriber's address is:")
        logger.info(self.myAddress)
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
            return
        if self.mqtt_broker is None:
            self.mqtt_broker = "127.0.0.1"
            logger.infor("Using the local host: 127.0.0.1")
        if self.port is None:
            self.port = 1883
            logger.info("Using the ddefault port: 1883")
        self.my_client = self.createActor(
            MqttClientActor, globalName="sarad_subscriber.mqtt.client_actor"
        )
        lwt_msg = {
            "lwt_topic": "test1/connect",
            "lwt_payload": "0",
            "lwt_qos": 0,
        }
        ask_msg = {
            "CMD": "SETUP",
            "PAR": {
                "parent_adr": self.myAddress,
                "client_id": self.mqtt_cid,
                "mqtt_broker": self.mqtt_broker,
                "port": self.port,
                "LWT": lwt_msg,
            },
        }
        ask_return = ActorSystem().ask(self.my_client, ask_msg)
        logger.info("ask return: %s", ask_return)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor. Kill this client actor.")
            ActorSystem().tell(self.my_client, ActorExitRequest())
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
                },
            )
            return
        """ask_msg = {
            "CMD": "CONNECT",
        }
        ask_return = ActorSystem().ask(self.my_client, ask_msg)
        if not ask_return["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor. Kill this client actor.")
            ActorSystem().tell(self.my_client, ActorExitRequest())
            self.send(sender, {"RETURN": "SETUP", "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"]})
            return
        """
        ask_msg = {
            "CMD": "UNSUBSCRIBE",
            "PAR": {
                "INFO": ["+/connected", "+/meta", "+/+/connected", "+/+/meta"],
            },
        }
        ask_return = ActorSystem().ask(self.my_client, ask_msg)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor. Kill this client actor.")
            ActorSystem().tell(self.my_client, ActorExitRequest())
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
                },
            )
            return

        ask_msg = {
            "CMD": "SUBSCRIBE",
            "PAR": {
                "INFO": [
                    ("+/connected", 0),
                    ("+/meta", 0),
                    ("+/+/connected", 0),
                    ("+/+/meta", 0),
                ],
            },
        }
        ask_return = ActorSystem().ask(self.my_client, ask_msg)
        if not ask_return["ERROR_CODE"] in (
            RETURN_MESSAGES["OK"]["ERROR_CODE"],
            RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
        ):
            logger.critical("Failed to setup the client actor. Kill this client actor.")
            ActorSystem().tell(self.my_client, ActorExitRequest())
            self.send(
                sender,
                {
                    "RETURN": "SETUP",
                    "ERROR_CODE": RETURN_MESSAGES["SETUP_FAILURE"]["ERROR_CODE"],
                },
            )
            return
        logger.info("Let the client actor stay at standby state")
        self.send(self.my_client, {"CMD": "STANDBY", "PAR": None})
        self.send(
            sender,
            {
                "RETURN": "SETUP",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            },
        )
        return

    def _parse(self, msg, sender) -> None:
        logger.info("PARSE")
        if sender != self.my_client:
            logger.warning(
                "Received a MQTT message '%s' from an unknown sender '%s'", msg, sender
            )
            # self.send(sender, {"RETURN": "PARSE", "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_SENDER"]["ERROR_CODE"]})
            return
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
            if topic_parts[1] == "connected":
                if payload in ("2", "1"):
                    filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                    if not Path(filename_).is_file():
                        open(filename_, "w+")
                elif payload == "0":
                    filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                    if Path(filename_).is_file():
                        next_msg = {
                            "CMD": "RM_HOST",
                            "PAR": {
                                "is_id": topic_parts[0],
                            },
                        }
                        logger.info(
                            "[RM_HOST]\tTo remove the cluster (%s) from file system",
                            topic_parts[0],
                        )
                        self.send(self.myAddress, next_msg)
                    else:
                        logger.warning(
                            "SARAD_Subscriber has received disconnection message from an unknown instrument server (%s)",
                            topic_parts[0],
                        )
                else:
                    logger.warning(
                        "SARAD_Subscriber has received connection state of an unknown cluster (%s)",
                        topic_parts[0],
                    )
            elif topic_parts[1] == "meta":
                filename_ = fr"{self.__folder2_history}{topic_parts[0]}"
                if Path(filename_).is_file():  # if this file exists
                    next_msg = {
                        "CMD": None,
                        "PAR": {
                            "is_id": topic_parts[0],
                            "payload": payload,
                        },
                    }
                    if os.stat(filename_).st_size == 0:  # if this file is empty
                        next_msg["CMD"] = "ADD_HOST"
                    else:
                        next_msg["CMD"] = "UP_HOST"
                    logger.info(
                        "[%s]: To write the properties of this cluster (%s) into file system",
                        next_msg["CMD"],
                        topic_parts[0],
                    )
                    self.send(self.myAddress, next_msg)
                else:
                    logger.warning(
                        "SARAD_Subscriber has received meta message of an unknown cluster (%s)",
                        topic_parts[0],
                    )
            elif split_len == 3:  # topics related to an instrument
                if topic_parts[2] == "connected":
                    if payload in ("2", "1"):
                        if (
                            topic_parts[0] in self.instr_conn_history.keys()
                        ):  # the IS MQTT has been added
                            if (
                                topic_parts[1]
                                in self.instr_conn_history[topic_parts[0]].keys()
                            ):
                                if (
                                    self.instr_conn_history[topic_parts[0]][
                                        topic_parts[1]
                                    ]["Status"]
                                    == "Removed"
                                ):
                                    self.instr_conn_history[topic_parts[0]][
                                        topic_parts[1]
                                    ]["Status"] == "Not_added"
                            else:
                                self.instr_conn_history[topic_parts[0]][topic_parts[1]][
                                    "Status"
                                ] == "Not_added"
                        else:
                            self.instr_conn_history[topic_parts[0]] = {}
                            self.instr_conn_history[topic_parts[0]][topic_parts[1]][
                                "Status"
                            ] == "Not_added"
                    elif payload == "0":
                        logger.info("disconnection message")
                        if (topic_parts[0] in self.instr_conn_history.keys()) and (
                            topic_parts[1]
                            in self.instr_conn_history[topic_parts[0]].keys()
                        ):
                            next_msg = {
                                "CMD": "RM_DEVICE",
                                "PAR": {
                                    "is_id": topic_parts[0],
                                    "instr_id": topic_parts[1],
                                },
                            }
                            logger.info(
                                "[RM_DEVICE]: To remove the instrument: %s under the IS: %s",
                                topic_parts[1],
                                topic_parts[0],
                            )
                            self.send(self.myAddress, next_msg)
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
                elif topic_parts[2] == "meta":
                    if (topic_parts[0] in self.instr_conn_history.keys()) and (
                        topic_parts[1] in self.instr_conn_history[topic_parts[0]].keys()
                    ):
                        if (
                            self.instr_conn_history[topic_parts[0]][topic_parts[1]][
                                "Status"
                            ]
                            != "Not_added"
                            and self.instr_conn_history[topic_parts[0]][topic_parts[1]][
                                "Status"
                            ]
                            != "Added"
                        ):
                            logger.warning(
                                "Receive unknown message '%s' under the topic (%s)",
                                payload,
                                topic,
                            )
                        else:
                            next_msg = {
                                "CMD": None,
                                "PAR": {
                                    "is_id": topic_parts[0],
                                    "instr_id": topic_parts[1],
                                    "payload": payload,
                                },
                            }
                            if (
                                self.instr_conn_history[topic_parts[0]][topic_parts[1]][
                                    "Status"
                                ]
                                == "Not_added"
                            ):
                                next_msg["CMD"] = "ADD_DEVICE"
                            else:
                                next_msg["CMD"] = "UP_DEVICE"
                            logger.info(
                                "[%s]: To write the properties of this instrument (%s) into file system",
                                next_msg["CMD"],
                                topic_parts[1],
                            )
                            self.send(self.myAddress, next_msg)
                    else:
                        logger.warning(
                            "Receive unknown meta message '%s' under the topic '%s'",
                            payload,
                            topic,
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
            time.sleep(1)
        # self.wakeupAfter(datetime.timedelta(seconds=1), payload="Parse")


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
            },
        },
    )
    if ask_return["ERROR_CODE"] in (
        RETURN_MESSAGES["OK"]["ERROR_CODE"],
        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
    ):
        logger.info("SARAD MQTT Subscriber is setup correctly!")
        input("Press Enter to End")
        ActorSystem().tell(sarad_mqtt_subscriber, ActorExitRequest())
        logger.info("!")
    else:
        logger.warning("SARAD MQTT Subscriber is not setup!")
        logger.error(ask_return)
        input("Press Enter to End")
        logger.info("!!")
    ActorSystem().shutdown()


if __name__ == "__main__":
    __test__()
