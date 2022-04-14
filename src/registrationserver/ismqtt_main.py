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
from datetime import datetime, timedelta

from thespian.actors import ActorSystem, Thespian_ActorStatus  # type: ignore
from thespian.system.messages.status import Thespian_StatusReq  # type: ignore

from registrationserver.actor_messages import AppType, KillMsg, SetupMsg
from registrationserver.config import actor_config
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger
from registrationserver.registrar import Registrar
from registrationserver.shutdown import (is_flag_set, kill_processes,
                                         set_file_flag)

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener


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
    app_type = AppType.ISMQTT
    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    system = ActorSystem(
        systemBase=actor_config["systemBase"],
        capabilities=actor_config["capabilities"],
        logDefs=logcfg,
    )
    registrar_actor = system.createActor(Registrar, globalName="registrar")
    system.tell(
        registrar_actor,
        SetupMsg("registrar", "actor_system", app_type),
    )
    logger.debug("Actor system started.")
    usb_listener = UsbListener(registrar_actor, app_type)
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
        daemon=True,
    )
    usb_listener_thread.start()
    return (registrar_actor, usb_listener)


def main():
    """This is the main function of the Instrument Server MQTT"""
    logger.debug("Entering main()")
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        set_file_flag(True)
        startup_tupel = startup()
        registrar_actor = startup_tupel[0]
        usb_listener = startup_tupel[1]
    elif start_stop == "stop":
        set_file_flag(False)
        return None
    else:
        print("Usage: <program> start|stop")
        return None

    logger.debug("Starting the main loop")
    wait_some_time = False
    while is_flag_set():
        before = datetime.now()
        try:
            reply = ActorSystem().ask(
                registrar_actor, Thespian_StatusReq(), timeout=timedelta(seconds=3)
            )
            if not isinstance(reply, Thespian_ActorStatus):
                set_file_flag(False)
        except OSError as exception:
            logger.critical("%s. Check Ethernet cable! Emergency shutdown.", exception)
            set_file_flag(False)
        time.sleep(4)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug("Wakeup from suspension.")
            wait_some_time = True
            set_file_flag(False)
    logger.debug("Terminate UsbListener")
    if usb_listener is not None:
        usb_listener.stop()
    if wait_some_time:
        logger.debug("Wait for 10 sec before shutting down ISMQTT.")
        time.sleep(10)
    logger.debug("Terminate the actor system")
    retry = True
    for _i in range(0, 5):
        while retry:
            try:
                response = ActorSystem().ask(
                    registrar_actor, KillMsg(), timeout=timedelta(seconds=10)
                )
                logger.debug("KillMsg to Registrar returned with %s", response)
                if response:
                    retry = False
                else:
                    time.sleep(3)
            except OSError as exception:
                logger.error(exception)
                time.sleep(3)
            break
    try:
        ActorSystem().shutdown()
    except OSError as exception:
        logger.critical(exception)
        if os.name == "posix":
            logger.info("Trying to kill residual processes. Fingers crossed!")
            exception = kill_processes("python.instrument_server_mqtt")
            if exception is not None:
                logger.critical(exception)
                logger.critical("There might be residual processes!")
                logger.info("Consider using 'ps ax' to investigate.")
    logger.info("This is the end, my only friend, the end.")
    raise SystemExit("Exit with error for automatic restart.")


if __name__ == "__main__":
    main()
