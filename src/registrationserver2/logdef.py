"""Definition of the logDef dictionary to setup logging in actors

Created
    2021-04-17

Authors
    copied from Thespian documentation
"""
import logging


class actorLogFilter(logging.Filter):
    def filter(self, logrecord):
        return "actorAddress" in logrecord.__dict__


class notActorLogFilter(logging.Filter):
    def filter(self, logrecord):
        return "actorAddress" not in logrecord.__dict__


logcfg = {
    "version": 1,
    "formatters": {
        "normal": {"format": "%(levelname)-8s %(message)s"},
        "actor": {"format": "%(levelname)-8s %(actorAddress)s => %(message)s"},
    },
    "filters": {
        "isActorLog": {"()": actorLogFilter},
        "notActorLog": {"()": notActorLogFilter},
    },
    "handlers": {
        "h1": {
            "class": "logging.FileHandler",
            "filename": "example.log",
            "formatter": "normal",
            "filters": ["notActorLog"],
            "level": logging.INFO,
        },
        "h2": {
            "class": "logging.FileHandler",
            "filename": "example.log",
            "formatter": "actor",
            "filters": ["isActorLog"],
            "level": logging.INFO,
        },
    },
    "loggers": {"": {"handlers": ["h1", "h2"], "level": logging.DEBUG}},
}
