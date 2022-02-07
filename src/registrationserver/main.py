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
from datetime import datetime

from thespian.actors import ActorSystem  # type: ignore

from registrationserver.actor_messages import AppType, KillMsg
from registrationserver.config import config
from registrationserver.logdef import LOGFILENAME
from registrationserver.logger import logger
from registrationserver.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver.restapi import REGISTRAR_ACTOR, RestApi
from registrationserver.shutdown import is_flag_set, set_file_flag

if os.name == "nt":
    from registrationserver.modules.usb.win_listener import UsbListener
else:
    from registrationserver.modules.usb.unix_listener import UsbListener


def mqtt_loop(mqtt_listener):
    """Loop function of the MQTT Listener"""
    if mqtt_listener is not None:
        mqtt_listener.mqtt_loop()


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
    usb_listener = UsbListener(REGISTRAR_ACTOR, AppType.RS)
    usb_listener_thread = threading.Thread(
        target=usb_listener.run,
        daemon=True,
    )
    usb_listener_thread.start()

    return MdnsListener(REGISTRAR_ACTOR, service_type=config["TYPE"])


def main():
    """Main function of the Registration Server"""
    logger.debug("Entering main()")
    if len(sys.argv) < 2:
        start_stop = "start"
    else:
        start_stop = sys.argv[1]
    if start_stop == "start":
        mdns_listener = startup()
        set_file_flag(True)
    elif start_stop == "stop":
        set_file_flag(False)
        return None
    else:
        print("Usage: <program> start|stop")
        return None

    logger.debug("Starting the main loop")
    while is_flag_set():
        before = datetime.now()
        time.sleep(4)
        after = datetime.now()
        if (after - before).total_seconds() > 10:
            logger.debug(
                "Wakeup from suspension. Shutting down RegServer for a fresh restart."
            )
            set_file_flag(False)
    logger.debug("Shutdown MdnsListener")
    if mdns_listener is not None:
        mdns_listener.shutdown()
    logger.debug("Terminate the actor system")
    retry = True
    for _i in range(0, 5):
        while retry:
            try:
                response = ActorSystem().ask(REGISTRAR_ACTOR, KillMsg(), 10)
                retry = False
                logger.debug("KillMsg to Registrar returned with %s", response)
            except OSError as exception:
                logger.error(exception)
                time.sleep(3)
            break
    ActorSystem().shutdown()
    logger.info("Actor system shut down finished.")
    logger.debug("This is the end, my only friend, the end.")
    raise SystemExit("Exit with error for automatic restart.")


if __name__ == "__main__":
    main()
