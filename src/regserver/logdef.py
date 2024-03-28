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

from regserver.config import config, dirs

LOGLEVEL = config["LEVEL"]

LOGFILENAME = config["LOG_FOLDER"] + config["LOG_FILE"]
try:
    os.makedirs(os.path.dirname(LOGFILENAME), exist_ok=True)
    with open(LOGFILENAME, "a", encoding="utf-8") as f:
        pass
except PermissionError:
    LOGFILENAME = f"{dirs.user_log_dir}{os.path.sep}{config['LOG_FILE']}"
    os.makedirs(os.path.dirname(LOGFILENAME), exist_ok=True)
    with open(LOGFILENAME, "a", encoding="utf-8") as f:
        pass

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
