"""
Created on 2021-03-12

@author: Yixiang
"""

from typing import Dict

MQTT_ACTOR_REQUESTs: Dict[
    str, str
] = {}  # A dictionary for storing the request statuses of MQTT Actors
"""
Struture of MQTT_ACTOR_REQUESTs:
MQTT_ACTOR_REQUESTs = {
    IS1_ID: {
        instr_id1 : "reserve", # the mqtt_actor (actor name is the same as instr_id1) requesting to reserve instrument (instr_id1)
        instr_id2 : "free",    # the mqtt_actor (actor name is the same as instr_id1) requesting to free instrument (instr_id1)
        instr_id3 : "None",    # nothing to do with the reservation/free
        ...
    },
    ...
}
"""

MQTT_ACTOR_ADRs: Dict[
    str, str
] = {}  # A dictionary for storing the addresses of MQTT Actors
"""
Struture of MQTT_ACTOR_ADRs:
MQTT_ACTOR_ADRs = {
    IS1_ID: {
        Actor11_Name : Actor11_ADR, # Name of an actor is the ID of the instrument that this actor takes care of.
        Actor12_Name : Actor12_ADR, # The address of each actor can be gained through createActor() methods in the ActorSystem class.
        ...
    },
    IS2_ID: {
        Actor21_Name : Actor21_ADR,
        Actor22_Name : Actor22_ADR,
        ...
    },
    ...
}
"""

IS_ID_LIST: list = []  # A list for storing the ID of IS MQTT


RETURN_MESSAGES = {
    # The message received by the actor was not in an expected format
    "ILLEGAL_WRONGFORMAT": {
        "RESULT": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },
    # The command received by the actor was not yet implemented by the implementing class
    "ILLEGAL_NOTIMPLEMENTED": {
        "RESULT": "Not implemented",
        "ERROR_CODE": 2,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_WRONGTYPE": {
        "RESULT": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_UNKNOWN_COMMAND": {
        "RESULT": "Unknown Command",
        "ERROR_CODE": 4,
    },
    # The actor was in an wrong state
    # "ILLEGAL_STATE": {
    #     "RESULT": "Actor not setup correctly, make sure to send SETUP message first",
    #     "ERROR_CODE": 5,
    # }, # not supported in RETURN_MESSAGE in data_base_actor.py
    "CONNECTION_FAILURE": {
        "RESULT": "MQTT client failed to connect to MQTT-broker",
        "ERROR_CODE": 6,
    },
    "CONNECTION_NO_RESPONSE": {
        "RESULT": "No response to connection request",
        "ERROR_CODE": 7,
    },
    # "DISCONNECTION_FAILURE": {
    #     "RESULT": "MQTT client failed to disconnect with MQTT-broker",
    #     "ERROR_CODE": 8,
    # },
    # "DISCONNECTION_NO_RESPONSE": {
    #     "RESULT": "No response to disconnection request",
    #     "ERROR_CODE": 9,
    # },
    "PUBLISH_FAILURE": {
        "RESULT": "Failed to publish the message",
        "ERROR_CODE": 10,
    },
    "SUBSCRIBE_FAILURE": {
        "RESULT": "Failed to subscribe to the topic",
        "ERROR_CODE": 11,
    },
    "UNSUBSCRIBE_FAILURE": {
        "RESULT": "Failed to unsubscribe to the topic",
        "ERROR_CODE": 12,
    },
    "NO_MQTT_ACTOR": {
        "RESULT": "There is no such MQTT Actor created",
        "ERROR_CODE": 13,
    },
    "PREPARE_FAILURE": {
        "RESULT": "Failed to make the MQTT Actor prepared",
        "ERROR_CODE": 14,
    },
    "OK_SKIPPED": {"RETURN": True, "SKIPPED": True},
    "OK": {"RETURN": True, "SKIPPED": True},
}
