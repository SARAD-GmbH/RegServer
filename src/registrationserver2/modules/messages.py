"""
Created on 08.12.2020

@author: rfoerster
"""

from registrationserver2 import theLogger

theLogger.info("%s -> %s", __package__, __file__)

RETURN_MESSAGES = {
    # The message received by the actor was not in an expected format.
    "ILLEGAL_WRONGFORMAT": {
        "RETURN": "Misformatted or no message sent",
        "ERROR_CODE": 1,
    },
    # The command received by the actor was not yet implemented by the
    # implementing class.
    "ILLEGAL_NOTIMPLEMENTED": {
        "RETURN": "Not implemented",
        "ERROR_CODE": 2,
    },
    # The message received by the actor was not in an expected type.
    "ILLEGAL_WRONGTYPE": {
        "RETURN": "Wrong Message Type, dictionary Expected",
        "ERROR_CODE": 3,
    },
    # The message received by the actor was not in an expected type.
    "ILLEGAL_UNKNOWN_COMMAND": {
        "RETURN": "Unknown Command",
        "ERROR_CODE": 4,
    },
    # The actor was in an wrong state.
    "ILLEGAL_STATE": {
        "RETURN": "Actor not setup correctly, make sure to send SETUP message first",
        "ERROR_CODE": 5,
    },
    "OK_SKIPPED": {
        "RETURN": "OK, skipped",
        "ERROR_CODE": 10,
    },
    "OK": {
        "RETURN": "OK",
        "ERROR_CODE": 0,
    },
}
