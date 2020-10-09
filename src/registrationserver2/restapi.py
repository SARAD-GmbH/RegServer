'''
Created on 02.10.2020

@author: rfoerster
'''
import registrationserver2
from registrationserver2 import theLogger



if __name__ == '__main__':
	exec(open(registrationserver2.mainpy).read())
	exit
	

from flask import Flask, json, request, Response
import socket
import os
import sys

class RestApi():
	api = Flask(__name__)
	

	class dummy:
		@staticmethod
		def write(arg=None,**kwargs):
			pass
		@staticmethod
		def flush(arg=None,**kwargs):
			pass
	
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
					answer[dir_entry] =  json.load(open(file))
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
	@staticmethod
	@api.route('/list/<did>', methods=['GET'])
	@api.route(f'/{registrationserver2.path_available}/<did>', methods=['GET'])
	def getDevice(did):
		if not registrationserver2.matchid.fullmatch(did):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.folder_available}{os.path.sep}{did}'):
				answer[did] =  json.load(open(f'{registrationserver2.folder_available}{os.path.sep}{did}'))
		except: 
			theLogger.error('!!!')
		
		resp = Response(
			response=json.dumps(answer),
			status=200,
			mimetype="application/json"
			)	    	
		return resp
	
	@staticmethod
	@api.route(f'/{registrationserver2.path_history}', methods=['GET'])
	@api.route(f'/{registrationserver2.path_history}/', methods=['GET'])
	def getHistory():
		answer = {}
		try:
			for dir_entry in os.listdir(f'{registrationserver2.folder_history}'):
				if os.path.isfile(f'{registrationserver2.folder_history}{os.path.sep}{dir_entry}'):
					answer[dir_entry] =  json.load(open(f'{registrationserver2.folder_history}{os.path.sep}{dir_entry}'))
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
	
	@staticmethod
	@api.route(f'/{registrationserver2.path_history}/<did>', methods=['GET'])
	def getDeviceOld(did):
		if not registrationserver2.matchid.fullmatch(id):
			return json.dumps({'Error': 'Wronly formated ID'})
		answer = {}
		try:
			if os.path.isfile(f'{registrationserver2.folder_history}{os.path.sep}{did}'):
				answer[id] =  json.load(open(f'{registrationserver2.folder_history}{os.path.sep}{did}'))
		except: 
			theLogger.error('!!!')
		resp = Response(response=json.dumps(answer),
			status=200,
			mimetype="application/json")	    	
		return resp
	
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
		

