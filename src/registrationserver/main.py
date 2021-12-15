""" Main executable when running as Registration Server

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-main.puml
"""

import os
import sys
import threading

from thespian.actors import ActorSystem  # type: ignore

from registrationserver.modules.usb.cluster_actor import ClusterActor

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener

from datetime import datetime

from registrationserver.config import AppType, actor_config, config, home
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger
from registrationserver.modules.mqtt.mqtt_listener import SaradMqttSubscriber
from registrationserver.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver.restapi import RestApi
from registrationserver.shutdown import is_flag_set, set_file_flag


def mqtt_loop(mqtt_listener):
    if mqtt_listener is not None:
        mqtt_listener.mqtt_loop()


def cleanup(mqtt_listener, mdns_listener):
    """Make sure all sub threads are stopped.

    * Stops the mqtt_listener if it is existing
    * Stops the mdns_listener if it is existing
    * Initiates the shutdown of the actor system
    * Checks the device folder (that already should be empty at this time)
      and removes all files from there

    The REST API thread and the usb_listener_thread don't need
    extra handling since they are daemonized and will be killed
    together with the main program.

    Args:
        mqtt_listener: An instance of SaradMqttSubscriber
        mdns_listener: An instance of MdnsListener

    Returns:
        None"""
    logger.info("Cleaning up before closing.")
    if mqtt_listener is not None:
        if mqtt_listener.is_connected:
            mqtt_listener.stop()
    if mdns_listener is not None:
        mdns_listener.shutdown()
    ActorSystem().shutdown()
    logger.info("Actor system shut down finished.")
    dev_folder = config["DEV_FOLDER"]
    if os.path.exists(dev_folder):
        logger.info("Cleaning device folder")
        for root, _, files in os.walk(dev_folder):
            for name in files:
                filename = os.path.join(root, name)
                logger.info("[Del] %s removed", name)
                os.remove(filename)


def startup():
    """Starting the RegistrationServer

    * starts the actor system by importing registrationserver
    * starts the API thread
    * starts the MdnsListener

    Returns:
        Object of type MdnsListener
    """
    try:
        with open(LOGFILENAME, "w", encoding="utf8") as _:
            pass
    except Exception:  # pylint: disable=broad-except
        logger.error("Initialization of log file failed.")
    logger.info("Logging system initialized.")
    config["APP_TYPE"] = AppType.RS
    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    system = ActorSystem(
        systemBase=actor_config["systemBase"],
        capabilities=actor_config["capabilities"],
        logDefs=logcfg,
    )
    system.createActor(ClusterActor, globalName="cluster")
    logger.debug("Actor system started.")

    restapi = RestApi()
    apithread = threading.Thread(
        target=restapi.run,
        args=(
            config["HOST"],
            config["API_PORT"],
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

    return MdnsListener(service_type=config["TYPE"])


def main():
    logger.debug("Entering main()")
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        logger.debug("Starting the MQTT subscriber loop")
        mqtt_listener = None
        mdns_listener = startup()
        mqtt_listener = SaradMqttSubscriber()
        set_file_flag(True)
    elif start_stop == "stop":
        logger.debug("Stopping the MQTT subscriber loop")
        set_file_flag(False)
        return None
    else:
        print("Usage: <program> start|stop")
        return None

    while is_flag_set():
        before = datetime.now()
        mqtt_loop(mqtt_listener)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug(
                "Wakeup from suspension. Shutting down RegServer for a fresh restart."
            )
            set_file_flag(False)
    try:
        cleanup(mqtt_listener, mdns_listener)
    except UnboundLocalError:
        pass
    logger.debug("This is the end, my only friend, the end.")


if __name__ == "__main__":
    main()
