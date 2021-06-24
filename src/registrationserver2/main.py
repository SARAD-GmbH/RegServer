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

from thespian.actors import ActorSystem  # type: ignore

if os.name == "nt":
    from registrationserver2.modules.usb.win_usb_listener import UsbListener
else:
    from registrationserver2.modules.usb.linux_usb_listener import UsbListener

from zeroconf import IPVersion

from registrationserver2.config import actor_config, config
from registrationserver2.logdef import logcfg
from registrationserver2.logger import logger
from registrationserver2.modules.mqtt.mqtt_subscriber import \
    SaradMqttSubscriber
from registrationserver2.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver2.restapi import RestApi


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
        dev_folder = config["DEV_FOLDER"]
        if os.path.exists(dev_folder):
            logger.debug("Cleaning device folder")
            for root, _, files in os.walk(dev_folder):
                for name in files:
                    filename = os.path.join(root, name)
                    logger.debug("[Del] %s removed", name)
                    os.remove(filename)
        if os.name == "nt":
            os.kill(os.getpid(), signal.SIGTERM)
        sys.exit(0)

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
    )
    apithread.setDaemon(True)
    apithread.start()
    usb_listener = UsbListener()
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
    )
    usb_listener_thread.setDaemon(True)
    usb_listener_thread.start()

    _ = MdnsListener(_type=config["TYPE"])
    mqtt_subscriber = SaradMqttSubscriber()

    logger.info("Press Ctrl+C to end!")
    main.run = True
    logger.debug("Start the MQTT subscriber loop")
    while main.run:
        if mqtt_subscriber is not None:
            mqtt_subscriber.mqtt_loop()
    cleanup()
    logger.debug("This is the end, my only friend, the end.")


if __name__ == "__main__":
    # =======================
    # Default values for configuration,
    # is applied if a value is not set in config.py
    # =======================
    home = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
    app_folder = f"{home}{os.path.sep}SARAD{os.path.sep}"
    config.setdefault("DEV_FOLDER", f"{app_folder}devices")
    config.setdefault("IC_HOSTS_FOLDER", f"{app_folder}hosts")
    config.setdefault("TYPE", "_rfc2217._tcp.local.")
    config.setdefault("MDNS_TIMEOUT", 3000)
    config.setdefault("PORT_RANGE", range(50000, 50500))
    config.setdefault("HOST", "127.0.0.1")
    config.setdefault("systemBase", "multiprocTCPBase")
    config.setdefault("capabilities", "{'Admin Port': 1901}")
    config.setdefault("ip_version", IPVersion.All)

    main()
