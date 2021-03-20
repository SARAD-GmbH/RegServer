"""
    Created on 30.09.2020

    @author: rfoerster

    Main executable
    TODO: Loads each module
    Loads / Starts Rest API
    Starts mDNS Listener (TODO: move to module)

    .. uml:: uml-main.puml

"""

import atexit
import importlib.util
import os
import pathlib
import signal
import threading
import time

from thespian.actors import ActorSystem  # type: ignore

import registrationserver2
from registrationserver2 import FOLDER_AVAILABLE, theLogger
from registrationserver2.restapi import RestApi

theLogger.info("%s -> %s", __package__, __file__)


def main():
    """Starting the RegistrationServer2"""
    registrationserver2.actor_system = ActorSystem()  # systemBase='multiprocQueueBase')
    time.sleep(2)
    restapi = RestApi()
    apithread = threading.Thread(
        target=restapi.run,
        args=(
            "0.0.0.0",
            8000,
        ),
    )
    apithread.start()
    parent_path = pathlib.Path(__file__).parent.absolute()
    modules_path = f"{parent_path}{os.path.sep}modules{os.path.sep}__init__.py"
    theLogger.info(modules_path)
    specification = importlib.util.spec_from_file_location("modules", modules_path)
    modules = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(modules)

    # Prepare for closing
    @atexit.register
    def cleanup():  # pylint: disable=unused-variable
        """Make sure all sub threads are stopped, including the REST API"""
        theLogger.info("Cleaning up before closing.")
        registrationserver2.actor_system.shutdown()
        if os.path.exists(FOLDER_AVAILABLE):
            for root, _, files in os.walk(FOLDER_AVAILABLE):
                for name in files:
                    link = os.path.join(root, name)
                    theLogger.debug("[Del]:\tRemoved: %s", name)
                    os.unlink(link)
        os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    main()
