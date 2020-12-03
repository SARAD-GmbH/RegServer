'''
Created on 30.09.2020

@author: rfoerster
'''
import os
import ipaddress
import socket
import json
import traceback

import hashids
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

import registrationserver2
from registrationserver2.config import config
from registrationserver2 import theLogger
from registrationserver2.modules.rfc2217.rfc2217_actor import Rfc2217Actor

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
	__type : str

	def add_service(self, zc: Zeroconf, type_: str, name: str) -> None: #pylint: disable=C0103
		'''
			Hook, being called when a new service representing a device is being detected
		'''
		theLogger.info(f'[Add]:\tFound: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.info(f'[Add]:\t{info.properties}')
		#serial = info.properties.get(b'SERIAL', b'UNKNOWN').decode("utf-8")
		filename= fr'{self.__folder_history}{name}'
		link= fr'{self.__folder_available}{name}'
		try:
			data = self.convert_properties(name=name, info=info)
			if data:
				with open(filename, 'w+') as file_stream:
					file_stream.write(data) if data else theLogger.error(f'[Add]:\tFailed to convert Properties from {type_}, {name}') #pylint: disable=W0106
				if not os.path.exists(link):
					os.link(filename, link)
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'[Add]:\t {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error(f'[Add]:\tCould not write properties of device with Name: {name} and Type: {type_}')

		#if an actor already exists this will return the address of the excisting one, else it creates a new
		if data:
			this_actor = registrationserver2.actor_system.createActor(Rfc2217Actor, globalName = name)
			setup_return = registrationserver2.actor_system.ask(this_actor, {'CMD':'SETUP', 'PORT': 'rfc2217://serviri.hq.sarad.de:5580'})
			if setup_return is Rfc2217Actor.OK:
				theLogger.info(registrationserver2.actor_system.ask(this_actor, {"CMD":"SEND", "DATA":b'\x42\x80\x7f\x0c\x0c\x00\x45'}))
			if not (setup_return is Rfc2217Actor.OK or setup_return is Rfc2217Actor.OK_SKIPPED):
				registrationserver2.actor_system.ask(this_actor, {'CMD':'KILL'})

	def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None: #pylint: disable=C0103
		'''
			Hook, being called when a regular shutdown of a service representing a device is being detected
		'''
		theLogger.info(f'[Del]:\tRemoved: Service of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		#filename= fr'{self.__folder_history}{serial}'
		link= fr'{self.__folder_available}{name}'
		theLogger.debug('[Del]:\tInfo: %s' %(info))
		if os.path.exists(link):
			os.unlink(link)

	def update_service(self, zc: Zeroconf, type_: str, name: str) -> None: #pylint: disable=C0103
		'''
			Hook, being called when a  service representing a device is being updated
		'''
		theLogger.info(f'[Update]:\tService of type {type_}. Name: {name}')
		info = zc.get_service_info(type_, name, timeout=config['MDNS_TIMEOUT'])
		theLogger.info(f'[Update]:\tGot Info: {(info)}' )
		if not info:
			return
		#serial = info.properties.get("SERIAL", "UNKNOWN")
		filename= fr'{self.__folder_history}{info.name}'
		link= fr'{self.__folder_available}{info.name}'
		try:
			data = self.convert_properties(name = name, info=info)
			if data:
				with open(filename, 'w+') as file_stream:
					file_stream.write(data) if data else theLogger.error(f'[Update]:\tFailed to convert Properties from {type_}, {name}') #pylint: disable=W0106
				if not os.path.exists(link):
					os.link(filename, link)
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'[Update]:\t{type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error(f'[Update]:\tCould not write properties of device with Name: {name} and Type: {type_}')

	@staticmethod
	def convert_properties(info = None, name = ""):
		'''
			Helper function to convert mdns service information to the desired yaml format
		'''
		if not info or not name:
			return None

		properties = info.properties

		if not properties or not (_model := properties.get(b'MODEL_ENC',None)):
			return None

		_model = _model.decode('utf-8')

		if not (_serial_short := properties.get(b'SERIAL_SHORT',None)):
			return None

		_serial_short = _serial_short.decode('utf-8')
		hids = hashids.Hashids()

		if not (_ids := hids.decode(_serial_short)):
			return None

		if not (len(_ids) == 3) or not info.port:
			return None

		_addr = ''
		try:
			_addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
			_addr = socket.gethostbyaddr(_addr_ip)[0]
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
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
						'Address':	_addr_ip,
						'Port': info.port
					}
			}

		theLogger.debug(out)

		return json.dumps(out)

	def __init__(self,_type):
		'''
			Initialize a mdns Listener for a specific device group
		'''
		self.__type = type
		self.__zeroconf = Zeroconf()
		self.__browser = ServiceBrowser(self.__zeroconf,_type, self)
		self.__folder_history = f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}'
		self.__folder_available = f'{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}'
		#self.__folder_history = config.get('FOLDER', f'{os.environ.get("HOME",None) or os.environ.get("LOCALAPPDATA",None)}{os.path.sep}SARAD{os.path.sep}devices') + f'{os.path.sep}'
		if not os.path.exists(self.__folder_history):
			os.makedirs(self.__folder_history)
		if not os.path.exists(self.__folder_available):
			os.makedirs(self.__folder_available)

		theLogger.debug(f'Output to: {self.__folder_history}')
