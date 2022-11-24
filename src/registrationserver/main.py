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

from serial.serialutil import SerialException  # type: ignore
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
from registrationserver.modules.frontend.modbus.modbus_rtu import ModbusRtu
from registrationserver.registrar import Registrar
from registrationserver.restapi import RestApi
from registrationserver.shutdown import (is_flag_set, kill_processes,
                                         set_file_flag, system_shutdown)

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
    * starts the Modbus RTU frontend

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
        SetupMsg("registrar", "actor_system", None, None),
    )
    logger.debug("Actor system started.")
    # The Actor System must be started *before* the RestApi
    modbus_rtu = None
    usb_listener = None
    mdns_backend = None
    if Frontend.REST in frontend_config:
        restapi = RestApi()
        api_thread = threading.Thread(
            target=restapi.run,
            args=(rest_frontend_config["API_PORT"],),
            daemon=True,
        )
        api_thread.start()
    if Frontend.MODBUS_RTU in frontend_config:
        try:
            modbus_rtu = ModbusRtu(registrar_actor)
            modbus_rtu.start()
        except SerialException as exception:
            logger.error("Modbus RTU not functional: %s", exception)
    if Backend.USB in backend_config:
        usb_listener = UsbListener(registrar_actor)
        usb_listener_thread = threading.Thread(
            target=usb_listener.run,
            daemon=True,
        )
        usb_listener_thread.start()
    if Backend.MDNS in backend_config:
        mdns_backend = MdnsListener(
            registrar_actor, service_type=mdns_backend_config["TYPE"]
        )
    return (registrar_actor, mdns_backend, usb_listener, modbus_rtu)


def shutdown(startup_tupel, wait_some_time, registrar_is_down, with_error=True):
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
    modbus_rtu = startup_tupel[3]
    if modbus_rtu is not None:
        logger.debug("Terminate ModbusRtu")
        try:
            modbus_rtu.stop()
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
    kill_residual_processes(end_with_error=with_error)


def kill_residual_processes(end_with_error=True):
    """Kill RegServer processes. OS independent."""
    if end_with_error:
        logger.info("Trying to kill residual processes. Fingers crossed!")
    else:
        logger.info("RegServer ended gracefully")
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
        logger.debug("Run outer watchdog")
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
            kill_residual_processes(end_with_error=True)
            return None
    elif start_stop == "stop":
        system_shutdown(with_error=False)
        return None
    else:
        print("Usage: <program> start|stop")
        return None
    logger.debug("Starting the main loop")
    wait_some_time = False
    interval = actor_config["OUTER_WATCHDOG_INTERVAl"]
    last_trial = datetime.now()
    registrar_is_down = False
    while is_flag_set()[0]:
        before = datetime.now()
        if (before - last_trial).total_seconds() > interval:
            registrar_is_down = not outer_watchdog(
                startup_tupel[0], number_of_trials=actor_config["OUTER_WATCHDOG_TRIALS"]
            )
            last_trial = before
        else:
            registrar_is_down = False
        if registrar_is_down:
            logger.critical(
                "No status response from Registrar Actor. -> Emergency shutdown."
            )
            system_shutdown()
        time.sleep(1)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.info("Wakeup from suspension.")
            wait_some_time = True
            system_shutdown()
    shutdown(
        startup_tupel, wait_some_time, registrar_is_down, with_error=is_flag_set()[1]
    )


if __name__ == "__main__":
    main()
