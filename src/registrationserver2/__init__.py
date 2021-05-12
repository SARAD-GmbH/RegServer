"""
Registration Server module,
connects all kinds of Instrument Server with the user applications
"""
import logging
import logging.config
import logging.handlers
import os

from zeroconf import IPVersion

import registrationserver2.logdef
from registrationserver2.config import config

# =======================
# Default values for configuration,
# is applied if a value is not set in config.py
# =======================
home = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
app_folder = f"{home}{os.path.sep}SARAD{os.path.sep}"
config.setdefault("FOLDER", f"{app_folder}devices")
config.setdefault("HOSTS_FOLDER", f"{app_folder}hosts")
config.setdefault("TYPE", "_rfc2217._tcp.local.")
config.setdefault("MDNS_TIMEOUT", 3000)
config.setdefault("PORT_RANGE", range(50000, 50500))
config.setdefault("HOST", "127.0.0.1")
config.setdefault("systemBase", "multiprocTCPBase")
config.setdefault("capabilities", "{'Admin Port': 1901}")
config.setdefault("ip_version", IPVersion.All)


# =======================
# Logging configuration
# The order is important! Setup logger after the actor system.
# =======================
logging.config.dictConfig(registrationserver2.logdef.logcfg)
logger = logging.getLogger("Reg. Server")
logger.info("Logging system initialized.")

# ==========================================
# Folders structure / API names for devices and device history
# TODO: move to configuration instead
# ==========================================

# How the sub folder for available instrument/host description files is called
FILE_PATH_AVAILABLE = "available"

# How the sub folder for all detected instrument/host description files is called
FILE_PATH_HISTORY = "history"

# How the API sub path for available instrument/host descriptions is called
PATH_AVAILABLE = FILE_PATH_AVAILABLE

# How the API sub path for all detected instrument/host descriptions is called
PATH_HISTORY = FILE_PATH_HISTORY

# "available" and "history" under "devices"
FOLDER_AVAILABLE = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_AVAILABLE}'
FOLDER_HISTORY = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_HISTORY}'

# "available" and "history" under "hosts"
HOSTS_FOLDER_AVAILABLE = f'{config["HOSTS_FOLDER"]}{os.path.sep}{FILE_PATH_AVAILABLE}'
HOSTS_FOLDER_HISTORY = f'{config["HOSTS_FOLDER"]}{os.path.sep}{FILE_PATH_HISTORY}'

RESERVE_KEYWORD = "reserve"
FREE_KEYWORD = "free"
logger.debug("Registrationserver initialized.")
