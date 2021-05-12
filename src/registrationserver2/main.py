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
        if mqtt_subscriber.is_connected:
            mqtt_subscriber.stop()
        ActorSystem().shutdown()
        logger.debug("Actor system shut down finished.")
        if os.path.exists(FOLDER_AVAILABLE):
            for root, _, files in os.walk(FOLDER_AVAILABLE):
                for name in files:
                    link = os.path.join(root, name)
                    logger.debug("[Del]:\tRemoved: %s", name)
                    os.unlink(link)
        os.kill(os.getpid(), signal.SIGTERM)

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

    """try:
        logger.info("Press ENTER to end!")
        input("Press ENTER to end\n")
    finally:
        cleanup()"""
    
    loop_run = True 
    while loop_run: 
        """try:
            logger.info("You have 2 seconds: Press Enter to End")
            something = inputimeout(prompt=">>", timeout=4)
            logger.info(something)
            loop_run = False
        except TimeoutOccurred:
            logger.info("keep running")
            mqtt_subscriber.mqtt_loop()
            loop_run = True"""
        logger.info("After 2 seconds you can press 'e' to end")
        time.sleep(3)
        if keyboard.is_pressed('e'):
            logger.info("You have pressed 'e' to stop the whole stuff")
            loop_run = False
        else:
            mqtt_subscriber.mqtt_loop()
        
    logger.info("To cleanup")
    cleanup()

if __name__ == "__main__":
    main()
