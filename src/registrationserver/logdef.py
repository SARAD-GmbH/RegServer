"""Definition of the logDef dictionary to setup logging in actors

:Created:
    2021-04-17

:Authors:
    | copied from Thespian documentation
    | simplified by Michael Strey <strey@sarad.de>
"""
import logging
import logging.handlers
import os

from registrationserver.config import config

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
            "format": "%(asctime)-15s %(levelname)-8s %(module)-14s %(message)s"
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "formatter": "normal",
            "level": LOGLEVEL,
            "filename": LOGFILENAME,
            "mode": "a",
            "encoding": "utf-8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "normal",
            "level": LOGLEVEL,
            "stream": "ext://sys.stdout",
        },
        "socket": {
            "class": "logging.handlers.SocketHandler",
            "level": LOGLEVEL,
            "host": "localhost",
            "port": logging.handlers.DEFAULT_TCP_LOGGING_PORT,
        },
    },
    "loggers": {"": {"handlers": ["file", "console"], "level": LOGLEVEL}},
}
