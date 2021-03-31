"""
Registration Server 2 module,
connects all kinds of Instrument Server 2 with the user applications
"""
# standard libraries
import logging
import os
import re
from typing import Any, Optional, Pattern

# 3rd party
from thespian.actors import ActorSystem  # type: ignore

# local
from registrationserver2.config import config

# actor_system :ActorSystem = ActorSystem('multiprocTCPBase')
actor_system: ActorSystem = ActorSystem()


# =======================
# Default values for configuration,
# is applied if a value is not set in config.py
# =======================
home: Optional[str] = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
config.setdefault(
    "FOLDER",
    f"{home}{os.path.sep}SARAD{os.path.sep}devices",
)
config.setdefault("LEVEL", logging.CRITICAL)
config.setdefault("MDNS_TIMEOUT", 3000)
config.setdefault("TYPE", "_rfc2217._tcp.local.")
config.setdefault(
    "FOLDER2",
    f'{os.environ.get("HOME", None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}hosts',
)

# Initialization of the actor system,
# can be changed to a distributed system here.
# TODO:  Setup ActorSystem with values from the configuration

# ==========================================
# Logging configuration,
# TODO: configuration still gets overwritten by one of the imports
# ==========================================
theLogger: Any = logging.getLogger("Instrument Server V2")
formatter: Any = logging.Formatter("[%(name)s]\t[%(levelname)s]:\t%(message)s")
if theLogger.handlers:
    for handler in theLogger.handlers:
        theLogger.removeHandler(handler)

streamh: Any = logging.StreamHandler()
logging.basicConfig(level=logging.CRITICAL)

theLogger.setLevel(config["LEVEL"])

theLogger.info("Logging system initialized.")

# ==========================================
# Folders structure / API names for devices and device history
# TODO: move to configuration instead
# ==========================================

# How the sub folder for available instrument/host description files is called
FILE_PATH_AVAILABLE: str = "available"

# How the sub folder for all detected instrument/host description files is called
FILE_PATH_HISTORY: str = "history"

# How the API sub path for available instrument/host descriptions is called
PATH_AVAILABLE: str = FILE_PATH_AVAILABLE

# How the API sub path for all detected instrument/host descriptions is called
PATH_HISTORY: str = FILE_PATH_HISTORY

# "available" and "history" under "devices"
FOLDER_AVAILABLE: str = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_AVAILABLE}'
FOLDER_HISTORY: str = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_HISTORY}'

# "available" and "history" under "hosts"
FOLDER2_AVAILABLE = f'{config["FOLDER2"]}{os.path.sep}{FILE_PATH_AVAILABLE}'
FOLDER2_HISTORY = f'{config["FOLDER2"]}{os.path.sep}{FILE_PATH_HISTORY}'

RESERVE_KEYWORD: str = "reserve"
FREE_KEYWORD: str = "free"
