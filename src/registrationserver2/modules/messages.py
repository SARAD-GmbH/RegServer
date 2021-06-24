"""
Created on 08.12.2020

@author: rfoerster
"""

RETURN_MESSAGES = {
    # The message received by the actor was not in an expected format.
    "ILLEGAL_WRONGFORMAT": {
        "ERROR_MESSAGE": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },
    # The command received by the actor was not yet implemented by the
    # implementing class.
    "ILLEGAL_NOTIMPLEMENTED": {
        "ERROR_MESSAGE": "Not implemented",
        "ERROR_CODE": 2,
    },
    # The message received by the actor was not in an expected type.
    "ILLEGAL_WRONGTYPE": {
        "ERROR_MESSAGE": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },
    # The message received by the actor was not in an expected type.
    "ILLEGAL_UNKNOWN_COMMAND": {
        "ERROR_MESSAGE": "Unknown Command",
        "ERROR_CODE": 4,
    },
    # The actor was in an wrong state.
    "ILLEGAL_STATE": {
        "ERROR_MESSAGE": "Actor not setup correctly, make sure to send SETUP message first",
        "ERROR_CODE": 5,
    },
    "OCCUPIED": {
        "ERROR_MESSAGE": "Device occupied",
        "ERROR_CODE": 6,
    },
    "SETUP": {
        "ERROR_MESSAGE": "Error during actor setup",
        "ERROR_CODE": 31,
    },
    "CONNECT": {
        "ERROR_MESSAGE": "Error during setup of connection to MQTT broker",
        "ERROR_CODE": 32,
    },
    "PUBLISH": {
        "ERROR_MESSAGE": "Error during setup of connection to MQTT broker",
        "ERROR_CODE": 33,
    },
    "SUBSCRIBE": {
        "ERROR_MESSAGE": "Error when subscribing to an MQTT topic",
        "ERROR_CODE": 34,
    },
    "UNSUBSCRIBE": {
        "ERROR_MESSAGE": "Error when unsubscribing from an MQTT topic",
        "ERROR_CODE": 34,
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
        "ERROR_MESSAGE": "OK",
        "ERROR_CODE": 0,
    },
}
