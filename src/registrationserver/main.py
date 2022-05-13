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
import time
from datetime import datetime, timedelta

from thespian.actors import ActorSystem, Thespian_ActorStatus  # type: ignore
from thespian.system.messages.status import Thespian_StatusReq  # type: ignore

import registrationserver.config as configuration
from registrationserver.actor_messages import (Backend, Frontend, KillMsg,
                                               SetupMsg)
from registrationserver.logdef import LOGFILENAME, logcfg
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.mdns_listener import MdnsListener
from registrationserver.registrar import Registrar
from registrationserver.restapi import RestApi
from registrationserver.shutdown import (is_flag_set, kill_processes,
                                         set_file_flag)

if os.name == "nt":
    from registrationserver.modules.backend.usb.win_listener import UsbListener
else:
    from registrationserver.modules.backend.usb.unix_listener import \
        UsbListener


def startup():
    """Starting the RegistrationServer

    * starts the actor system by importing registrationserver
    * starts the API thread
    * starts the MdnsListener

    Returns:
        Tuple of Registrar Actor, MdnsListener, and UsbListener
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
    try:
        system = ActorSystem(
            systemBase=configuration.actor_config["systemBase"],
            capabilities=configuration.actor_config["capabilities"],
            logDefs=logcfg,
        )
    except Exception as exception:  # pylint: disable=broad-except
        logger.critical(exception)
        kill_residual_processes()
        return ()
    registrar_actor = system.createActor(Registrar, globalName="registrar")
    system.tell(
        registrar_actor,
        SetupMsg("registrar", "actor_system"),
    )
    logger.debug("Actor system started.")
    # The Actor System must be started *before* the RestApi
    if Frontend.REST in configuration.frontend_config:
        restapi = RestApi()
        apithread = threading.Thread(
            target=restapi.run,
            args=(
                configuration.config["HOST"],
                configuration.config["API_PORT"],
            ),
            daemon=True,
        )
        apithread.start()
    if Backend.USB in configuration.backend_config:
        usb_listener = UsbListener(registrar_actor)
        usb_listener_thread = threading.Thread(
            target=usb_listener.run,
            daemon=True,
        )
        usb_listener_thread.start()
    else:
        usb_listener = None
    if Backend.MDNS in configuration.backend_config:
        mdns_backend = MdnsListener(
            registrar_actor, service_type=configuration.config["TYPE"]
        )
    else:
        mdns_backend = None
    return (registrar_actor, mdns_backend, usb_listener)


def shutdown(startup_tupel, wait_some_time, registrar_is_down):
    # pylint: disable=too-many-branches
    """Shutdown application"""
    mdns_listener = startup_tupel[1]
    if mdns_listener is not None:
        logger.debug("Shutdown MdnsListener")
        try:
            mdns_listener.shutdown()
        except Exception as exception:  # pylint: disable=broad-except
            logger.critical(exception)
    usb_listener = startup_tupel[2]
    if usb_listener is not None:
        logger.debug("Terminate UsbListener")
        try:
            usb_listener.stop()
        except Exception as exception:  # pylint: disable=broad-except
            logger.critical(exception)
    if wait_some_time:
        logger.debug("Wait for 10 sec before shutting down RegServer.")
        time.sleep(10)
    logger.debug("Terminate the actor system")
    if registrar_is_down:
        logger.debug("Registrar actor already died from emergency shutdown")
    else:
        registrar_actor = startup_tupel[0]
        response = ActorSystem().ask(
            registrar_actor, KillMsg(), timeout=timedelta(seconds=10)
        )
        logger.error("KillMsg to Registrar returned with %s", response)
    try:
        ActorSystem().shutdown()
    except OSError as exception:
        logger.critical(exception)
        kill_residual_processes()


def kill_residual_processes():
    """Kill RegServer processes. OS independent."""
    logger.info("Trying to kill residual processes. Fingers crossed!")
    if os.name == "posix":
        process_regex = "python.sarad_registration_server"
    elif os.name == "nt":
        process_regex = "regserver-service.exe"
    else:
        process_regex = ""
    exception = kill_processes(process_regex)
    if exception is not None:
        logger.critical(exception)
        logger.critical("There might be residual processes.")
    if os.name == "posix":
        logger.info("Consider using 'ps ax' to investigate!")
    if os.name == "nt":
        logger.info("Inspect Task Manager to investigate!")


def main():
    """Main function of the Registration Server"""
    logger.debug("Entering main()")
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        set_file_flag(True)
        startup_tupel = startup()
    elif start_stop == "stop":
        set_file_flag(False)
        raise SystemExit("Exit with error for automatic restart.")
    else:
        print("Usage: <program> start|stop")
        return None

    logger.debug("Starting the main loop")
    wait_some_time = False
    registrar_is_down = False
    retry_counter = 3
    while is_flag_set() and retry_counter:
        before = datetime.now()
        with ActorSystem().private() as registrar_status:
            reply = registrar_status.ask(
                startup_tupel[0], Thespian_StatusReq(), timeout=timedelta(seconds=3)
            )
        if not isinstance(reply, Thespian_ActorStatus):
            logger.error("Registrar replied %s instead of Thespian_ActorStatus")
            retry_conter = retry_conter - 1
            if not retry_counter:
                set_file_flag(False)
                registrar_is_down = True
                logger.critical(
                    "No status response from Registrar Actor. Emergency shutdown."
                )
        time.sleep(1)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug("Wakeup from suspension.")
            wait_some_time = True
            set_file_flag(False)
    shutdown(startup_tupel, wait_some_time, registrar_is_down)
    logger.info("This is the end, my only friend, the end.")
    raise SystemExit("Exit with error for automatic restart.")


if __name__ == "__main__":
    main()
