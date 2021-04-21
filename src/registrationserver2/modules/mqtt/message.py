"""
Created on 2021-03-12

@author: Yixiang
"""
import json
from typing import Dict

# MQTT_ACTOR_REQUESTs: Dict[
#    str, str
# ] = {}  # A dictionary for storing the request statuses of MQTT Actors
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

# MQTT_ACTOR_ADRs: Dict[
#    str, str
# ] = {}  # A dictionary for storing the addresses of MQTT Actors
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

# IS_ID_LIST: list = []  # A list for storing the ID of IS MQTT

Instr_CONN_HISTORY: Dict[
    str, str
] = {}  # mainly used for distinguishing __add_instr__() and __update_instr__()
"""
Struture of Instr_CONN_HISTORY:
MQTT_ACTOR_ADRs = {
    IS1_ID: {
        Instr_ID11 : {
            "Status": "Not_added", # this instrument has connected but its description message is not added -> __add_instr__()
            "Actor": <Name of the MQTT Actor>, 
        }
        Instr_ID12 : {
            "Status": "Added", # this instrument has connected and its description message is added -> __update_instr__()
            "Actor": <Name of the MQTT Actor>,
        }
        #Instr_ID13 : {
        #    "Status": "Not_removed", # this instrument has disconnected but the link to its description message is not removed -> __rm_instr__()
        #    "Actor": <Name of the MQTT Actor>,
        #}
        Instr_ID14 : {
            "Status": "Removed", # this instrument has disconnected and the link to its description message is removed, once connected -> "Not_added"
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

RETURN_MESSAGES = {
    # The message received by the actor was not in an expected format
    "ILLEGAL_WRONGFORMAT": {
        "ERROR_MESSAGE": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },
    # The command received by the actor was not yet implemented by the implementing class
    "ILLEGAL_NOTIMPLEMENTED": {
        "ERROR_MESSAGE": "Not implemented",
        "ERROR_CODE": 2,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_WRONGTYPE": {
        "ERROR_MESSAGE": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_UNKNOWN_COMMAND": {
        "ERROR_MESSAGE": "Unknown Command",
        "ERROR_CODE": 4,
    },
    # The actor was in an wrong state.
    "ILLEGAL_STATE": {
        "ERROR_MESSAGE": "Actor not setup correctly, make sure to send SETUP message first",
        "ERROR_CODE": 5,
    },
    "CONNECTION_FAILURE": {
        "ERROR_MESSAGE": "MQTT client failed to connect to MQTT-broker",
        "ERROR_CODE": 6,
    },
    #"CONNECTION_NO_RESPONSE": {
    #    "ERROR_MESSAGE": "No response to connection request",
    #    "ERROR_CODE": 7,
    #},
    # "DISCONNECTION_FAILURE": {
    #     "ERROR_MESSAGE": "MQTT client failed to disconnect with MQTT-broker",
    #     "ERROR_CODE": 8,
    # },
    # "DISCONNECTION_NO_RESPONSE": {
    #     "ERROR_MESSAGE": "No response to disconnection request",
    #     "ERROR_CODE": 9,
    # },
    "PUBLISH_FAILURE": {
        "ERROR_MESSAGE": "Failed to publish the message",
        "ERROR_CODE": 11,
    },
    "SUBSCRIBE_FAILURE": {
        "ERROR_MESSAGE": "Failed to subscribe to the topic",
        "ERROR_CODE": 12,
    },
    "UNSUBSCRIBE_FAILURE": {
        "ERROR_MESSAGE": "Failed to unsubscribe to the topic",
        "ERROR_CODE": 13,
    },
    "NO_MQTT_ACTOR": {
        "ERROR_MESSAGE": "There is no such MQTT Actor created",
        "ERROR_CODE": 14,
    },
    "PREPARE_FAILURE": {
        "ERROR_MESSAGE": "Failed to make the MQTT Actor prepared",
        "ERROR_CODE": 15,
    },
    "SEND_RESERVE_FAILURE": {
        "ERROR_MESSAGE": "Failed to send reservation request",
        "ERROR_CODE": 16,
    },
    "RESERVE_NO_REPLY": {
        "ERROR_MESSAGE": "Got no reply for the reservation request",
        "ERROR_CODE": 17,
    },
    "RESERVE_REFUSED": {
        "ERROR_MESSAGE": "Reservation request is refused",
        "ERROR_CODE": 18,
    },
    "SEND_FREE_FAILURE": {
        "ERROR_MESSAGE": "Failed to send free request",
        "ERROR_CODE": 19,
    },
    "SEND_FAILURE": {
        "ERROR_MESSAGE": "Failed to send binary CMD",
        "ERROR_CODE": 21,
    },
    "ASK_NO_REPLY": {
        "ERROR_MESSAGE": "Got no reply to the request sent to the client actor via 'ask' method",
        "ERROR_CODE": 22,
    },
    "INSTRUMENT_UNKNOWN": {
        "ERROR_MESSAGE": "Unknown instrument that is not registered",
        "ERROR_CODE": 23,
    },
    "SETUP_FAILURE": {
        "ERROR_MESSAGE": "Failed to setup the actor",
        "ERROR_CODE": 24,
    },
    "ILLEGAL_REPLY": {
        "ERROR_MESSAGE": "The reply from IS in wrong format or missed important message",
        "ERROR_CODE": 25,
    },
    "NO_INSTRUMENT_SERVER": {
        "ERROR_MESSAGE": "No such an instrument server in history",
        "ERROR_CODE": 26,
    },
    "BLOCKED": {
        "ERROR_MESSAGE": "The target is busy now",
        "ERROR_CODE": 27,
    },
    "ILLEGAL_SENDER": {
        "ERROR_MESSAGE": "The sender is illegal for the target actor",
        "ERROR_CODE": 28,
    },
    "OK_SKIPPED": {
        "ERROR_MESSAGE": "OK, skipped",
        "ERROR_CODE": 10,
    },
    "OK_UPDATED": {
        "ERROR_MESSAGE": "OK, updated",
        "ERROR_CODE": 20,
    },
    "OK": {
        "RETURN": "OK",
        "ERROR_CODE": 0,
    },
}


def is_JSON(myJSON):
    try:
        json_obj = json.loads(myJSON)
    except ValueError as e:
        return None
    return json_obj
