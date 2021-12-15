""" Main executable of Instrument Server MQTT

Created
    2021-10-28

Authors
    Michael Strey <strey@sarad.de>
"""

import os
import sys
import threading
import time

from thespian.actors import ActorExitRequest  # type: ignore
from thespian.actors import Actor, ActorSystem, PoisonMessage

from registrationserver.config import AppType, actor_config, config
from registrationserver.device_db import DeviceDb
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger
from registrationserver.modules.mqtt_scheduler import MqttSchedulerActor
from registrationserver.modules.usb.cluster_actor import ClusterActor
from registrationserver.shutdown import is_flag_set, set_file_flag

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener


def cleanup():
    """Make sure all sub threads are stopped.

    * Initiates the shutdown of the actor system
    * Checks the device folder (that already should be empty at this time)
      and removes all files from there

    The usb_listener_thread doesn't need
    extra handling since it is daemonized and will be killed
    together with the main program.

    Returns:
        None"""
    logger.debug("Terminate the ClusterActor")
    cluster_actor = ActorSystem().createActor(Actor, globalName="cluster")
    response = ActorSystem().ask(cluster_actor, {"CMD": "KILL"})
    if isinstance(response, PoisonMessage):
        logger.critical("Critical error in cluster_actor. I will try to proceed.")
        logger.critical(response.details)
        ActorSystem().tell(cluster_actor, ActorExitRequest())
    logger.debug("Cluster_actor killed: %s", response)
    logger.info("Cleaning up before closing.")
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
    """Starting the Instrument Server MQTT

    * starts the actor system by importing registrationserver
    * creats the singleton Cluster Actor
    * creats the singleton MQTT Scheduler Actor
    * starts the usb_listener

    Returns:
        None
    """
    try:
        with open(LOGFILENAME, "w", encoding="utf8") as _:
            pass
    except Exception:  # pylint: disable=broad-except
        logger.error("Initialization of log file failed.")
    logger.info("Logging system initialized.")
    config["APP_TYPE"] = AppType.ISMQTT
    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    system = ActorSystem(
        systemBase=actor_config["systemBase"],
        capabilities=actor_config["capabilities"],
        logDefs=logcfg,
    )
    system.createActor(DeviceDb, globalName="device_db")
    system.createActor(ClusterActor, globalName="cluster")
    system.createActor(MqttSchedulerActor, globalName="mqtt_scheduler")
    logger.debug("Actor system started.")
    usb_listener = UsbListener()
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
        daemon=True,
    )
    usb_listener_thread.start()


def main():
    """This is the main function of the Instrument Server MQTT"""
    logger.debug("Entering main()")
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        startup()
        set_file_flag(True)
    elif start_stop == "stop":
        set_file_flag(False)
        time.sleep(5)
        set_file_flag(True)
        return None
    else:
        print("Usage: <program> start|stop")
        return None

    while is_flag_set():
        time.sleep(4)
    try:
        cleanup()
        set_file_flag(False)
    except UnboundLocalError:
        pass
    logger.debug("This is the end, my only friend, the end.")


if __name__ == "__main__":
    main()
