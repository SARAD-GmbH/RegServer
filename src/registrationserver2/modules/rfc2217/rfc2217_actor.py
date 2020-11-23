'''
Created on 14.10.2020

@author: rfoerster
'''
import asyncio

import serial_asyncio
import thespian

from registrationserver2.modules.DeviceBaseActor import DeviceBaseActor

class Rfc2217Actor(DeviceBaseActor):
	'''
		Actor for dealing with RFC2217 Connections, creates and maintains a RFC2217Protocol handler and relays messages towards it
	https://pythonhosted.org/pyserial/pyserial_api.html#module-serial.aio
	'''

	def __send__(self, msg):
		return self.ILLEGAL_NOTIMPLEMENTED

	def __reserve__(self, msg):
		return self.ILLEGAL_NOTIMPLEMENTED

	def __free__(self, msg):
		return self.ILLEGAL_NOTIMPLEMENTED

	def __open_connection(self):
		pass
		#self.port = serial_asyncio.serial_for_url(self.config.uri)
		#self.port = serial_asyncio.
		#//self.port.han

class RFC2217Protocol(asyncio.Protocol):
	'''
		Handler for creating and managing connections to RFC2217 Services
	'''
	def connection_made(self, transport):
		pass

	def data_received(self, data):
		pass

	def connection_lost(self, exc):
		pass

	def pause_writing(self):
		pass

	def resume_writing(self):
		pass

	def eof_received(self):
		pass

if __name__ == '__main__':
	sys = thespian.actors.ActorSystem()
	sys.createActor(Rfc2217Actor, globalName='rfc2217://serviri.hq.sarad.de:5580')
