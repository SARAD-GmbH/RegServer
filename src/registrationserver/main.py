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
from registrationserver.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver.registrar import Registrar
from registrationserver.restapi import RestApi
from registrationserver.shutdown import (is_flag_set, kill_processes,
                                         set_file_flag)

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener


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
        kill_processes("python.sarad_registration_server")
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
        try:
            registrar_actor = startup_tupel[0]
            mdns_listener = startup_tupel[1]
            usb_listener = startup_tupel[2]
        except IndexError as exception:
            raise SystemExit("Exit with error for automatic restart.") from exception
    elif start_stop == "stop":
        set_file_flag(False)
        raise SystemExit("Exit with error for automatic restart.")
    else:
        print("Usage: <program> start|stop")
        return None

    logger.debug("Starting the main loop")
    wait_some_time = False
    while is_flag_set():
        before = datetime.now()
        reply = ActorSystem().ask(
            registrar_actor, Thespian_StatusReq(), timeout=timedelta(seconds=3)
        )
        if not isinstance(reply, Thespian_ActorStatus):
            set_file_flag(False)
        time.sleep(4)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug("Wakeup from suspension.")
            wait_some_time = True
            set_file_flag(False)

    logger.debug("Shutdown MdnsListener")
    if mdns_listener is not None:
        logger.debug(mdns_listener)
        try:
            mdns_listener.shutdown()
        except Exception as exception:  # pylint: disable=broad-except
            logger.critical(exception)
    logger.debug("Terminate UsbListener")
    if usb_listener is not None:
        try:
            usb_listener.stop()
        except Exception as exception:  # pylint: disable=broad-except
            logger.critical(exception)
    if wait_some_time:
        logger.debug("Wait for 10 sec before shutting down RegServer.")
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
            exception = kill_processes("python.sarad_registration_server")
            if exception is not None:
                logger.critical(exception)
                logger.critical("There might be residual processes!")
                logger.info("Consider using 'ps ax' to investigate.")
    logger.info("This is the end, my only friend, the end.")
    raise SystemExit("Exit with error for automatic restart.")


if __name__ == "__main__":
    main()
