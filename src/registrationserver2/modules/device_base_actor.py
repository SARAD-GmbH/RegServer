'''
Created on 13.10.2020

@author: rfoerster
'''
from builtins import staticmethod
import os
import traceback
import logging
from json.decoder import JSONDecodeError

from thespian.actors import Actor
import thespian
from flask import json

import registrationserver2
from registrationserver2 import theLogger
from registrationserver2.messages import RETURN_MESSAGES

logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')

class DeviceBaseActor(Actor):
    '''
    .. uml:: uml-device_base_actor.puml

	'''
	ACCEPTED_MESSAGES = {
		#Those needs implementing
			"SEND"	:	"__send__", # is being called when the end-user-application wants to send data, should return the direct or indirect response from the device, None in case the device is not reachable (so the end application can set the timeout itself)
			"SEND_RESERVE" : "__send_reserve__", # is being called when the end-user-application wants to reserve the directly or indirectly connected device for exclusive communication, should return if a reservation is currently possible
			"SEND_FREE" : "__send_free__",

		#Those are implemented by the base class (this class)
			"ECHO"	:	"__echo__", # should returns what is send, main use is for testing purpose at this point
			"FREE"	:	"__free__", # is being called when the end-user-application is done requesting / sending data, should return true as soon the freeing process has been initialized
			"SETUP"	:	"__setup__",
			"RESERVE"	:	"__reserve__",
			"KILL"	:	"__kill__",
		}
	'''
	Defines magic methods that are called when the specific message is received by the actor
	'''

    _config: dict = {}
    _file: json
    setup_done = False
	reservation: dict

    def receiveMessage(self, msg, sender):
        '''
			Handles received Actor messages / verification of the message format
		'''
        if isinstance(msg, thespian.actors.ActorExitRequest):
            return

		if not isinstance(msg,dict):
			self.send(sender, RETURN_MESSAGES.get('ILLEGAL_WRONGTYPE'))
			return

		cmd_string= msg.get("CMD", None)

		if not cmd_string:
			self.send(sender, RETURN_MESSAGES.get('ILLEGAL_WRONGFORMAT'))
			return

		cmd = self.ACCEPTED_MESSAGES.get(cmd_string,None)

		if not cmd:
			self.send(sender, RETURN_MESSAGES.get('ILLEGAL_UNKNOWN_COMMAND'))
			return

		if not getattr(self,cmd,None):
			self.send(sender, RETURN_MESSAGES.get('ILLEGAL_NOTIMPLEMENTED'))
			return

		self.send(sender,getattr(self,cmd)(msg))

	@staticmethod
	def __echo__(msg:dict)->dict:
		msg.pop('CMD', None)
		msg.pop('RETURN', None)
		msg['RETURN'] = True
		return msg

	def __setup__(self, msg:dict)->dict:
		if not self.setup_done:
			self._config = msg
			filename=fr'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{self.globalName}'
			registrationserver2.theLogger.info(f'Setting up Actor {self.globalName}')
			if os.path.isfile(filename):
				try:
					file = open(filename)
					self._file = json.load(file)
					self.setup_done = True
					return RETURN_MESSAGES.get('OK')
				except JSONDecodeError as error:
					registrationserver2.theLogger.error(f' Failed to parse {filename}')
					return RETURN_MESSAGES.get('ILLEGAL_STATE')
				except BaseException as error: #pylint: disable=W0703
					registrationserver2.theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
					return RETURN_MESSAGES.get('ILLEGAL_STATE')
			else:
				return RETURN_MESSAGES.get('ILLEGAL_STATE')
		else:
			registrationserver2.theLogger.info(f'Actor already set up with {self._config}')
			return RETURN_MESSAGES.get('OK_SKIPPED')

	def __kill__(self, msg:dict) -> dict: # TODO move to Actor Manager
		registrationserver2.theLogger.info(f'Shutting down actor {self.globalName}, Message : {msg}')
		theLogger.info( registrationserver2.actor_system.ask(self.myAddress, thespian.actors.ActorExitRequest() ))
		#self.setup_done = False

	def __reserve__(self, msg:dict) -> dict:
		pass

	def __init__(self):
		super().__init__()
		self._config : dict = {}
		self._file: json
		self.setup_done = False
