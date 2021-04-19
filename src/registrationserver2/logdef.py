"""Definition of the logDef dictionary to setup logging in actors

Created
    2021-04-17

Authors
    copied from Thespian documentation
"""
import logging
import logging.handlers
import os

from registrationserver2.config import config


class actorLogFilter(logging.Filter):
    def filter(self, logrecord):
        return "actorAddress" in logrecord.__dict__


class notActorLogFilter(logging.Filter):
    def filter(self, logrecord):
        return "actorAddress" not in logrecord.__dict__


LOGLEVEL = config["LEVEL"]

if config["LOG_FILE"] is not None:
    log_folder = config["LOG_FOLDER"]
    log_file = config["LOG_FILE"]
    FILENAME = log_folder + log_file
    os.makedirs(os.path.dirname(FILENAME), exist_ok=True)
    with open(FILENAME, "w") as f:
        pass
else:
    FILENAME = "registrationserver.log"

logcfg = {
    "version": 1,
    "formatters": {
        "normal": {
            "format": "%(asctime)-15s %(levelname)-6s %(module)-15s %(message)s"
        },
        "actor": {
            "format": "%(asctime)-15s %(levelname)-6s %(actorAddress)-15s %(message)s"
        },
    },
    "filters": {
        "isActorLog": {"()": actorLogFilter},
        "notActorLog": {"()": notActorLogFilter},
    },
    "handlers": {
        "h1": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "normal",
            "filename": FILENAME,
            "maxBytes": 8192,
            "backupCount": 5,
            "filters": ["notActorLog"],
            "mode": "w",
            "encoding": "utf-8",
            "level": LOGLEVEL,
        },
        "h2": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "actor",
            "filename": FILENAME,
            "maxBytes": 8192,
            "backupCount": 5,
            "filters": ["isActorLog"],
            "mode": "w",
            "encoding": "utf-8",
            "level": LOGLEVEL,
        },
    },
    "loggers": {"": {"handlers": ["h1", "h2"], "level": LOGLEVEL}},
}
