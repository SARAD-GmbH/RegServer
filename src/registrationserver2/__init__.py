
import os
import registrationserver2
mainpy = fr"{os.path.dirname(os.path.realpath(__file__))}{os.path.sep}main.py"

if __name__ == '__main__':
	exec(open(mainpy).read())
	exit

import logging

import re
from registrationserver2.config import config 

config.setdefault('FOLDER', f'{os.environ.get("HOME",None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}devices')
config.setdefault('LEVEL', logging.CRITICAL)
config.setdefault('MDNS_TIMEOUT', 3000)	
config.setdefault('TYPE', '_sarad-1688._rfc2217._tcp.local.')

logging.basicConfig(level=logging.CRITICAL,format='[%(name)s]\t[%(levelname)s]:\t%(message)s')
global theLogger
theLogger = logging.getLogger('Instrument Server V2')
logging.root.setLevel(logging.CRITICAL)
werklog = logging.getLogger('werkzeug')	
formatter = logging.Formatter('[%(name)s]\t[%(levelname)s]:\t%(message)s')
if werklog.handlers:
	for handler in werklog.handlers:
		werklog.removeHandler(handler)
if theLogger.handlers:
	for handler in theLogger.handlers:
		theLogger.removeHandler(handler)
		
global streamh		
streamh = logging.StreamHandler()
logging.basicConfig(level=logging.CRITICAL, formatter=formatter)
streamh.setFormatter(formatter)
werklog.addHandler(streamh)
werklog.addHandler(streamh)

theLogger.setLevel(config['LEVEL'])
werklog.setLevel(logging.CRITICAL) 


theLogger.info("Test")

#@TODO: move to config instead

global matchid 
matchid = re.compile(r"^[0-9a-zA-Z]+[0-9a-zA-Z_\.-]*$")

file_path_available = 'available'
file_path_history = 'history'

path_available = file_path_available
path_history = file_path_history

folder_available = f'{config["FOLDER"]}{os.path.sep}{file_path_available}'
folder_history = f'{config["FOLDER"]}{os.path.sep}{file_path_history}'

reserve_keyword = 'reserve'
free_keyword = 'free'
