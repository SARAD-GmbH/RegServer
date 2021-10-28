""" Main executable of Instrument Server MQTT

Created
    2021-10-28

Authors
    Michael Strey <strey@sarad.de>
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

from registrationserver.config import actor_config, config, home
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger

FLAGFILENAME = f"{home}{os.path.sep}startstop.file"


def set_file_flag(startorstop):
    # In this case I am using a simple file, but the flag could be
    # anything else: an entry in a database, a specific time...
    if startorstop:
        with open(FLAGFILENAME, "w", encoding="utf8") as flag_file:
            flag_file.write("run")
    else:
        if os.path.isfile(FLAGFILENAME):
            os.unlink(FLAGFILENAME)


def is_flag_set():
    return os.path.isfile(FLAGFILENAME)


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
    """Starting the RegistrationServer

    * starts the actor system by importing registrationserver
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
    # TODO: system.createActor(MqttSchedulerActor, globalName="mqtt_scheduler")
    logger.debug("Actor system started.")
    usb_listener = UsbListener()
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
        daemon=True,
    )
    usb_listener_thread.start()
    return None


def main():
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
        return None
    else:
        print("Usage: <program> start|stop")
        return None

    while is_flag_set():
        pass
    try:
        cleanup()
    except UnboundLocalError:
        pass
    logger.debug("This is the end, my only friend, the end.")


if __name__ == "__main__":
    main()
