'''
Created on 13.10.2020

@author: rfoerster
'''
from builtins import staticmethod
import os
import traceback
from json.decoder import JSONDecodeError

from thespian.actors import Actor
import thespian
from flask import json

import registrationserver2
from registrationserver2 import theLogger

class DeviceBaseActor(Actor):
	'''
	classdocs
	/**
	@startuml
	actor "Alice" as user
	control "Sarad App" as app
	box "Registration Server 2" #pink
		entity "rest api" as api
		entity "device Actor" as deviceactor
	end box
	entity "device with Instrument Server" as device
	user->app:Changes Config /\n Requests Data

	group reservation
		app->api:Attempts to Reserve Device
		api->deviceactor:relays request
		deviceactor->device:relays request
		device->deviceactor:accepts request /\n relays port information
		deviceactor->device:connects
		deviceactor->deviceactor:opens port
		deviceactor->api:accepts request /\n relays port information
		api->app:relays port
	end
	note over deviceactor: start timeout
	group Data - repeats on unexpected disconnect
		app->deviceactor:connects
		note over deviceactor: refresh timeout
		group Commands without response
			app->deviceactor:sends data
			note over deviceactor: refresh timeout
			deviceactor->device:relays data
			app->user:"OK"
		end
		group Commands with response
			app->deviceactor:sends data
			note over deviceactor: refresh timeout
			deviceactor->device:relays data
			device->deviceactor:relays answer
			deviceactor->app:relays answer
		end
		app->user:displays answer
		app->deviceactor:disconnects
	end
	group free
		app->api:frees device
		api->deviceactor:relays free
		deviceactor->device:relays free
	end
	group timeout reached
		deviceactor->device:sends free
	end
	collections cake
	user->cake:has some
	@enduml
	*/
	'''
	ILLEGAL_WRONGFORMAT = {"ERROR":"Misformatted or no message sent", "ERROR_CODE" : 1} # The message received by the actor was not in an expected format
	ILLEGAL_NOTIMPLEMENTED = {"ERROR":"Not implemented", "ERROR_CODE" : 2} #The command received by the actor was not yet implemented by the implementing class
	ILLEGAL_WRONGTYPE = {"ERROR":"Wrong Message Type, dictionary Expected", "ERROR_CODE" : 3} # The message received by the actor was not in an expected type
	ILLEGAL_UNKNOWN_COMMAND = {"ERROR":"Unknown Command", "ERROR_CODE" : 4} # The message received by the actor was not in an expected type
	ILLEGAL_STATE = {"ERROR":"Actor not setup correctly, make sure to send SETUP message first", "ERROR_CODE" : 5} # The actor was in an wrong state
	OK_SKIPPED = { "RETURN" : "OK", "First": False }
	OK = { "RETURN" : "OK", "First": True}

	ACCEPTED_MESSAGES = {
			"RESERVE"	:	"__reserve__",	# is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible
			"FREE"	:	"__free__", # is being called when the end-user-application is done requesting / sending data, should return true as soon the freeing process has been initialized
			"SEND"	:	"__send__", # is being called when the end-user-application wants to send data, should return the direct or indirect response from the device, None in case the device is not reachable (so the end application can set the timeout itself)
			"ECHO"	:	"__echo__", # should returns what is send, main use is for testing purpose at this point
			"SETUP"	:	"__setup__",
			"KILL" : "__kill__"
		}
	'''
	Defines magic methods that are called when the specific message is received by the actor
	'''

	_config : dict = {}
	_file: json
	setup_done = False

	def receiveMessage(self, msg, sender):
		'''
			Handles received Actor messages / verification of the message format
		'''
		if isinstance(msg, thespian.actors.ActorExitRequest):
			return

		if not isinstance(msg,dict):
			self.send(sender, self.ILLEGAL_WRONGTYPE)
			return

		cmd_string= msg.get("CMD", None)

		if not cmd_string:
			self.send(sender, self.ILLEGAL_WRONGFORMAT)
			return

		cmd = self.ACCEPTED_MESSAGES.get(cmd_string,None)

		if not cmd:
			self.send(sender, self.ILLEGAL_UNKNOWN_COMMAND)
			return

		if not getattr(self,cmd,None):
			self.send(sender, self.ILLEGAL_NOTIMPLEMENTED)
			return

		self.send(sender,getattr(self,cmd)(msg))

	@staticmethod
	def __echo__(msg):
		return msg

	def __setup__(self, msg:dict):
		if not self.setup_done:
			self._config = msg
			filename=fr'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{self.globalName}'
			registrationserver2.theLogger.info(f'Setting up Actor {self.globalName}')
			if os.path.isfile(filename):
				try:
					file = open(filename)
					self._file = json.load(file)
					self.setup_done = True
					return self.OK
				except JSONDecodeError as error:
					registrationserver2.theLogger.error(f' Failed to parse {filename}')
					return self.ILLEGAL_STATE
				except BaseException as error: #pylint: disable=W0703
					registrationserver2.theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
					return self.ILLEGAL_STATE
			else:
				return self.ILLEGAL_STATE
		else:
			registrationserver2.theLogger.info(f'Actor already set up with {self._config}')
			return self.OK_SKIPPED

	def __kill__(self, msg:dict):
		registrationserver2.theLogger.info(f'Shutting down actor {self.globalName}, Message : {msg}')
		theLogger.info( registrationserver2.actor_system.ask(self.myAddress, thespian.actors.ActorExitRequest() ))
		#self.setup_done = False

	def __init__(self):
		super().__init__()
		self._config : dict = {}
		self._file: json
		self.setup_done = False
		