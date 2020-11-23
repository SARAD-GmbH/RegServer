'''
	Registration Server 2 module, connects all kind of instrument server 2 with the user applications
'''
#standard libraries
import os
import sys
import logging
import re

#3rd party
from thespian.actors import ActorSystem

#local
from registrationserver2.config import config

mainpy = fr"{os.path.dirname(os.path.realpath(__file__))}{os.path.sep}main.py"
if __name__ == '__main__':
	exec(open(mainpy).read())
	sys.exit()

#=======================
#	Default values for configuration, is applied if a value is not set in config.py
#=======================
config.setdefault('FOLDER', f'{os.environ.get("HOME",None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}devices')
config.setdefault('LEVEL', logging.CRITICAL)
config.setdefault('MDNS_TIMEOUT', 3000)
config.setdefault('TYPE', '_sarad-1688._rfc2217._tcp.local.')

actors = ActorSystem() # Initialization of the actor system, can be changed to a distributed system here. TODO:  Setup ActorSystem with values from the configuration


#==========================================
#	Logging configuration,
#	TODO: configuration still gets overwritten but one of the imports
#==========================================
theLogger = logging.getLogger('Instrument Server V2')
#theLogger = logging.getLogger()
werklog = logging.getLogger('werkzeug')
formatter = logging.Formatter('[%(name)s]\t[%(levelname)s]:\t%(message)s')
if werklog.handlers:
	for handler in werklog.handlers:
		werklog.removeHandler(handler)
if theLogger.handlers:
	for handler in theLogger.handlers:
		theLogger.removeHandler(handler)

streamh = logging.StreamHandler()
logging.basicConfig(level=logging.CRITICAL, formatter=formatter)
streamh.setFormatter(formatter)
werklog.addHandler(streamh)
werklog.addHandler(streamh)

theLogger.setLevel(config['LEVEL'])
werklog.setLevel(logging.CRITICAL) 

theLogger.info("Test")

#==========================================
#	Folders structure / APi names for devices and device history
#	TODO: move to configuration instead
#==========================================
matchid = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")

file_path_available = 'available'
file_path_history = 'history'

path_available = file_path_available
path_history = file_path_history

folder_available = f'{config["FOLDER"]}{os.path.sep}{file_path_available}'
folder_history = f'{config["FOLDER"]}{os.path.sep}{file_path_history}'

reserve_keyword = 'reserve'
free_keyword = 'free'
