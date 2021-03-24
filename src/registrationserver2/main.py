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
import os
import signal
import threading
import time

from thespian.actors import ActorSystem  # type: ignore

import registrationserver2
import registrationserver2.modules.rfc2217
import registrationserver2.modules.rfc2217.mdns_listener
import registrationserver2.modules.rfc2217.rfc2217_actor
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
