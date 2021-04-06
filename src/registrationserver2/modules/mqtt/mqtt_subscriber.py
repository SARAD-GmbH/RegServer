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
import ctypes
# import json
import os
import queue
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

import paho.mqtt.client as MQTT  # type: ignore
import registrationserver2
# import traceback
# import traceback
import thespian
from registrationserver2 import actor_system, logger
from registrationserver2.modules.mqtt.message import (  # , MQTT_ACTOR_REQUESTs, MQTT_ACTOR_ADRs, IS_ID_LIST
    RETURN_MESSAGES, Instr_CONN_HISTORY)
from registrationserver2.modules.mqtt.mqtt_actor import MqttActor
from thespian.actors import Actor

# from typing import Dict


# from typing import Dict


# from _hashlib import new

logger.info("%s -> %s", __package__, __file__)

mqtt_msg_queue = queue.Queue()


def add_2d_dict(actor_adr_dict, is_id_, instr_id_, val):
    if is_id_ in actor_adr_dict.keys():
        actor_adr_dict[is_id_].update({instr_id_: val})
        logger.info(f"The Instrument ({instr_id_}) is added")
        return 1
    else:
        logger.warning(
            f"The IS MQTT ({is_id_}) is unknown and hence, the instrument ({instr_id_}) is not added"
        )
        return 0


class MqttParser(threading.Thread):
    def __init__(self, TName="Mqtt-Parser"):
        super().__init__(name=TName)
        logger.info(f"The thread ({TName}) is created")
        self.len = 0
        self.topic_parts = []
        self.__folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
        self.__folder2_history = f"{registrationserver2.FOLDER2_HISTORY}{os.path.sep}"

    def run(self):
        try:
            while True:
                self.parser()
        finally:
            logger.info("The MQTT parser thread is ended")

    def get_id(self):
        # returns id of the respective thread
        if hasattr(self, "_thread_id"):
            return self._thread_id
        for ID, thread_ in threading._active.items():
            if thread_ is self:
                return ID

    def raise_exception(self):
        thread_id = self.get_id()
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            thread_id, ctypes.py_object(SystemExit)
        )
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            logger.warning("Exception raise failure")
            logger.warning("Failed to stop the MQTT parser thread")

    def parser(self):
        if not mqtt_msg_queue.empty():
            message = mqtt_msg_queue.get()
            self.topic_parts = message.get("topic").split("/")
            self.len = len(self.topic_parts)
            if self.len == 2:
                SARAD_MQTT_SUBSCRIBER = actor_system.createActor(
                    SaradMqttSubscriber, globalName="SARAD_Subscriber"
                )
                if self.topic_parts[1] == "connected":
                    if message.payload == "2" or message.payload == "1":
                        # filename_ = fr"{self.__folder2_history}{self.topic_parts[0]}"
                        # IS_ID_LIST.append(self.topic_parts[0])
                        # MQTT_ACTOR_ADRs[self.topic_parts[0]]={}
                        if not (Path(filename_).is_file()):
                            open(filename_, "w+")
                    elif message.payload == "0":
                        if Path(filename_).is_file():
                            ask_msg = {
                                "CMD": "RM_HOST",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has removed this cluster ({self.topic_parts[0]}) from file system"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with removing this cluster ({self.topic_parts[0]}) from file system"
                                )
                        else:
                            logger.warning(
                                f"SARAD_Subscriber has received disconnection message from an unknown instrument server ({self.topic_parts[0]})"
                            )
                    else:
                        logger.warning(
                            f"SARAD_Subscriber has received connection state of an unknown cluster ({self.topic_parts[0]})"
                        )
                elif self.topic_parts[1] == "meta":
                    filename_ = fr"{self.__folder2_history}{self.topic_parts[0]}"
                    if Path(filename_).is_file():  # if this file exists
                        if os.stat(filename_).st_size == 0:  # if this file is empty
                            ask_msg = {
                                "CMD": "ADD_HOST",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                    "payload": message.get("payload"),
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has added this cluster ({self.topic_parts[0]}) into file system"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with adding this cluster ({self.topic_parts[0]}) into file system"
                                )
                        else:
                            ask_msg = {
                                "CMD": "UP_HOST",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                    "payload": message.get("payload"),
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has updated the description of this cluster ({self.topic_parts[0]})"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with updating the description of this cluster ({self.topic_parts[0]})"
                                )
                    else:
                        logger.warning(
                            f"SARAD_Subscriber has received meta message of an unknown cluster ({self.topic_parts[0]})"
                        )
            elif self.len == 3:
                if self.topic_parts[2] == "connected":
                    if message.payload == "2" or message.payload == "1":
                        if (
                            self.topic_parts[0] in Instr_CONN_HISTORY.keys()
                        ):  # the IS MQTT has been added
                            if (
                                self.topic_parts[1]
                                in Instr_CONN_HISTORY[self.topic_parts[0]].keys()
                            ):
                                if (
                                    Instr_CONN_HISTORY[self.topic_parts[0]][
                                        self.topic_parts[1]
                                    ]
                                    == "Removed"
                                ):
                                    Instr_CONN_HISTORY[self.topic_parts[0]][
                                        self.topic_parts[1]
                                    ] == "Not_added"
                            else:
                                Instr_CONN_HISTORY[self.topic_parts[0]][
                                    self.topic_parts[1]
                                ] == "Not_added"
                        else:
                            Instr_CONN_HISTORY[self.topic_parts[0]] = {}
                            Instr_CONN_HISTORY[self.topic_parts[0]][
                                self.topic_parts[1]
                            ] == "Not_added"
                    elif message.payload == "0":
                        if (self.topic_parts[0] in Instr_CONN_HISTORY.keys()) and (
                            self.topic_parts[1]
                            in Instr_CONN_HISTORY[self.topic_parts[0]].keys()
                        ):
                            ask_msg = {
                                "CMD": "RM_DEVICE",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                    "instr_id": self.topic_parts[1],
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has killed the MQTT actor ({self.topic_parts[1]})"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with killing the MQTT actor ({self.topic_parts[1]})"
                                )
                        else:
                            logger.warning(
                                f"SARAD_Subscriber has received disconnection message from an unknown instrument ({self.topic_parts[1]}) controlled by the IS ({self.topic_parts[0]})"
                            )
                    else:
                        logger.warning(
                            f"SARAD_Subscriber has received unknown state of the MQTT actor ({self.topic_parts[1]}) controlled by the IS ({self.topic_parts[0]})"
                        )
                elif self.topic_parts[2] == "meta":
                    if (self.topic_parts[0] in Instr_CONN_HISTORY.keys()) and (
                        self.topic_parts[1]
                        in Instr_CONN_HISTORY[self.topic_parts[0]].keys()
                    ):
                        if (
                            Instr_CONN_HISTORY[self.topic_parts[0]][self.topic_parts[1]]
                            == "Not_added"
                        ):
                            ask_msg = {
                                "CMD": "ADD_DEVICE",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                    "instr_id": self.topic_parts[1],
                                    "payload": message.get("payload"),
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has added this actor ({self.topic_parts[1]}) into file system"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with adding this actor ({self.topic_parts[1]}) into file system"
                                )
                        elif (
                            Instr_CONN_HISTORY[self.topic_parts[0]][self.topic_parts[1]]
                            == "Added"
                        ):
                            ask_msg = {
                                "CMD": "UP_DEVICE",
                                "PAR": {
                                    "is_id": self.topic_parts[0],
                                    "instr_id": self.topic_parts[1],
                                    "payload": message.get("payload"),
                                },
                            }
                            ask_return = actor_system.ask(
                                SARAD_MQTT_SUBSCRIBER, ask_msg
                            )
                            logger.info(ask_return)
                            if (ask_return is RETURN_MESSAGES.get("OK")) or (
                                ask_return is RETURN_MESSAGES.get("OK_SKIPPED")
                            ):
                                logger.info(
                                    f"SARAD_Subscriber has updated the description file of this actor ({self.topic_parts[1]})"
                                )
                            else:
                                logger.warning(
                                    f"SARAD_Subscriber has problems with updating the description file of this actor ({self.topic_parts[1]})"
                                )
                        else:
                            logger.warning(
                                f"Receive unknown message {message.get('payload')} under the topic {message.get('topic')}"
                            )
                    else:
                        logger.warning(
                            f"Receive unknown message {message.get('payload')} under the topic {message.get('topic')}"
                        )
                else:  # Illeagl topics
                    logger.warning(
                        f"Receive unknown message {message.get('payload')} under the illegal topic {message.get('topic')}, which is sent to the actor ({self.topic_parts[1]})"
                    )
            else:  # Acceptable topics can be divided into 2 or 3 parts by '/'
                logger.warning(
                    f"Receive unknown message {message.get('payload')} under the topic {message.get('topic')} in illegal format, which is sent to the actor ({self.topic_parts[1]})"
                )


class SaradMqttSubscriber(Actor):
    """
    classdocs
    """

    ACCEPTED_COMMANDS = {
        "KILL": "_kill",  # Kill this actor itself
        "SETUP": "_setup",
        "RM_HOST": "_rm_host",  # Delete the link of the description file of a host from "available" to "history"
        "ADD_HOST": "_add_host",  # Create the link of the description file of a host from "available" to "history"
        "RM_DEVICE": "_rm_instr",  # Delete the link of the description file of an instrument from "available" to "history"
        "UP_HOST": "_update_host",  # Update the description file of a host
        "ADD_DEVICE": "_add_instr",  # Delete the link of the description file of a instrument from "available" to "history"
        "UP_DEVICE": "_update_instr",  # Update the description file of an instrument
    }

    mqtt_topic: str

    mqtt_payload: str

    mqtt_qos = 0

    mqtt_broker: str  # MQTT Broker, here: localhost

    mqtt_cid: str  # MQTT Client ID

    __folder_history: str

    __folder_available: str

    __folder2_history: str

    __folder2_available: str

    __lock = threading.Lock()

    SARAD_MQTT_PARSER = MqttParser(TName="MQTT_Parser")

    def __init__(self, client_id, broker):
        self.rc_conn = 2
        self.rc_disc = 2
        self.rc_pub = 1
        self.rc_sub = 1
        self.rc_uns = 1
        self.mqtt_cid = client_id
        self.mqtt_broker = broker
        with self.__lock:
            self.__folder_history = f"{registrationserver2.FOLDER_HISTORY}{os.path.sep}"
            self.__folder_available = (
                f"{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}"
            )
            self.__folder2_history = (
                f"{registrationserver2.FOLDER2_HISTORY}{os.path.sep}"
            )
            self.__folder2_available = (
                f"{registrationserver2.FOLDER2_AVAILABLE}{os.path.sep}"
            )
            if not os.path.exists(self.__folder_history):
                os.makedirs(self.__folder_history)
            if not os.path.exists(self.__folder_available):
                os.makedirs(self.__folder_available)
            if not os.path.exists(self.__folder2_history):
                os.makedirs(self.__folder2_history)
            if not os.path.exists(self.__folder2_available):
                os.makedirs(self.__folder2_available)
            logger.debug(f"For instruments, output to: {self.__folder_history}")
            logger.debug(f"For hosts, output to: {self.__folder2_history}")

    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

        if not isinstance(msg, dict):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGTYPE"))
            return

        cmd_string = msg.get("CMD", None)

        if not cmd_string:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT"))
            return

        cmd = self.ACCEPTED_COMMANDS.get(cmd_string, None)

        if not cmd:
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_UNKNOWN_COMMAND"))
            return

        if not getattr(self, cmd, None):
            self.send(sender, RETURN_MESSAGES.get("ILLEGAL_NOTIMPLEMENTED"))
            return

        self.send(sender, getattr(self, cmd)(msg))

    # Definition of callback functions for the MQTT client, namely the on_* functions
    # these callback functions are called in the new thread that is created through loo_start() of Client()
    def on_connect(
        self, client, userdata, flags, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client connected to the MQTT self.mqtt_broker."""
        self.rc_conn = result_code
        if self.rc_conn == 1:
            logger.info(
                f"Connection to MQTT self.mqtt_broker failed. result_code={result_code}"
            )
        else:
            logger.info("Connected with MQTT self.mqtt_broker.")
        # return self.result_code
    
    # Definition of callback functions for the MQTT client, namely the on_* functions
    # these callback functions are called in the new thread that is created through loo_start() of Client()
    def on_disconnect(
        self, client, userdata, result_code
    ):  # pylint: disable=unused-argument
        """Will be carried out when the client disconnected
        from the MQTT self.mqtt_broker."""
        self.rc_disc = result_code
        if self.rc_disc == 1:
            logger.info(
                f"Disconnection from MQTT-broker failed. result_code={result_code}"
            )
        else:
            logger.info("Gracefully disconnected from MQTT-broker.")

    def on_publish(self, client, userdata, mid):
        self.rc_pub = 0
        logger.info(f"The message with Message-ID {mid} is published to the broker!")

    def on_subscribe(self, client, userdata, mid, grant_qos):
        self.rc_sub = 0
        logger.info("Subscribed to the topic successfully!")

    def on_unsubscribe(self, client, userdata, mid):
        self.rc_uns = 0
        logger.info("Unsubscribed to the topic successfully!")

    def on_message(self, client, userdata, message):
        self.msg_buf = {}

        logger.info(f"message received: {str(message.payload.decode('utf-8'))}")
        logger.info(f"message topic: {message.topic}")
        logger.info(f"message qos: {message.qos}")
        logger.info(f"message retain flag: {message.retain}")
        self.msg_buf = {
            "topic": message.topic,
            "payload": message.payload,
        }
        mqtt_msg_queue.put(self.msg_buf)

    # Definition of methods accessible for the actor system and other actors -> referred to ACCEPTED_COMMANDS
    def _add_instr(self, msg: dict) -> dict:
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        instr_id = msg.get("PAR", None).get("instr_id", None)
        if instr_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if not is_id + "/" + instr_id in Instr_CONN_HISTORY:
            return RETURN_MESSAGES.get("INSTRUMENT_UNKNOWN")
        if msg.get("PAR", None).get("payload", None) is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        family_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Family", None)
        type_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Type", None)
        if family_ is None or type_ is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if family_ == 1:
            sarad_type = "sarad-1688"
        elif family_ == 2:
            sarad_type = "sarad-1688"
        elif family_ == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.warning(
                f"[Add]:\tFound: Unknown family (index: {family_}) of instrument"
            )
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        name_ = instr_id + "." + sarad_type + ".mqtt"
        data = msg.get("PAR", None).get("payload")
        # if an actor already exists this will return
        # the address of the excisting one, else it will create a new one
        if data:
            this_actor = actor_system.createActor(MqttActor, globalName=name_)
            setup_return = actor_system.ask(this_actor, {"CMD": "SETUP", "PAR": data})
            logger.info(setup_return)
            if not (
                setup_return is RETURN_MESSAGES.get("OK")
                or setup_return is RETURN_MESSAGES.get("OK_SKIPPED")
            ):
                actor_system.ask(this_actor, {"CMD": "KILL"})
                # After the device actor is killed because it is not setup correctly in __add_service__ method:
                # how to deal with the description file and the link?
                # how can the instrument server know this situation and handle with it?
                # IMO, MQTT Subscriber should ask the IS MQTT to send the ".../.../connected=2" and ".../.../meta" one by one again.
                Instr_CONN_HISTORY[is_id][instr_id] = "Removed"
                return setup_return
            else:
                prep_msg = {
                    "CMD": "PREPARE",
                    "PAR": {
                        "is_id": is_id,
                    },
                }
                prep_return = actor_system.ask(this_actor, prep_msg)
                if not (
                    prep_return is RETURN_MESSAGES.get("OK")
                    or prep_return is RETURN_MESSAGES.get("OK_SKIPPED")
                ):
                    actor_system.ask(this_actor, {"CMD": "KILL"})
                    # After the device actor is killed because it hasn't prepared correctly in __add_service__ method:
                    # how to deal with the description file and the link?
                    # how can the instrument server know this situation and handle with it?
                    # IMO, MQTT Subscriber should ask the IS MQTT to send the ".../.../connected=2" and ".../.../meta" one by one again.
                    Instr_CONN_HISTORY[is_id][instr_id] = "Removed"
                    return prep_return
            return RETURN_MESSAGES.get("OK_SKIPPED")

    def _rm_instr(self, msg: dict) -> dict:
        instr_id = msg.get("PAR", None).get("instr_id", None)
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if instr_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if not is_id + "/" + instr_id in Instr_CONN_HISTORY:
            return RETURN_MESSAGES.get("INSTRUMENT_UNKNOWN")
        if msg.get("PAR", None).get("payload", None) is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        family_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Family", None)
        type_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Type", None)
        if family_ is None or type_ is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if family_ == 1:
            sarad_type = "sarad-1688"
        elif family_ == 2:
            sarad_type = "sarad-1688"
        elif family_ == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.warning(
                f"[Add]:\tFound: Unknown family (index: {family_}) of instrument"
            )
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        name_ = instr_id + "." + sarad_type + ".mqtt"
        this_actor = registrationserver2.actor_system.createActor(
            MqttActor, globalName=name_
        )
        logger.info(
            registrationserver2.actor_system.ask(this_actor, {"CMD": "KILL"})
        )
        del Instr_CONN_HISTORY[is_id + "/" + instr_id]
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _update_instr(self, msg: dict) -> dict:
        instr_id = msg.get("PAR", None).get("instr_id", None)
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if instr_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if not is_id + "/" + instr_id in Instr_CONN_HISTORY:
            return RETURN_MESSAGES.get("INSTRUMENT_UNKNOWN")
        if msg.get("PAR", None).get("payload", None) is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        family_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Family", None)
        type_ = msg.get("PAR", None).get("payload", None).get("Identification", None).get("Type", None)
        if family_ is None or type_ is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        if family_ == 1:
            sarad_type = "sarad-1688"
        elif family_ == 2:
            sarad_type = "sarad-1688"
        elif family_ == 5:
            sarad_type = "sarad-dacm"
        else:
            logger.warning(
                f"[Add]:\tFound: Unknown family (index: {family_}) of instrument"
            )
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        name_ = instr_id + "." + sarad_type + ".mqtt"
        with self.__lock:
            logger.info(f"[Update]:\tUpdate: Instrument ID: {instr_id}")
            filename = fr"{self.__folder_history}{name_}"
            link = fr"{self.__folder_available}{name_}"
            try:
                data = msg.get("PAR", None).get("payload")
                if data:
                    with open(filename, "w+") as file_stream:
                        file_stream.write(data)
                    if not os.path.exists(link):
                        logger.info(f"Linking {link} to {filename}")
                        os.link(filename, link)
                else:
                    logger.error(
                        f"[Update]:\tFailed to get Properties from {msg}, {instr_id}"
                    )  # pylint: disable=W0106
                    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    f'[Update]:\t {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except:  # pylint: disable=W0702
                logger.error(
                    f"[Update]:\tCould not write properties of device with ID: {instr_id}"
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _add_host(self, msg: dict) -> dict:
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        with self.__lock:
            logger.info(
                f"[Add]:\tFound: A new connected host with Instrument Server ID : {is_id}"
            )
            filename = fr"{self.__folder2_history}{is_id}"
            link = fr"{self.__folder2_available}{is_id}"
            try:
                data = msg.get("PAR", None).get("payload")
                if data:
                    with open(filename, "w+") as file_stream:
                        file_stream.write(data)
                    if not os.path.exists(link):
                        logger.info(f"Linking {link} to {filename}")
                        os.link(filename, link)
                else:
                    logger.error(
                        f"[Add]:\tFailed to get Properties from {msg}, {is_id}"
                    )  # pylint: disable=W0106
                    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    f'[Add]:\t {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except:  # pylint: disable=W0702
                logger.error(
                    f"[Add]:\tCould not write properties of instrument server with ID: {is_id}"
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _rm_host(self, msg: dict) -> dict:
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        for mem in Instr_CONN_HISTORY:
            if mem.split("/")[0] == is_id:
                _re = self._rm_instr(
                    {
                        "CMD": "RM_DEVICE",
                        "PAR": {"is_id": is_id, "instr_id": mem.split("/")[1]},
                    }
                )
                logger.info(_re)
        with self.__lock:
            logger.info(f"[Del]:\tRemoved the host with Instrument Server ID: {is_id}")
            link = fr"{self.__folder2_available}{is_id}"
            if os.path.exists(link):
                os.unlink(link)
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _update_host(self, msg: dict) -> dict:
        is_id = msg.get("PAR", None).get("is_id", None)
        if is_id is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        with self.__lock:
            logger.info(
                f"[Update]:\tFound: A new connected host with Instrument Server ID : {is_id}"
            )
            filename = fr"{self.__folder2_history}{is_id}"
            link = fr"{self.__folder2_available}{is_id}"
            try:
                data = msg.get("PAR", None).get("payload")
                if data:
                    with open(filename, "w+") as file_stream:
                        file_stream.write(data)
                    if not os.path.exists(link):
                        logger.info(f"Linking {link} to {filename}")
                        os.link(filename, link)
                else:
                    logger.error(
                        f"[Update]:\tFailed to get Properties from {msg}, {is_id}"
                    )  # pylint: disable=W0106
                    return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except BaseException as error:  # pylint: disable=W0703
                logger.error(
                    f'[Update]:\t {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}'
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
            except:  # pylint: disable=W0702
                logger.error(
                    f"[Update]:\tCould not write properties of instrument server with ID: {is_id}"
                )
                return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _kill(self, msg) -> dict:
        self.__disconnect(msg)
        for IS_ID in Instr_CONN_HISTORY.keys():
            rm_return = self._rm_host({"CMD": "RM_HOST", "PAR": {"is_id": IS_ID}})
            logger.info(rm_return)
        del Instr_CONN_HISTORY
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def _setup(self, msg: dict) -> dict:
        conn_re = self.__connect()
        logger.info(f"[CONN]\tThe client ({self.mqtt_cid}): {conn_re}")
        if conn_re is RETURN_MESSAGES.get("OK_SKIPPED"):
            self.mqttc.loop_start()
            self.SARAD_MQTT_PARSER.start()
        else:
            return conn_re
        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": "+/connected", "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("SETUP_FAILURE")

        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": "+/meta", "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("SETUP_FAILURE")
        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": "+/+/connected", "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("SETUP_FAILURE")

        sub_req_msg = {
            # "CMD": "SUBSCRIBE",
            "PAR": {"topic": "+/+/meta", "qos": 0},
        }
        subscribe_status = self.__subscribe(sub_req_msg)
        if not (
            subscribe_status is RETURN_MESSAGES.get("OK")
            or subscribe_status is RETURN_MESSAGES.get("OK_SKIPPED")
        ):
            return RETURN_MESSAGES.get("SETUP_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    # Definition of methods, namely __*(), not accessible for the actor system and other actors
    def __connect(self) -> dict:
        # self.mqtt_cid = msg.get("PAR", None).get("client_id", None)

        # if self.mqtt_cid is None:
        #    return RETURN_MESSAGES.get("ILLEGAL_STATE")

        if self.mqtt_cid is None:
            self.mqtt_cid = "SARAD-Subscriber-000"

        # self.mqtt_broker = msg.get("PAR", None).get("mqtt_broker", None)

        if self.mqtt_broker is None:
            self.mqtt_broker = "localhost"

        self.mqttc = MQTT.Client(self.mqtt_cid)

        self.mqttc.reinitialise()

        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        self.mqttc.on_unsubscribe = self.on_unsubscribe

        self.mqttc.connect(self.mqtt_broker)

        self.wait_cnt = 3

        while self.wait_cnt != 0:  # Wait only 3*2s = 6s
            if self.rc_conn == 0:
                self.rc_conn = 2
                break
            elif self.rc_conn == 1:
                self.rc_conn = 2
                return RETURN_MESSAGES.get("CONNECTION_FAILURE")
            else:
                time.sleep(2)
                self.wait_cnt = self.wait_cnt - 1
        else:
            return RETURN_MESSAGES.get("CONNECTION_NO_RESPONSE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __disconnect(self) -> dict:
        logger.info("To disconnect from the MQTT-broker!")
        self.mqttc.disconnect()
        logger.info("To stop the MQTT thread!")
        self.mqttc.loop_stop()
        logger.info("To stop the MQTT parser thread!")
        self.SARAD_MQTT_PARSER.raise_exception()
        self.SARAD_MQTT_PARSER.join()
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __publish(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("PAR", None).get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_payload = msg.get("PAR", None).get("payload", None)
        split_buf = self.mqtt_topic.split("/")
        if len(split_buf) != 3 and len(split_buf) != 2:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_qos = msg.get("PAR", None).get("qos", None)
        self.mqttc.publish(self.mqtt_topic, self.mqtt_payload, self.mqtt_qos)
        self.wait_cnt1 = 3
        while self.wait_cnt1 != 0:  # Wait only 3*2s = 6s
            if self.rc_pub == 1:
                time.sleep(2)
                self.wait_cnt1 = self.wait_cnt1 - 1
                logger.info("Waiting for the on_publish being called")
            else:
                self.rc_pub = 1
                break
        else:
            logger.info("on_publish not called: PUBLISH FAILURE!")
            return RETURN_MESSAGES.get("PUBLISH_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __subscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqtt_qos = msg.get("qos", None)
        if self.mqtt_qos is None:
            self.mqtt_qos = 0
        self.mqttc.subscribe(self.mqtt_topic, self.mqtt_qos)
        self.wait_cnt2 = 3
        while self.wait_cnt2 != 0:  # Wait only 3*2s = 6s
            if self.rc_sub == 1:
                time.sleep(2)
                self.wait_cnt2 = self.wait_cnt2 - 1
                logger.info("Waiting for the on_subscribe being called")
            else:
                self.rc_sub = 1
                break
        else:
            logger.info("on_subscribe not called: SUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("SUBSCRIBE_FAILURE")
        return RETURN_MESSAGES.get("OK_SKIPPED")

    def __unsubscribe(self, msg: dict) -> dict:
        self.mqtt_topic = msg.get("topic", None)
        if self.mqtt_topic is None:
            return RETURN_MESSAGES.get("ILLEGAL_WRONGFORMAT")
        self.mqttc.unsubscribe(self.mqtt_topic)
        self.wait_cnt3 = 3

        while self.wait_cnt3 != 0:  # Wait only 3*2s = 6s
            if self.rc_uns == 1:
                time.sleep(2)
                self.wait_cnt3 = self.wait_cnt3 - 1
                logger.info("Waiting for the on_unsubscribe being called")
            else:
                self.rc_uns = 1
                break
        else:
            logger.info("on_unsubscribe not called: UNSUBSCRIBE FAILURE!")
            return RETURN_MESSAGES.get("UNSUBSCRIBE_FAILURE")

        return RETURN_MESSAGES.get("OK_SKIPPED")

    # * Handling of Ctrl+C:
    def signal_handler(self, sig, frame):  # pylint: disable=unused-argument
        """On Ctrl+C:
        - stop all cycles
        - disconnect from MQTT self.mqtt_broker"""
        logger.info("You pressed Ctrl+C!")
        self._disconnect()
        sys.exit(0)

    signal.signal(
        signal.SIGINT, signal_handler
    )  # SIGINT: By default, interrupt is Ctrl+C


def __test__():
    SaradMqttSubscriber = actor_system.createActor(
        SaradMqttSubscriber, globalName="SARAD_Subscriber"
    )
    ask_return = actor_system.ask(SARAD_MQTT_SUBSCRIBER, "SETUP")
    if ask_return is RETURN_MESSAGES.get("OK"):
        logger.info("SARAD MQTT Subscriber is setup correctly!")
        print("SARAD MQTT Subscriber is setup correctly!")
    else:
        logger.warning("SARAD MQTT Subscriber is not setup!")
        logger.error(ask_return)
        print("SARAD MQTT Subscriber is not setup!")
    input("Press Enter to End")
    actor_system.ask(SARAD_MQTT_SUBSCRIBER, "KILL")
    logger.info("!")


if __name__ == "__main__":
    __test__()
