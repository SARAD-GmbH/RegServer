"""
    Created on 30.09.2020

    @author: rfoerster

    Main executable
    TODO: Loads each module
    Loads / Starts Rest API
    Starts mDNS Listener (TODO: move to module)

    .. uml:: uml-main.puml

"""

import threading
import signal
import os
import time
import importlib.util
import pathlib
import logging
from thespian.actors import ActorSystem
import sys
#sys.path.append('C:\\Users\\Yixiang\\Documents\\Projekte\\git\\SARAD\\src-registrationserver2\\src')
print(sys.path)
from registrationserver2.restapi import RestApi
import registrationserver2
from registrationserver2 import theLogger

# import registrationserver2.modules #pylint: disable=W0611 #@UnusedImport

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")


def main():
    """Starting the RegistrationServer2"""
    registrationserver2.actor_system = ActorSystem()  # systemBase='multiprocQueueBase')
    time.sleep(2)
    test2 = RestApi()
    apithread = threading.Thread(
        target=test2.run,
        args=(
            "0.0.0.0",
            8000,
        ),
    )
    apithread.start()

    modules_path = f"{pathlib.Path(__file__).parent.absolute()}{os.path.sep}modules{os.path.sep}__init__.py"
    theLogger.info(modules_path)
    specification = importlib.util.spec_from_file_location("modules", modules_path)
    modules = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(modules)

    try:
        input("Press Enter to End\n")
    finally:
        registrationserver2.actor_system.shutdown()
        os.kill(
            os.getpid(), signal.SIGTERM
        )  # Self kill, mostly to make sure all sub threads are stopped, including the REST API


if __name__ == "__main__":
    main()
