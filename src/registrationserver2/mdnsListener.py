'''
Created on 30.09.2020

@author: rfoerster
'''

import registrationserver2
import ipaddress

if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit

import os
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from registrationserver2.config import config
from registrationserver2 import theLogger
import json
import hashids
import socket

class SaradMdnsListener(ServiceListener):
	'''
	/**
	classdocs
	@startuml
	actor "Service Employee" as user
	entity "Device with Instrument Server" as is2
	box "RegistrationServer 2"
	entity "SaradMdnsListener" as rs2
	entity "mDNS Actor" as mdnsactor
	database "Device List" as list
	end box
	user -> is2 : connect to local network
	is2 -> rs2 : Sends mDNS over multicast
	rs2 -> list : creates / updates device description file
	rs2 -> list : links device into the available list
	rs2 -> mdnsactor : creates listener (Actor) to receive commands / data
	user -> is2 : disconnects from network
	is2 -> rs2 : sends disconnect over mDNS
	rs2 -> list : unlinks device from the available list
	rs2 -> mdnsactor: destroy
	
	@enduml

	*/
	'''
	__zeroconf : Zeroconf
	__browser: ServiceBrowser
	__folder_history : str
	__folder_available : str
	
	'''
		Hook, being called when a new service representing a device is being detected 
	'''
	def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'[Add]:\tFound: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.debug(f'[Add]:\t{info.properties}' )
		#serial = info.properties.get(b'SERIAL', b'UNKNOWN').decode("utf-8")
		filename= fr'{self.__folder_history}{name}'
		link= fr'{self.__folder_available}{name}'
		try:
			with open(filename, 'w+') as f:
				data = self.convertProperties(name=name, info=info)
				f.write(data)
			if not os.path.exists(link):
				os.link(filename, link)
			
		except:
			theLogger.error(f'Could not write properties of device with Name: {name} and Type: {type_}')

	'''
		Hook, being called when a regular shutdown of a service representing a device is being detected 
	'''
	def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'Removed: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		#filename= fr'{self.__folder_history}{serial}'
		link= fr'{self.__folder_available}{name}'
		theLogger.debug('[Del]:\tInfo: %s' %(info))
		if os.path.exists(link):
			os.unlink(link)

	'''
		Hook, being called when a  service representing a device is being updated 
	'''
	def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
		theLogger.info(f'[Update]:\tService of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.info(f'[Update]:\tGot Info: {(info)}' )
		if not info:
			return
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		filename= fr'{self.__folder_history}{info.name}'
		link= fr'{self.__folder_available}{info.name}'
		try:
			with open(filename, 'w+') as f:
				data = self.convertProperties(name = name, info=info)
				f.write(data)
			if not os.path.exists(link):
				os.link(filename, link)
			
		except:
			theLogger.error(f'Could not write properties of device with Name: {name} and Type: {type_}')
		
	'''
		Helper function to convert mdns service information to the desired yaml format 
	'''	
	def convertProperties(self, info = None, name = ""):
		
		if not info:
			return None
		
		
		properties = info.properties
		
		
		if not properties:
			return None
		
		if not name: 
			return None		
		
		if not (_model := properties.get(b'MODEL_ENC',None)):
			return None
		
		_model = _model.decode('utf-8')
		
		if not (_serial_short := properties.get(b'SERIAL_SHORT',None)):
			return None
		
		_serial_short = _serial_short.decode('utf-8')
		hids = hashids.Hashids()
		
		if not (_ids := hids.decode(_serial_short)):
			return None
		
		if not (len(_ids) == 3):
			return None
		
		if not info.port:
			return None
		
		_addr = ''
		try: 
			_addrIp = ipaddress.IPv4Address(info.addresses[0]).exploded
			_addr = socket.gethostbyaddr(_addrIp)[0]
		except:
			pass
			
		out = {
				'Identification' : 
					{
						'Name' : properties[b'MODEL_ENC'].decode("utf-8"),
						"Family": _ids[0],
						"Type": _ids[1],
						"Serial number": _ids[2],
						"Host": _addr
						
					}, 
				'Remote' :
					{
						'Address':	_addrIp,
						'Port': info.port	
					}
			}
		#try:
		
		theLogger.debug(out)

		return json.dumps(out)
		
		for item in properties:
			out[item.decode("utf-8")]=properties.get(item).decode("utf-8")
		return json.dumps(out)
		#except ValueError as that:
		#theLogger.error(that)

	'''
		Initialize a mdns Listener for a specific device group 
	'''
	def __init__(self,_type):
		'''
		Constructor
		'''
		self.__zerconf = Zeroconf()
		self.__browser = ServiceBrowser(self.__zerconf,_type, self)
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
