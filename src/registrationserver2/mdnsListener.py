'''
Created on 30.09.2020

@author: rfoerster
'''

import registrationserver2

if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit

import os
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from registrationserver2.config import config
from registrationserver2 import theLogger
import json

class SaradMdnsListener(ServiceListener):
	'''
	classdocs
	'''
	__zeroconf : Zeroconf
	__browser: ServiceBrowser
	__folder_history : str
	__folder_available : str
	
	def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'[Add]:\tFound: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.debug(f'[Add]:\t{info.properties}' )
		#serial = info.properties.get(b'SERIAL', b'UNKNOWN').decode("utf-8")
		filename= fr'{self.__folder_history}{name}'
		link= fr'{self.__folder_available}{name}'
		try:
			with open(filename, 'w+') as f:
				data = self.convertProperties(name=name, properties=info.properties)
				f.write(data)
			if not os.path.exists(link):
				os.link(filename, link)
			
		except:
			theLogger.error(f'Could not write properties of device with Name: {name} and Type: {type_}')

	def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'Removed: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		#filename= fr'{self.__folder_history}{serial}'
		link= fr'{self.__folder_available}{name}'
		theLogger.debug('[Del]:\tInfo: %s' %(info))
		if os.path.exists(link):
			os.unlink(link)

	def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'[Update]:\tService of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.info(f'[Update]:\tGot Info: {info.properties}' )
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		filename= fr'{self.__folder_history}{name}'
		link= fr'{self.__folder_available}{name}'
		try:
			with open(filename, 'w+') as f:
				data = self.convertProperties(name = name, properties = info.properties)
				f.write(data)
			if not os.path.exists(link):
				os.link(filename, link)
			
		except:
			theLogger.error(f'Could not write properties of device with Name: {name} and Type: {type_}')
			
	def convertProperties(self, properties = None, name = ""):
		
		if not properties or not name or not properties.get(b'MODEL_ENC',None):			
			return None
		out = {
				'Location' : 
					{
						'Name' : properties[b'MODEL_ENC'].decode("utf-8")
						
					} 
			}
		#try:

		return json.dumps(out)
		
		for item in properties:
			out[item.decode("utf-8")]=properties.get(item).decode("utf-8")
		return json.dumps(out)
		#except ValueError as that:
		#theLogger.error(that)

	def __init__(self):
		'''
		Constructor
		'''
		self.__zerconf = Zeroconf()
		self.__browser = ServiceBrowser(self.__zerconf,config.get('TYPE', '_rfc2217._tcp.local.'), self)
		self.__folder_history = f'{config["FOLDER"]}{os.path.sep}history{os.path.sep}'
		self.__folder_available = f'{config["FOLDER"]}{os.path.sep}available{os.path.sep}'
		#self.__folder_history = config.get('FOLDER', f'{os.environ.get("HOME",None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}devices') + f'{os.path.sep}'
		if not os.path.exists(self.__folder_history):
				os.makedirs(self.__folder_history)
		if not os.path.exists(self.__folder_available):
				os.makedirs(self.__folder_available)
		
		theLogger.debug(f'Output to: {self.__folder_history}')
		
	def __del__(self):
		self.__zerconf.close()
