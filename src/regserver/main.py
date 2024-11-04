""" Main executable when running as Registration Server

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""

import os
import select
import shutil
import threading
from datetime import datetime, timedelta
from multiprocessing import Process
from time import sleep

from serial.serialutil import SerialException  # type: ignore
from thespian.actors import ActorSystem, Thespian_ActorStatus  # type: ignore
from thespian.system.messages.status import Thespian_StatusReq  # type: ignore

from regserver.actor_messages import Backend, Frontend, KillMsg, SetupMsg
from regserver.config import (FRMT, PING_FILE_NAME, actor_config,
                              backend_config, config, config_file,
                              frontend_config, mdns_backend_config,
                              rest_frontend_config)
from regserver.logdef import LOGFILENAME, logcfg
from regserver.logger import logger
from regserver.modules.backend.mdns.mdns_listener import MdnsListener
from regserver.modules.frontend.modbus.modbus_rtu import ModbusRtu
from regserver.registrar import Registrar
from regserver.restapi import run
from regserver.shutdown import (is_flag_set, kill_processes, set_file_flag,
                                system_shutdown)
from regserver.version import VERSION

if os.name == "posix":
    from gpiozero import LED  # type: ignore
    from gpiozero.exc import BadPinFactory  # type: ignore
    from systemd import journal

    from regserver.modules.backend.usb.unix_listener import UsbListener
else:
    from regserver.modules.backend.usb.win_listener import UsbListener

RETRY_DELAY = 2  # in seconds


class Main:
    """Main class to start and stop the RegServer"""

    def __init__(self):
        """Starting the RegServer

        * starts the actor system
        * starts the API thread
        * starts the MdnsListener
        * starts the Modbus RTU frontend
        """
        # =======================
        # Initialization of the actor system,
        # can be changed to a distributed system here.
        # =======================
        self.init_log_file()
        threading.excepthook = self.custom_hook
        # maybe there are processes left from last run
        self.kill_residual_processes(end_with_error=False)
        set_file_flag(True)
        self.led = None
        self.handle_aranea_led()
        try:
            system = ActorSystem(
                systemBase=actor_config["systemBase"],
                capabilities=actor_config["capabilities"],
                logDefs=logcfg,
            )
        except Exception as exception:  # pylint: disable=broad-except
            logger.warning(exception)
            logger.info("Retry to start Actor System after %d s.", RETRY_DELAY)
            sleep(RETRY_DELAY)
            try:
                system = ActorSystem(
                    systemBase=actor_config["systemBase"],
                    capabilities=actor_config["capabilities"],
                    logDefs=logcfg,
                )
            except RuntimeError as inner_exception:
                logger.warning(inner_exception)
                logger.info("Falling back to multiprocQueueBase Actor implementation")
                capabilities = {
                    "Process Startup Method": actor_config["capabilities"].get(
                        "Process Startup Method"
                    )
                }
                actor_config["systemBase"] = "multiprocQueueBase"
                try:
                    system = ActorSystem(
                        systemBase=actor_config["systemBase"],
                        capabilities=capabilities,
                        logDefs=logcfg,
                    )
                except Exception as second_exception:  # pylint: disable=broad-except
                    logger.critical(second_exception)
                    return
            except Exception as inner_exception:  # pylint: disable=broad-except
                logger.critical(inner_exception)
                return
        self.registrar_actor = system.createActor(Registrar, globalName="registrar")
        system.tell(
            self.registrar_actor,
            SetupMsg("registrar", "actor_system", None, None),
        )
        logger.debug("Actor system started.")
        # The Actor System must be started *before* the RestApi
        self.modbus_rtu = None
        usb_listener = None
        self.mdns_backend = None
        self.stop_event = threading.Event()
        if Frontend.REST in frontend_config:
            if os.name == "posix":
                self.api_process = Process(
                    target=run,
                    name="api_process",
                    args=(rest_frontend_config["API_PORT"],),
                )
            else:
                self.api_process = threading.Thread(
                    target=run,
                    name="api_thread",
                    args=(rest_frontend_config["API_PORT"],),
                    daemon=True,
                )
            self.api_process.start()
        if Frontend.MODBUS_RTU in frontend_config:
            try:
                self.modbus_rtu = ModbusRtu(self.registrar_actor)
                self.modbus_rtu.start()
            except SerialException as exception:
                logger.error("Modbus RTU not functional: %s", exception)
        if Backend.USB in backend_config:
            usb_listener = UsbListener(self.registrar_actor)
            self.usb_listener_thread = threading.Thread(
                target=usb_listener.run,
                name="usb_listener_thread",
                args=(self.stop_event,),
                daemon=True,
            )
            self.usb_listener_thread.start()
        if Backend.MDNS in backend_config:
            self.mdns_backend = MdnsListener(
                self.registrar_actor, service_type=mdns_backend_config["TYPE"]
            )
        logger.info("The RegServer is up and running now.")

    def handle_aranea_led(self):
        """Take care to switch the green LED, if there is one"""
        if os.name == "posix":
            try:
                self.led = LED(23)
            except BadPinFactory:
                self.led = False
            else:
                if Frontend.MQTT in frontend_config:
                    self.led.close()  # MQTT scheduler will take over
                else:
                    check_network_thread = threading.Thread(
                        target=self.check_network,
                        name="check_network_thread",
                        args=(self.stop_event,),
                    )
                    check_network_thread.start()
                    logger.info("Check_network thread started")
        else:
            self.led = False

    def shutdown(self, wait_some_time, registrar_is_down, with_error=True):
        # pylint: disable=too-many-branches
        """Shutdown application"""
        self.write_ping_file()
        self.stop_event.set()
        self.usb_listener_thread.join()
        if self.mdns_backend is not None:
            logger.info("Shutdown MdnsListener")
            try:
                self.mdns_backend.shutdown()
            except Exception as exception:  # pylint: disable=broad-except
                logger.critical(exception)
        if self.modbus_rtu is not None:
            logger.info("Terminate ModbusRtu")
            try:
                self.modbus_rtu.stop()
            except Exception as exception:  # pylint: disable=broad-except
                logger.critical(exception)
        if (self.api_process is not None) and (os.name == "posix"):
            logger.info("Terminate REST-API")
            try:
                self.api_process.kill()
            except Exception as exception:  # pylint: disable=broad-except
                logger.critical(exception)
        if wait_some_time:
            logger.debug("Wait for 10 sec before shutting down RegServer.")
            sleep(10)
        logger.info("Terminate the actor system")
        if registrar_is_down:
            logger.debug("Registrar actor already died from emergency shutdown")
        else:
            try:
                response = ActorSystem().ask(
                    self.registrar_actor, KillMsg(), timeout=timedelta(seconds=10)
                )
            except ConnectionResetError:
                response = None
            if response:
                logger.debug("Registrar actor terminated successfully")
            else:
                logger.error("KillMsg to Registrar returned with %s", response)
        try:
            ActorSystem().shutdown()
            sleep(3)
        except OSError as exception:
            logger.critical(exception)
        for thread in threading.enumerate():
            logger.debug("Thread still alive: %s", thread.name)
        self.kill_residual_processes(end_with_error=with_error)
        if with_error:
            raise SystemExit("Exit with error for automatic restart.")
        if self.led and not self.led.closed:
            self.led.close()
        logger.info("RegServer ended gracefully")

    def kill_residual_processes(self, end_with_error=True):
        """Kill RegServer processes. OS independent."""
        if end_with_error:
            logger.info("Trying to kill residual processes. Fingers crossed!")
        if os.name == "posix":
            process_regex = "sarad_registrat"
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
        for thread in threading.enumerate():
            logger.info("Thread still alive after killing: %s", thread.name)

    def outer_watchdog(self, number_of_trials=0) -> bool:
        """Checks the existance of the Registrar Actor.

        Args:
        registrar_address: Actor address of the Registrar
        number_of_trials: number of attempts to reach the Actor

        Returns:
        True if the Registrar is alive.
        """
        registrar_is_down = False
        attempts_left = number_of_trials
        while attempts_left:
            logger.debug("Run outer watchdog")
            registrar_is_down = False
            with ActorSystem().private() as registrar_status:
                try:
                    # logger.debug("Noch da John Maynard?")
                    reply = registrar_status.ask(
                        self.registrar_actor,
                        Thespian_StatusReq(),
                        timeout=timedelta(seconds=5),
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
                attempts_left = 0  # don't retry, stop it!
            else:
                if isinstance(reply, Thespian_ActorStatus):
                    # logger.debug("Aye Sir!")
                    attempts_left = 0
                    registrar_is_down = False
                else:
                    attempts_left = attempts_left - 1
                    logger.error(
                        "Registrar replied %s instead of Thespian_ActorStatus.",
                        reply,
                    )
                    logger.error(
                        "%d of %d attempts left.",
                        attempts_left,
                        number_of_trials,
                    )
                    sleep(0.5)
                    registrar_is_down = True
        return not registrar_is_down

    def custom_hook(self, args):
        """Custom exception hook to handle exceptions that occured within threads."""
        logger.critical("Thread %s failed with %s", args.thread, args.exc_value)
        logger.critical("Traceback: %s", args.exc_traceback)
        system_shutdown(with_error=True)

    def check_network(self, stop_event):
        """Check the Journal for new entries of NetworkManager."""
        if os.name == "posix":
            j = journal.Reader()
            j.add_match("_SYSTEMD_UNIT=NetworkManager.service")
            j.log_level(journal.LOG_INFO)
            j.seek_tail()
            j.get_previous()
            p = select.poll()  # pylint: disable=invalid-name
            p.register(j, j.get_events())
            while p.poll() and not stop_event.isSet():
                if j.process() != journal.APPEND:
                    sleep(0.5)
                    continue
                for entry in j:
                    if "CONNECTED_" in entry["MESSAGE"]:
                        self.led.on()
                    elif "DISCONNECTED" in entry["MESSAGE"]:
                        self.led.blink()

    def write_ping_file(self):
        """Write the current datetime into a file"""
        if (Backend.MQTT in backend_config) and (Frontend.MQTT not in frontend_config):
            with open(PING_FILE_NAME, "w", encoding="utf8") as pingfile:
                logger.debug("Write datetime to %s", PING_FILE_NAME)
                pingfile.write(datetime.utcnow().strftime(FRMT))

    def init_log_file(self):
        """Store the old log file and start a new one"""
        for i in sorted(range(1, config["NR_OF_LOG_FILES"]), reverse=True):
            if os.path.exists(f"{LOGFILENAME}.{i}"):
                shutil.copy2(f"{LOGFILENAME}.{i}", f"{LOGFILENAME}.{i + 1}")
        if os.path.exists(LOGFILENAME):
            shutil.copy2(LOGFILENAME, f"{LOGFILENAME}.1")
        try:
            with open(LOGFILENAME, "w", encoding="utf8") as _:
                logger.info("SARAD Registration Server %s", VERSION)
                logger.info("Configuration taken from %s", config_file)
                logger.info("Log entries go to %s", LOGFILENAME)
        except Exception:  # pylint: disable=broad-except
            logger.error("Initialization of log file failed.")

    def main(self):
        """Main function of the Registration Server"""
        logger.debug("Starting the main loop")
        wait_some_time = False
        interval = actor_config["OUTER_WATCHDOG_INTERVAL"]
        last_trial = datetime.now()
        registrar_is_down = False
        while is_flag_set()[0]:
            before = datetime.now()
            if (before - last_trial).total_seconds() > interval:
                registrar_is_down = not self.outer_watchdog(
                    number_of_trials=actor_config["OUTER_WATCHDOG_TRIALS"],
                )
                last_trial = before
                self.write_ping_file()
            else:
                registrar_is_down = False
            if registrar_is_down:
                logger.critical(
                    "No status response from Registrar Actor. -> Emergency shutdown."
                )
                system_shutdown()
            sleep(1)
            after = datetime.now()
            if (after - before).total_seconds() > 10:
                logger.info("Wakeup from suspension.")
                wait_some_time = True
                system_shutdown()
        self.shutdown(
            wait_some_time,
            registrar_is_down,
            with_error=is_flag_set()[1],
        )
