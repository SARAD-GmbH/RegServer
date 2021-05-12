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
import sys
import threading
import time
from thespian.actors import ActorSystem  # type: ignore
#from inputimeout import inputimeout, TimeoutOccurred
import keyboard

import registrationserver2.logdef
from registrationserver2 import FOLDER_AVAILABLE, logger
from registrationserver2.config import config
from registrationserver2.modules.mqtt.mqtt_subscriber import \
    SaradMqttSubscriber
from registrationserver2.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver2.restapi import RestApi
from click.termui import prompt
from pickle import FALSE


def main():
    """Starting the RegistrationServer2

    * starts the actor system by importing registrationserver2
    * starts the API thread
    * starts the MdnsListener
    """
    # Prepare for closing
    @atexit.register
    def cleanup():  # pylint: disable=unused-variable
        """Make sure all sub threads are stopped, including the REST API"""
        logger.info("Cleaning up before closing.")
        if mqtt_subscriber is not None:
            if mqtt_subscriber.is_connected:
                mqtt_subscriber.stop()
        ActorSystem().shutdown()
        logger.debug("Actor system shut down finished.")
        if os.path.exists(FOLDER_AVAILABLE):
            logger.debug("Cleaning folder from available instruments")
            for root, _, files in os.walk(FOLDER_AVAILABLE):
                for name in files:
                    link = os.path.join(root, name)
                    logger.debug("[Del]:\tRemoved: %s", name)
                    os.unlink(link)

    def signal_handler(_sig, _frame):
        """On Ctrl+C: stop MQTT loop"""
        logger.info("You pressed Ctrl+C!")
        main.run = False

    mqtt_subscriber = None

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    ActorSystem(
        systemBase=config["systemBase"],
        capabilities=config["capabilities"],
        logDefs=registrationserver2.logdef.logcfg,
    )
    logger.debug("Actor system started.")
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
    mqtt_subscriber = SaradMqttSubscriber()

    """loop_run = True 
    while loop_run: 
        logger.info("After 2 seconds you can press 'e' to end")
        time.sleep(3)
        if keyboard.is_pressed('e'):
            logger.info("You have pressed 'e' to stop the whole stuff")
            loop_run = False
        else:
            mqtt_subscriber.mqtt_loop()
        
    logger.info("To cleanup")
    cleanup()"""

    logger.info("Press Ctrl+C to end!")
    main.run = True
    logger.debug("Start the MQTT subscriber loop")
    while main.run:
        if mqtt_subscriber is not None:
            mqtt_subscriber.mqtt_loop()
    cleanup()
    logger.debug("Time to say goodbye :-(")
    os.kill(os.getpid(), signal.SIGKILL)
    # If things go well the code after this line will never be reached.
    logger.debug("This is the end, my only friend, the end.")
    sys.exit(0)


if __name__ == "__main__":
    main()
