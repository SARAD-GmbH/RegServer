""" Main executable

Created
    2020-09-30

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml:: uml-main.puml
"""

import atexit
import os
import signal
import threading
import time

from thespian.actors import ActorSystem  # type: ignore

import registrationserver2
from registrationserver2 import FOLDER_AVAILABLE, theLogger
from registrationserver2.config import config
from registrationserver2.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver2.restapi import RestApi

theLogger.info("%s -> %s", __package__, __file__)


def main():
    """Starting the RegistrationServer2

    * starts the actor system
    * starts the API thread
    * starts the MdnsListener
    """
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
    _ = MdnsListener(_type=config["TYPE"])

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
