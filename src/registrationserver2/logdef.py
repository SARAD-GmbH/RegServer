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
    LOGFILENAME = log_folder + log_file
    os.makedirs(os.path.dirname(LOGFILENAME), exist_ok=True)
    with open(LOGFILENAME, "a") as f:
        pass
else:
    LOGFILENAME = "registrationserver.log"

logcfg = {
    "version": 1,
    "formatters": {
        "normal": {
            "format": "%(asctime)-15s %(levelname)-10s %(module)-17s %(process)d %(message)s"
        },
        "actor": {
            "format": "%(asctime)-15s %(levelname)-10s %(actorAddress)-17s %(process)d %(message)s"
        },
    },
    "filters": {
        "isActorLog": {"()": actorLogFilter},
        "notActorLog": {"()": notActorLogFilter},
    },
    "handlers": {
        "f1": {
            "class": "logging.FileHandler",
            "formatter": "normal",
            "filename": LOGFILENAME,
            "filters": ["notActorLog"],
            "mode": "a",
            "encoding": "utf-8",
            "level": LOGLEVEL,
        },
        "f2": {
            "class": "logging.FileHandler",
            "formatter": "actor",
            "filename": LOGFILENAME,
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
    "loggers": {"": {"handlers": ["f1", "f2", "console"], "level": LOGLEVEL}},
}
