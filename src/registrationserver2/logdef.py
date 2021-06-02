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

home = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
app_folder = f"{home}{os.path.sep}SARAD{os.path.sep}"
config.setdefault("LEVEL", logging.CRITICAL)
config.setdefault("LOG_FOLDER", f"{app_folder}log{os.path.sep}")
config.setdefault("LOG_FILE", "registrationserver.log")

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
            "format": "%(asctime)-15s %(levelname)-6s %(module)-15s %(process)d %(message)s"
        },
        "actor": {
            "format": "%(asctime)-15s %(levelname)-6s %(actorAddress)-15s %(process)d %(message)s"
        },
    },
    "filters": {
        "isActorLog": {"()": actorLogFilter},
        "notActorLog": {"()": notActorLogFilter},
    },
    "handlers": {
        "f1": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "normal",
            "filename": FILENAME,
            "maxBytes": 81920,
            "backupCount": 5,
            "filters": ["notActorLog"],
            "mode": "a",
            "encoding": "utf-8",
            "level": LOGLEVEL,
        },
        "f2": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "actor",
            "filename": FILENAME,
            "maxBytes": 81920,
            "backupCount": 5,
            "filters": ["isActorLog"],
            "mode": "a",
            "encoding": "utf-8",
            "level": LOGLEVEL,
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "normal",
            # "filters": ["isActorLog", "notActorLog"],
            "level": LOGLEVEL,
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {"": {"handlers": ["console"], "level": LOGLEVEL}},
}
