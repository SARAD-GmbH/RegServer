'''
Created on 01.12.2020

@author: rfoerster
'''
import socket

from thespian.actors import Actor
from registrationserver2.modules import device_base_actor

class RedirectorActor(Actor):
	'''Creating port for listening to Packages from a SARAD© Application'''
	_sock : socket.socket
	_device : device_base_actor

	ILLEGAL_STATE = {"ERROR":"Actor not setup correctly, make sure to send SETUP message first", "ERROR_CODE" : 5} # The actor was in an wrong state
	ILLEGAL_WRONGTYPE = {"ERROR":"Wrong Message Type, dictionary Expected", "ERROR_CODE" : 3} # The message received by the actor was not in an expected type
	ILLEGAL_WRONGFORMAT = {"ERROR":"Misformatted or no message sent", "ERROR_CODE" : 1} # The message received by the actor was not in an expected format

	LOOP = {'CMD':'LOOP'}

	def receive(self):
		'''Listen to Port and redirect any messages'''
		(client_socket, client_address) = self._sock.accept()

	def receiveMessage(self, msg, sender): #pylint: disable=W0613,C0103 #@UnusedVariable
		'''Actor receive message loop'''

		if sender == self.myAddress and msg is self.LOOP:
			self.receive()
			self.send(self.myAddress, self.LOOP)
			return

		if not isinstance(msg,dict):
			self.send(sender, self.ILLEGAL_WRONGTYPE)
			return

		cmd_string= msg.get("CMD", None)

		if not cmd_string:
			self.send(sender, self.ILLEGAL_WRONGFORMAT)
			return

		if cmd_string == 'STARTUP':
			self._device = msg.get("DEVICE", None)
			if not self._device:
				self.send(sender, self.ILLEGAL_STATE)
			if not self._sock:	#create socket
				_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
				_sock.bind(('',0)) #listen to any address on any available port
				_sock.listen()
			if not self._sock:
				self.send(sender, self.ILLEGAL_STATE)
			self.send(sender, { 'DATA' : self._sock.getsockname()}) #send back the actual used port
