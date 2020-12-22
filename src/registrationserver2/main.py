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
import time
import importlib.util
import pathlib
from thespian.actors import ActorSystem
from registrationserver2.restapi import RestApi
import registrationserver2
from registrationserver2 import theLogger
#import registrationserver2.modules #pylint: disable=W0611 #@UnusedImport


def main():
    '''Starting the RegistrationServer2'''
    registrationserver2.actor_system = ActorSystem()  #systemBase='multiprocQueueBase')
    time.sleep(2)
    test2 = RestApi()
    apithread = threading.Thread(target=test2.run, args=(
        '0.0.0.0',
        8000,
    ))
    apithread.start()

    modules_path = f'{pathlib.Path(__file__).parent.absolute()}{os.path.sep}modules{os.path.sep}__init__.py'
    theLogger.info(modules_path)
    specification = importlib.util.spec_from_file_location(
        "modules", modules_path)
    modules = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(modules)

    try:
        input('Press Enter to End\n')
    finally:
        registrationserver2.actor_system.shutdown()
        os.kill(
            os.getpid(), signal.SIGTERM
        )  #Self kill, mostly to make sure all sub threads are stopped, including the rest API


if __name__ == '__main__':
    main()
