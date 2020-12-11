'''
Created on 02.10.2020

@author: rfoerster
'''

import socket
import os
import sys
import traceback

from flask import Flask, json, request, Response
from thespian.actors import Actor

import registrationserver2
from registrationserver2 import theLogger

if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	sys.exit()

class RestApi(Actor):
	'''
		Rest API
		delivers lists and info for devices
		relays reservation / free requests towards the instrument server 2 for the devices
		information is taken from the device info folder defined in both config.py (settings) and __init__.py (defaults)
		/*
		@startuml
		actor "Trucy" as user
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
		@enduml
		*/
	'''
	api = Flask(__name__)

	class Dummy:
		'''
			Dummy Output which just ignored messages
		'''
		@staticmethod
		def write(arg=None,**kwargs):
			'''
				Does Nothing
			'''
		@staticmethod
		def flush(arg=None,**kwargs):
			'''
				Does Nothing
			'''

	@staticmethod
	@api.route('/list', methods=['GET'])
	@api.route('/list/', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}/', methods=['GET'])
	def get_list():
		'''
			Path for getting the list of active devices
		'''
		answer = {}
		try:
			for dir_entry in os.listdir(registrationserver2.FOLDER_AVAILABLE):
				file = fr'{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}{dir_entry}'
				theLogger.debug(file)
				if os.path.isfile(file):
					theLogger.debug(file)
					answer[dir_entry] = { 'Identification' : json.load(open(file)).get('Identification', None)}
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")
		return resp

	@staticmethod
	@api.route('/list/<did>', methods=['GET'])
	@api.route('/list/<did>/', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}/<did>', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}/<did>/', methods=['GET'])
	def get_device(did):
		'''
			Path for getting Information for a single active device
		'''
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}{did}'):
				answer[did] = { 'Identification' :  json.load(open(f'{registrationserver2.FOLDER_AVAILABLE}{os.path.sep}{did}')).get('Identification', None)}
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error('!!!')

		resp = Response(
			response=json.dumps(answer),
			status=200,
			mimetype="application/json"
			)
		return resp

	@staticmethod
	@api.route(f'/{registrationserver2.PATH_HISTORY}', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_HISTORY}/', methods=['GET'])
	def get_history():
		'''
			Path for getting the list of all time detected devices
		'''
		answer = {}
		try:
			for dir_entry in os.listdir(f'{registrationserver2.FOLDER_HISTORY}'):
				if os.path.isfile(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{dir_entry}'):
					answer[dir_entry] =  { 'Identification' : json.load(open(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{dir_entry}')).get('Identification', None)}
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")
		return resp

	@staticmethod
	@api.route(f'/{registrationserver2.PATH_HISTORY}/<did>', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_HISTORY}/<did>/', methods=['GET'])
	def get_device_old(did):
		'''
		Path for getting information about a single previous or currently detected device
		'''
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{did}'):
				answer[did] =  { 'Identification' : json.load(open(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{did}')).get('Identification', None)}
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")
		return resp

	@staticmethod
	@api.route(f'/list/<did>/{registrationserver2.RESERVE_KEYWORD}', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}/<did>/{registrationserver2.RESERVE_KEYWORD}', methods=['GET'])
	def reserve_device(did):
		'''
			Path for reserving a single active device
		'''
		attribute_who = request.args.get('who')
		try:
			request_host = socket.gethostbyaddr(request.environ['REMOTE_ADDR'])[0]
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			request_host = request.environ['REMOTE_ADDR']
		theLogger.info(f'{did}:{attribute_who} --> {request_host}')
		
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		Reservation = {
				"Active": True,
				"Host": request_host,
				"App": attribute_who,
				"User": "rfoerster",
				"Timestamp": "2020-10-09T08:22:43Z",
				"IP": "123.123.123.123",
				"Port": 2345
			}
		
		try:
			if os.path.isfile(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{did}'):
				answer[did] =  { 'Identification' : json.load(open(f'{registrationserver2.FOLDER_HISTORY}{os.path.sep}{did}')).get('Identification', None)}
		except BaseException as error: #pylint: disable=W0703
			theLogger.error(f'! {type(error)}\t{error}\t{vars(error) if isinstance(error, dict) else "-"}\t{traceback.format_exc()}')
		except: #pylint: disable=W0702
			theLogger.error('!!!')
		
		answer[did]["Reservation"] = Reservation
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")
		
		return resp


	@staticmethod
	@api.route(f'/list/<did>/{registrationserver2.FREE_KEYWORD}', methods=['GET'])
	@api.route(f'/{registrationserver2.PATH_AVAILABLE}/<did>/{registrationserver2.FREE_KEYWORD}', methods=['GET'])
	def free_device(did):
		'''
			Path for freeing a single active device
		'''
		return json.dumps(f'{did}')

	def run(self, host=None, port=None, debug=None, load_dotenv=True):
		'''
			Start the API
		'''
		theLogger.info(f'Starting Api at {host}:{port}')
		std = sys.stdout
		sys.stdout = RestApi.Dummy
		self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
		sys.stdout = std
