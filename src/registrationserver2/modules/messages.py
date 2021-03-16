"""
Created on 08.12.2020

@author: rfoerster
"""

import logging

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")

RETURN_MESSAGES = {
    "ILLEGAL_WRONGFORMAT": {
        "ERROR": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },  # The message received by the actor was not in an expected format
    "ILLEGAL_NOTIMPLEMENTED": {
        "ERROR": "Not implemented",
        "ERROR_CODE": 2,
    },  # The command received by the actor was not yet implemented by the implementing class
    "ILLEGAL_WRONGTYPE": {
        "ERROR": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },  # The message received by the actor was not in an expected type
    "ILLEGAL_UNKNOWN_COMMAND": {
        "ERROR": "Unknown Command",
        "ERROR_CODE": 4,
    },  # The message received by the actor was not in an expected type
    "ILLEGAL_STATE": {
        "ERROR": "Actor not setup correctly, make sure to send SETUP message first",
        "ERROR_CODE": 5,
    },  # The actor was in an wrong state
    "OK_SKIPPED": {"RETURN": True, "SKIPPED": True},
    "OK": {"RETURN": True, "SKIPPED": True},
}
