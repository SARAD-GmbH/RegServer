""" Main executable

Created
    2020-09-30

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml:: uml-main.puml
"""

import atexit
import os
import signal
import threading

from thespian.actors import ActorSystem, ActorExitRequest  # type: ignore

import registrationserver2.logdef
from registrationserver2 import FOLDER_AVAILABLE, logger
from registrationserver2.config import config
from registrationserver2.modules.rfc2217.mdns_listener import MdnsListener
from registrationserver2.restapi import RestApi
from registrationserver2.modules.mqtt.mqtt_subscriber import SaradMqttSubscriber
from registrationserver2.modules.mqtt.message import RETURN_MESSAGES


def main():
    """Starting the RegistrationServer2

    * starts the actor system by importing registrationserver2
    * starts the API thread
    * starts the MdnsListener
    """
    # Prepare for closing
    @atexit.register
    def cleanup():  # pylint: disable=unused-variable
        """Make sure all sub threads are stopped, including the REST API"""
        logger.info("Cleaning up before closing.")
        ActorSystem().shutdown()
        logger.debug("Actor system shut down finished.")
        if os.path.exists(FOLDER_AVAILABLE):
            for root, _, files in os.walk(FOLDER_AVAILABLE):
                for name in files:
                    link = os.path.join(root, name)
                    logger.debug("[Del]:\tRemoved: %s", name)
                    os.unlink(link)
        os.kill(os.getpid(), signal.SIGTERM)

    # =======================
    # Initialization of the actor system,
    # can be changed to a distributed system here.
    # =======================
    ActorSystem(
        systemBase=config["systemBase"],
        capabilities=config["capabilities"],
        logDefs=registrationserver2.logdef.logcfg,
    )
    logger.debug("Actor system started.")
    restapi = RestApi()
    apithread = threading.Thread(
        target=restapi.run,
        args=(
            "0.0.0.0",
            8000,
        ),
    )
    apithread.start()
    _ = MdnsListener(_type=config["TYPE"])
    _subscriber = SaradMqttSubscriber()
    """sarad_mqtt_subscriber = ActorSystem().createActor(SaradMqttSubscriber)
    ask_return = ActorSystem().ask(
        sarad_mqtt_subscriber,
        {
            "CMD": "SETUP",
            "PAR": {
                "client_id": "sarad-mqtt_subscriber-client",
                "mqtt_broker": "127.0.0.1",
                "port": 1883,
            },
        },
    )
    if ask_return is None:
        logger.error("[test_actor/setup]: No reply from the subscriber")
    elif ask_return["ERROR_CODE"] in (
        RETURN_MESSAGES["OK"]["ERROR_CODE"],
        RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
    ):
        logger.info("SARAD MQTT Subscriber is setup correctly!")
    else:
        logger.warning("SARAD MQTT Subscriber is not setup! Kill it.")
        logger.error(ask_return)
        ActorSystem().tell(sarad_mqtt_subscriber, ActorExitRequest())"""
    
    try:
        logger.info("Press ENTER to end!")
        input("Press ENTER to end\n")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
