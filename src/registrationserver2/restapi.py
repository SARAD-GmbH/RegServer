'''
Created on 02.10.2020

@author: rfoerster
'''
import registrationserver2
from registrationserver2 import theLogger
from thespian.actors import Actor



if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit
	

from flask import Flask, json, request, Response
import socket
import os
import sys

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
class RestApi(Actor):
	api = Flask(__name__)
	

	class dummy:
		@staticmethod
		def write(arg=None,**kwargs):
			pass
		@staticmethod
		def flush(arg=None,**kwargs):
			pass
	'''
		Path for getting the list of active devices
	'''
	@staticmethod
	@api.route('/list', methods=['GET'])
	@api.route('/list/', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/', methods=['GET'])
	def getList():
		answer = {}
		try:
			for dir_entry in os.listdir(registrationserver2.folder_available):
				file = fr'{registrationserver2.folder_available}{os.path.sep}{dir_entry}'
				theLogger.debug(file)
				if os.path.isfile(file):
					theLogger.debug(file)
					answer[dir_entry] = { 'Identification' : json.load(open(file)).get('Identification', None)}
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
	'''
		Path for getting Information for a single active device
	'''	
	@staticmethod
	@api.route('/list/<did>', methods=['GET'])
	@api.route('/list/<did>/', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/<did>', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/<did>/', methods=['GET'])
	def getDevice(did):
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.folder_available}{os.path.sep}{did}'):
				answer[did] = { 'Identification' :  json.load(open(f'{registrationserver2.folder_available}{os.path.sep}{did}')).get('Identification', None)}
		except: 
			theLogger.error('!!!')
		
		resp = Response(
			response=json.dumps(answer),
			status=200,
			mimetype="application/json"
			)	    	
		return resp
	
	'''
		Path for getting the list of all time detected devices
	'''
	@staticmethod
	@api.route(f'/{registrationserver2.path_history}', methods=['GET'])
	@api.route(f'/{registrationserver2.path_history}/', methods=['GET'])
	def getHistory():
		answer = {}
		try:
			for dir_entry in os.listdir(f'{registrationserver2.folder_history}'):
				if os.path.isfile(f'{registrationserver2.folder_history}{os.path.sep}{dir_entry}'):
					answer[dir_entry] =  { 'Identification' : json.load(open(f'{registrationserver2.folder_history}{os.path.sep}{dir_entry}')).get('Identification', None)}
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
	'''
		Path for getting information about a single previous or currently detected device 
	'''	
	@staticmethod
	@api.route(f'/{registrationserver2.path_history}/<did>', methods=['GET'])
	@api.route(f'/{registrationserver2.path_history}/<did>/', methods=['GET'])
	def getDeviceOld(did):
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.folder_history}{os.path.sep}{did}'):
				answer[did] =  { 'Identification' : json.load(open(f'{registrationserver2.folder_history}{os.path.sep}{did}')).get('Identification', None)}
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
	'''
		Path for reserving a single active device
	'''
	@staticmethod
	@api.route(f'/list/<did>/{registrationserver2.reserve_keyword}', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/<did>/{registrationserver2.reserve_keyword}', methods=['GET'])
	def reserveDevice(did):
		whoname = request.args.get('who')
		try:
			whohost = socket.gethostbyaddr(request.environ['REMOTE_ADDR'])[0]
		except:
			whohost = request.environ['REMOTE_ADDR']
		return json.dumps(f'{did}:{whoname} --> {whohost}')
	
		#return json.dumps(vars(request))

	'''
		Path for freeing a single active device
	'''
	@staticmethod
	@api.route(f'/list/<did>/{registrationserver2.free_keyword}', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/<did>/{registrationserver2.free_keyword}', methods=['GET'])
	def freeDevice(did):
		return json.dumps(f'{did}')

	
	def run(self, host=None, port=None, debug=None, load_dotenv=True):
		theLogger.info(f'Starting Api at {host}:{port}')
		std = sys.stdout
		sys.stdout = RestApi.dummy
		self.api.run(host=host, port=port, debug=debug, load_dotenv=load_dotenv)
		sys.stdout = std
