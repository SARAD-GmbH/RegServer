'''
Registration Server 2 module,
connects all kinds of Instrument Server 2 with the user applications
'''
# standard libraries
import os
import sys
import logging
import re

# 3rd party
from thespian.actors import ActorSystem

# local
from registrationserver2.config import config
# actor_system :ActorSystem = ActorSystem('multiprocTCPBase')
actor_system: ActorSystem = ActorSystem()

logging.basicConfig(format='[%(name)s]\t[%(levelname)s]:\t%(message)s',
                    level=logging.DEBUG)
logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')

mainpy = fr"{os.path.dirname(os.path.realpath(__file__))}{os.path.sep}main.py"
if __name__ == '__main__':
    exec(open(mainpy).read())
    sys.exit()

# =======================
# Default values for configuration,
# is applied if a value is not set in config.py
# =======================
config.setdefault(
    'FOLDER',
    f'{os.environ.get("HOME", None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}devices' )
config.setdefault('LEVEL', logging.CRITICAL)
config.setdefault('MDNS_TIMEOUT', 3000)
config.setdefault('TYPE', '_sarad-1688._rfc2217._tcp.local.')

# Initialization of the actor system,
# can be changed to a distributed system here.
# TODO:  Setup ActorSystem with values from the configuration

# ==========================================
# Logging configuration,
# TODO: configuration still gets overwritten by one of the imports
# ==========================================
theLogger = logging.getLogger('Instrument Server V2')
# theLogger = logging.getLogger()
werklog = logging.getLogger('werkzeug')
formatter = logging.Formatter('[%(name)s]\t[%(levelname)s]:\t%(message)s')
if werklog.handlers:
    for handler in werklog.handlers:
        werklog.removeHandler(handler)
if theLogger.handlers:
    for handler in theLogger.handlers:
        theLogger.removeHandler(handler)

streamh = logging.StreamHandler()
logging.basicConfig(
    level=logging.CRITICAL)  #, format=registrationserver2.formatter)
streamh.setFormatter(formatter)
werklog.addHandler(streamh)
werklog.addHandler(streamh)

theLogger.setLevel(config['LEVEL'])
werklog.setLevel(logging.CRITICAL)

theLogger.info("Test")

# ==========================================
# Folders structure / API names for devices and device history
# TODO: move to configuration instead
# ==========================================
matchid = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")

# How the sub folder for available instruments description files is called
FILE_PATH_AVAILABLE = 'available'

# How the sub folder for all detected instruments description files is called
FILE_PATH_HISTORY = 'history'

# How the API sub path for available instruments descriptions is called
PATH_AVAILABLE = FILE_PATH_AVAILABLE

# How the API sub path for all detected instruments descriptions is called
PATH_HISTORY = FILE_PATH_HISTORY

FOLDER_AVAILABLE = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_AVAILABLE}'
FOLDER_HISTORY = f'{config["FOLDER"]}{os.path.sep}{FILE_PATH_HISTORY}'

RESERVE_KEYWORD = 'reserve'
FREE_KEYWORD = 'free'
