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

from thespian.actors import ActorSystem  # type: ignore

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener

from registrationserver.config import actor_config, config
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger
from registrationserver.modules.mqtt.mqtt_listener import SaradMqttSubscriber
from registrationserver.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver.restapi import RestApi


def main():
    """Starting the RegistrationServer2

    * starts the actor system by importing registrationserver
    * starts the API thread
    * starts the MdnsListener
    """
    # Prepare for closing
    @atexit.register
    def cleanup():  # pylint: disable=unused-variable
        """Make sure all sub threads are stopped, including the REST API"""
        logger.info("Cleaning up before closing.")
        if mqtt_listener is not None:
            if mqtt_listener.is_connected:
                mqtt_listener.stop()
        dev_folder = config["DEV_FOLDER"]
        if os.path.exists(dev_folder):
            logger.info("Cleaning device folder")
            for root, _, files in os.walk(dev_folder):
                for name in files:
                    filename = os.path.join(root, name)
                    logger.info("[Del] %s removed", name)
                    os.remove(filename)
        ActorSystem().shutdown()
        logger.info("Actor system shut down finished.")

    def signal_handler(_sig, _frame):
        """On Ctrl+C: stop MQTT loop"""
        logger.info("You pressed Ctrl+C!")
        main.run = False

    try:
        with open(LOGFILENAME, "w") as _:
            pass
    except Exception:  # pylint: disable=broad-except
        logger.error("Initialization of log file failed.")
    logger.info("Logging system initialized.")

    mqtt_listener = None

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    ActorSystem(
        systemBase=actor_config["systemBase"],
        capabilities=actor_config["capabilities"],
        logDefs=logcfg,
    )
    logger.debug("Actor system started.")
    restapi = RestApi()
    apithread = threading.Thread(
        target=restapi.run,
        args=(
            "0.0.0.0",
            8000,
        ),
        daemon=True,
    )
    apithread.start()
    usb_listener = UsbListener()
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
        daemon=True,
    )
    usb_listener_thread.start()

    _ = MdnsListener(_type=config["TYPE"])
    mqtt_listener = SaradMqttSubscriber()

    logger.info("Press Ctrl+C to end!")
    main.run = True
    logger.debug("Start the MQTT subscriber loop")
    while main.run:
        if mqtt_listener is not None:
            mqtt_listener.mqtt_loop()
    cleanup()
    logger.debug("This is the end, my only friend, the end.")


if __name__ == "__main__":
    main()
