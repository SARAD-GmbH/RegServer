"""
Created on 2021-03-12

@author: Yixiang
"""

import logging

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")

RETURN_MESSAGES = {
    # The message received by the actor was not in an expected format
    "ILLEGAL_WRONGFORMAT": {
        "ERROR": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },
    # The command received by the actor was not yet implemented by the implementing class
    "ILLEGAL_NOTIMPLEMENTED": {
        "ERROR": "Not implemented",
        "ERROR_CODE": 2,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_WRONGTYPE": {
        "ERROR": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },
    # The message received by the actor was not in an expected type
    "ILLEGAL_UNKNOWN_COMMAND": {
        "ERROR": "Unknown Command",
        "ERROR_CODE": 4,
    },
    # The actor was in an wrong state
    # "ILLEGAL_STATE": {
    #     "ERROR": "Actor not setup correctly, make sure to send SETUP message first",
    #     "ERROR_CODE": 5,
    # }, # not supported in RETURN_MESSAGE in data_base_actor.py
    "CONNECTION_FAILURE": {
        "ERROR": "MQTT client failed to connect to MQTT-broker",
        "ERROR_CODE": 6,
    },
    "CONNECTION_NO_RESPONSE": {
        "ERROR": "No response to connection request",
        "ERROR_CODE": 7,
    },
    # "DISCONNECTION_FAILURE": {
    #     "ERROR": "MQTT client failed to disconnect with MQTT-broker",
    #     "ERROR_CODE": 8,
    # },
    # "DISCONNECTION_NO_RESPONSE": {
    #     "ERROR": "No response to disconnection request",
    #     "ERROR_CODE": 9,
    # },
    # "PUBLISH_FAILURE": {"ERROR": "Failed to publish the message", "ERROR_CODE": 10},
    "SUBSCRIBE_FAILURE": {
        "ERROR": "Failed to subscribe to the topic",
        "ERROR_CODE": 11,
    },
    "UNSUBSCRIBE_FAILURE": {
        "ERROR": "Failed to unsubscribe to the topic",
        "ERROR_CODE": 12,
    },
    "OK_SKIPPED": {"RETURN": True, "SKIPPED": True},
    "OK": {"RETURN": True, "SKIPPED": True},
}
