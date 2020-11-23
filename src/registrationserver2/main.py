'''
	Created on 30.09.2020

	@author: rfoerster

	Main executable
	TODO: Loads each module
	Loads / Starts Rest API
	Starts mDNS Listener (TODO: move to module) 
	/*
	@startuml
	box "RegistrationServer 2"
	entity "Main Executable" as main
	database "Configuration" as config
	entity "mDNS" as mdns
	entity "Rest API" as api
	database "Instrument Server Connectors" as modules
	end box
	main -> config : Loads with config.py
	main -> api : restapi.py
	main -> mdns : mdnsListener.py
	main -> modules : modules/*/
	@enduml
	*/
'''

import threading
import signal
import os

from registrationserver2.mdns_listener import SaradMdnsListener
from registrationserver2.restapi import RestApi
from registrationserver2.config import config



if __name__ == '__main__':
	if isinstance(config['TYPE'], list):
		Test = []
		for __type in config['TYPE']:
			Test.append(SaradMdnsListener(_type = __type))
	else:
		Test = SaradMdnsListener(_type = config['TYPE'])
	Test2 = RestApi()
	apithread = threading.Thread(target=Test2.run,args=('0.0.0.0', 8000,))
	apithread.start()
	try:
		input('Press Enter to End\n')
	finally:
		del Test
		os.kill(os.getpid(), signal.SIGTERM) #Self kill, mostly to make sure all sub threads are stopped, including the rest API
		