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

from registrationserver.actor_messages import (Backend, Frontend, KillMsg,
                                               SetupMsg)
from registrationserver.config import (actor_config, backend_config,
                                       frontend_config, mdns_backend_config,
                                       rest_frontend_config)
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

RETRY_DELAY = 2  # in seconds


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
            logger.info("Log entries go to %s", LOGFILENAME)
    except Exception:  # pylint: disable=broad-except
        logger.error("Initialization of log file failed.")
    logger.info("Logging system initialized.")
    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    try:
        system = ActorSystem(
            systemBase=actor_config["systemBase"],
            capabilities=actor_config["capabilities"],
            logDefs=logcfg,
        )
    except Exception as exception:  # pylint: disable=broad-except
        logger.warning(exception)
        logger.info("Retry to start Actor System after %d s.", RETRY_DELAY)
        time.sleep(RETRY_DELAY)
        try:
            system = ActorSystem(
                systemBase=actor_config["systemBase"],
                capabilities=actor_config["capabilities"],
                logDefs=logcfg,
            )
        except Exception as inner_exception:  # pylint: disable=broad-except
            logger.critical(inner_exception)
            return ()
    registrar_actor = system.createActor(Registrar, globalName="registrar")
    system.tell(
        registrar_actor,
        SetupMsg("registrar", "actor_system", None),
    )
    logger.debug("Actor system started.")
    # The Actor System must be started *before* the RestApi
    if Frontend.REST in frontend_config:
        restapi = RestApi()
        api_thread = threading.Thread(
            target=restapi.run,
            args=(rest_frontend_config["API_PORT"],),
            daemon=True,
        )
        api_thread.start()
    if Backend.USB in backend_config:
        usb_listener = UsbListener(registrar_actor)
        usb_listener_thread = threading.Thread(
            target=usb_listener.run,
            daemon=True,
        )
        usb_listener_thread.start()
    else:
        usb_listener = None
    if Backend.MDNS in backend_config:
        mdns_backend = MdnsListener(
            registrar_actor, service_type=mdns_backend_config["TYPE"]
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
        try:
            response = ActorSystem().ask(
                registrar_actor, KillMsg(), timeout=timedelta(seconds=10)
            )
        except ConnectionResetError:
            response = None
        if response:
            logger.debug("Registrar actor terminated successfully")
        else:
            logger.error("KillMsg to Registrar returned with %s", response)
    try:
        ActorSystem().shutdown()
    except OSError as exception:
        logger.critical(exception)
    kill_residual_processes()


def kill_residual_processes(end_with_error=True):
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
    if end_with_error:
        raise SystemExit("Exit with error for automatic restart.")


def outer_watchdog(registrar_address, number_of_trials=0) -> bool:
    """Checks the existance of the Registrar Actor.

    Args:
       registrar_address: Actor address of the Registrar
       number_of_trials: number of attempts to reach the Actor

    Returns:
       True if the Registrar is alive.
    """
    registrar_is_down = False
    while number_of_trials:
        registrar_is_down = False
        with ActorSystem().private() as registrar_status:
            try:
                # logger.debug("Noch da John Maynard?")
                reply = registrar_status.ask(
                    registrar_address,
                    Thespian_StatusReq(),
                    timeout=timedelta(seconds=1),
                )
            except OSError as exception:
                logger.critical("We are offline. OSError: %s.", exception)
                registrar_is_down = True
            except RuntimeError as exception:
                logger.critical("RuntimeError: %s.", exception)
                registrar_is_down = True
            except Exception as exception:  # pylint: disable=broad-except
                logger.critical("Exception: %s.", exception)
                registrar_is_down = True
        if registrar_is_down:
            number_of_trials = 0  # don't retry, stop it!
        else:
            if isinstance(reply, Thespian_ActorStatus):
                # logger.debug("Aye Sir!")
                number_of_trials = 0
                registrar_is_down = False
            else:
                logger.error(
                    "Registrar replied %s instead of Thespian_ActorStatus. Retrying %d",
                    reply,
                    number_of_trials,
                )
                time.sleep(0.5)
                number_of_trials = number_of_trials - 1
                registrar_is_down = True
    return not registrar_is_down


def main():
    """Main function of the Registration Server"""
    logger.debug("Entering main()")
    kill_residual_processes(
        end_with_error=False
    )  # maybe there are processes left from last run
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        set_file_flag(True)
        startup_tupel = startup()
        if not startup_tupel:
            time.sleep(30)
            kill_residual_processes()
            return None
    elif start_stop == "stop":
        set_file_flag(False)
    else:
        print("Usage: <program> start|stop")
        return None
    logger.debug("Starting the main loop")
    wait_some_time = False
    while is_flag_set():
        before = datetime.now()
        registrar_is_down = not outer_watchdog(startup_tupel[0], number_of_trials=0)
        if registrar_is_down:
            logger.critical(
                "No status response from Registrar Actor. -> Emergency shutdown."
            )
            set_file_flag(False)
        time.sleep(1)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug("Wakeup from suspension.")
            wait_some_time = True
            set_file_flag(False)
    shutdown(startup_tupel, wait_some_time, registrar_is_down)


if __name__ == "__main__":
    main()
