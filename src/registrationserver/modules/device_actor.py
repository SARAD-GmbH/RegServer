"""Main actor of the Registration Server

:Created:
    2020-10-13

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-device_actor.puml
"""
from datetime import datetime, timedelta

from overrides import overrides  # type: ignore
from registrationserver.actor_messages import AppType
from registrationserver.base_actor import BaseActor
from registrationserver.config import config, ismqtt_config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from registrationserver.modules.messages import RETURN_MESSAGES
from registrationserver.redirect_actor import RedirectorActor
from registrationserver.shutdown import system_shutdown
from thespian.actors import Actor, WakeupMessage

logger.debug("%s -> %s", __package__, __file__)


class DeviceBaseActor(BaseActor):
    """Base class for protocol specific device actors.

    Implements all methods that all device actors have in common.
    Handles the following actor messages:

    * SETUP: is used to initialize the actor right after its creation. This is
      needed because some parts of the initialization cannot be done in
      __init__() (because for instance self.globalName is not available yet in
      __init__()), other initialization steps require data from the
      MdnsListener/MqttSubscriber creating the device actor. The same method is
      used for updates of the device state comming from the
      MdnsListener/MqttSubscriber.

    * RESERVE: is being called when the end-user-application wants to
        reserve the directly or indirectly connected device for exclusive
        communication, should return if a reservation is currently possible

    * SEND: is being called when the end-user-application wants to send
        data, should return the direct or indirect response from the device,
        None in case the device is not reachable (so the end application can
        set the timeout itself)

    * FREE: is being called when the end-user-application is done requesting or
        sending data, should return True as soon the freeing process has been
        initialized
    """

    @overrides
    def __init__(self):
        logger.debug("Initialize a new device actor.")
        super().__init__()
        self.ACCEPTED_COMMANDS.update(
            {
                "SEND": "_on_send_cmd",
                "RESERVE": "_on_reserve_cmd",
                "FREE": "_on_free_cmd",
                "UPDATE": "_on_update_cmd",
                "READ": "_on_read_cmd",
            }
        )
        self.ACCEPTED_RETURNS.update(
            {
                "SETUP": "_on_setup_return",
                "KILL": "_on_kill_return",
            }
        )
        self._config: dict = {}
        self.device_status = {}
        self.my_redirector = None
        self.app = None
        self.user = None
        self.host = None
        self.sender_api = None
        self.mqtt_scheduler = None
        logger.info("Device actor created.")

    def receiveMsg_WakeupMessage(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage"""
        if msg.payload == "keep_alive":
            self.wakeupAfter(timedelta(minutes=10), payload="keep_alive")

    @overrides
    def _on_setup_cmd(self, msg, sender) -> None:
        logger.debug("[_on_setup_cmd]")
        super()._on_setup_cmd(msg, sender)
        self.wakeupAfter(timedelta(minutes=10), payload="keep_alive")
        self.device_status = msg["PAR"]
        self.my_id = msg["ID"]
        logger.debug("Device status: %s", self.device_status)
        self.registrar = self.createActor(Actor, globalName="registrar")
        if config["APP_TYPE"] == AppType.ISMQTT:
            self.mqtt_scheduler = self.createActor(Actor, globalName="mqtt_scheduler")
        self._mark_as_device_actor()
        return_message = {
            "RETURN": "SETUP",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "SELF": self.my_id,
        }
        self.send(sender, return_message)
        if self.mqtt_scheduler is not None:
            self.device_status["Identification"]["Host"] = ismqtt_config["IS_ID"]
            add_message = {
                "CMD": "ADD",
                "PAR": {
                    "INSTR_ID": short_id(self.my_id),
                    "DEVICE_STATUS": self.device_status,
                },
            }
            logger.debug(
                "Sending 'ADD' with %s to MQTT scheduler %s",
                add_message,
                self.mqtt_scheduler,
            )
            self.send(self.mqtt_scheduler, add_message)

    def _on_update_cmd(self, msg, _sender) -> None:
        # TODO: Can be replaced with a new SetupMsg
        logger.debug("[_on_update_cmd]")
        self.device_status = msg["PAR"]
        logger.debug("Device status: %s", self.device_status)
        if self.mqtt_scheduler is not None:
            add_message = {
                "CMD": "ADD",
                "PAR": {
                    "INSTR_ID": short_id(self.my_id),
                    "DEVICE_STATUS": self.device_status,
                },
            }
            logger.debug(
                "Sending 'ADD' with %s to MQTT scheduler %s",
                add_message,
                self.mqtt_scheduler,
            )
            self.send(self.mqtt_scheduler, add_message)

    @overrides
    def _on_kill_cmd(self, msg, sender):
        logger.info("%s for actor %s", msg, self.my_id)
        # Send 'REMOVE' message to MQTT Scheduler
        if config["APP_TYPE"] == AppType.ISMQTT:
            remove_message = {
                "CMD": "REMOVE",
                "PAR": {"INSTR_ID": short_id(self.my_id)},
            }
            logger.debug(
                "Sending 'REMOVE' with %s to MQTT scheduler %s",
                remove_message,
                self.mqtt_scheduler,
            )
            self.send(self.mqtt_scheduler, remove_message)
        if self.my_redirector is not None:
            self.send(self.my_redirector, {"CMD": "KILL"})
        self.send(self.registrar, {"CMD": "REMOVE", "PAR": {"GLOBAL_NAME": self.my_id}})
        return_message = {
            "RETURN": "KILL",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(sender, return_message)
        logger.debug("Cleanup done before finally killing me.")
        super()._on_kill_cmd(msg, sender)

    def _on_reserve_cmd(self, msg, sender) -> None:
        """Handler for RESERVE message from REST API."""
        logger.info("Device actor received a RESERVE command with message: %s", msg)
        self.sender_api = sender
        try:
            self.app = msg["PAR"]["APP"]
        except LookupError:
            logger.error("ERROR: there is no APP name!")
            return
        try:
            self.host = msg["PAR"]["HOST"]
        except LookupError:
            logger.error("ERROR: there is no HOST name!")
            return
        try:
            self.user = msg["PAR"]["USER"]
        except LookupError:
            logger.error("ERROR: there is no USER name!")
            return
        if config["APP_TYPE"] == AppType.RS:
            try:
                if self.device_status["Reservation"]["Active"]:
                    if self.device_status["Reservation"]["Host"] == self.host:
                        return_message = {
                            "RETURN": "RESERVE",
                            "ERROR_CODE": RETURN_MESSAGES["OK_UPDATED"]["ERROR_CODE"],
                        }
                    else:
                        return_message = {
                            "RETURN": "RESERVE",
                            "ERROR_CODE": RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"],
                        }
                    self.send(self.sender_api, return_message)
                    return
            except KeyError:
                logger.debug("First reservation since restart of RegServer")
            self._reserve_at_is()
        return

    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Request the reservation of an instrument at the Instrument Server. This function has
        to be implemented (overridden) in the protocol specific modules.

        Args:
            self.app: String identifying the requesting app.
            self.host: String identifying the host running the app.
            self.user: String identifying the user of the app.
            self.sender_api: The actor object asking for reservation.
        """

    def _forward_reservation(self, success: bool):
        # pylint: disable=unused-argument, no-self-use
        """Forward the reply from the Instrument Server to the redirector actor.
        This function has to be called in the protocol specific modules.
        """
        if success:
            if self._create_redirector():
                return
            return_message = {
                "RETURN": "RESERVE",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            }
            self.send(self.sender_api, return_message)
            return
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OCCUPIED"]["ERROR_CODE"],
        }
        self.send(self.sender_api, return_message)
        return

    def _create_redirector(self) -> bool:
        """Create redirector actor"""
        if self.my_redirector is None:
            logger.debug("Trying to create a redirector actor")
            self.my_redirector = self.createActor(RedirectorActor)
            msg = {"CMD": "SETUP", "PAR": {"PARENT_NAME": self.my_id}}
            logger.debug("Send SETUP command to redirector with msg %s", msg)
            self.send(self.my_redirector, msg)
            return True
        logger.debug(
            "[create_redirector] Redirector %s already exists.", self.my_redirector
        )
        return False

    def _on_setup_return(self, msg, sender):
        logger.debug("returned with %s", msg)
        try:
            assert msg["ERROR_CODE"] in (
                RETURN_MESSAGES["OK"]["ERROR_CODE"],
                RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            )
        except AssertionError:
            return_message = {
                "RETURN": "RESERVE",
                "ERROR_CODE": RETURN_MESSAGES["UNKNOWN_PORT"]["ERROR_CODE"],
            }
            self.send(self.sender_api, return_message)
            return
        # Write Reservation section into device status
        ip_address = msg["RESULT"]["IP"]
        port = msg["RESULT"]["PORT"]
        reservation = {
            "Active": True,
            "App": self.app,
            "Host": self.host,
            "User": self.user,
            "IP": ip_address,
            "Port": port,
            "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        self.device_status["Reservation"] = reservation
        logger.debug("Reservation state updated: %s", self.device_status)
        self.send(self.my_redirector, {"CMD": "CONNECT"})
        return_message = {
            "RETURN": "RESERVE",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
        }
        self.send(self.sender_api, return_message)
        return

    def _on_free_cmd(self, msg, sender):
        """Handler for FREE message from REST API."""
        logger.info("Device actor received a FREE command. %s", msg)
        self.sender_api = sender
        try:
            if self.device_status["Reservation"]["Active"]:
                self.device_status["Reservation"]["Active"] = False
                self.device_status["Reservation"].pop("IP")
                self.device_status["Reservation"].pop("Port")
                self.device_status["Reservation"]["Timestamp"] = (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z"
                )
                return_message = {
                    "RETURN": "FREE",
                    "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                }
            else:
                return_message = {
                    "RETURN": "FREE",
                    "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
                }
        except KeyError:
            logger.debug("Instr. was not reserved before.")
            return_message = {
                "RETURN": "FREE",
                "ERROR_CODE": RETURN_MESSAGES["OK_SKIPPED"]["ERROR_CODE"],
            }
        self.send(self.sender_api, return_message)
        if self.my_redirector is not None:
            logger.debug("Send KILL to redirector %s", self.my_redirector)
            kill_cmd = {"CMD": "KILL"}
            self.send(self.my_redirector, kill_cmd)
            return

    def _on_kill_return(self, msg, sender):
        """Completes the _on_free_cmd function with the reply from the redirector actor after
        it received the KILL command."""
        if not msg["ERROR_CODE"]:
            reservation = {
                "Active": False,
                "App": self.device_status["Reservation"]["App"],
                "Host": self.device_status["Reservation"]["Host"],
                "User": self.device_status["Reservation"]["User"],
                "Timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            logger.info("[Free] %s", reservation)
            self.device_status["Reservation"] = reservation
            self.my_redirector = None
            return
        logger.critical("Killing the redirector actor failed with %s", msg)
        system_shutdown()
        return

    def _on_read_cmd(self, msg, sender):
        """Handler for READ command.

        Sends back a message containing the device_status."""
        result = {
            "RETURN": "READ",
            "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
            "RESULT": self.device_status,
        }
        self.send(sender, result)
