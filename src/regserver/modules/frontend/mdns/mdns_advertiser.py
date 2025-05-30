"""mDNS Advertiser -- actor to advertise instruments via mDNS (Zeroconf)

The mDNS Scheduler creates one Advertiser for every connected instrument.
The associated Redirector will be created by the Device Actor on Reservation.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

"""

import socket
from threading import Thread

from overrides import overrides  # type: ignore
from regserver.base_actor import BaseActor
from regserver.config import (config, get_hostname, get_ip,
                              lan_frontend_config, rest_frontend_config)
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.shutdown import system_shutdown
from zeroconf import ServiceInfo, Zeroconf
from zeroconf._exceptions import EventLoopBlocked, NonUniqueNameException


class MdnsAdvertiserActor(BaseActor):
    # pylint: disable=too-many-instance-attributes
    """Actor to advertise a listening server socket via mDNS"""

    @overrides
    def __init__(self):
        super().__init__()
        self.device_actor = None
        self.tcp_port = rest_frontend_config["API_PORT"]
        self.address = config["MY_IP"]
        self.service = None
        try:
            self.zeroconf = Zeroconf(
                ip_version=lan_frontend_config["IP_VERSION"],
                interfaces=[config["MY_IP"], "127.0.0.1"],
            )
        except OSError:
            self.zeroconf = None
            logger.error("No network -- %s", self.my_id)
        self.service_name = ""
        self.instr_name = ""
        self.device_id = ""
        self.occupied = False
        self.virgin = True

    def receiveMsg_SetupMdnsAdvertiserActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for the initialisation message from MdnsScheduler"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_actor = msg.device_actor
        self._subscribe_to_device_status_msg(self.device_actor)

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = short_id(msg.device_id)
        sarad_protocol = msg.device_id.split(".")[1]
        if msg.device_status.get("Identification", False):
            self.instr_name = msg.device_status["Identification"].get("Name", "")
        else:
            logger.error(
                "Something went wrong with the initialization of %s", msg.device_id
            )
            return
        self.service_name = f"{instr_id}.{sarad_protocol}"
        self.device_id = msg.device_id
        if msg.device_status.get("Reservation") is None:
            self.occupied = False
        else:
            self.occupied = msg.device_status["Reservation"].get("Active", False)
            if not self.virgin and self.zeroconf is not None:
                self.__update_service()
        if self.virgin and self.zeroconf is not None:
            try:
                self.__start_advertising()
            except NonUniqueNameException:
                logger.warning(
                    "%s is already availabel from another host in this LAN.",
                    msg.device_id,
                )
                self._kill_myself()

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.service is not None:
            try:
                self.zeroconf.unregister_service(self.service)
                self.zeroconf.close()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error(
                    "%s raised when trying to unregister Zeroconf service", exception
                )
        self._unsubscribe_from_device_status_msg(self.device_actor)
        super()._kill_myself(register=register, resurrect=resurrect)

    def __start_advertising(self):
        logger.debug("Start advertising %s", self.service_name)
        properties = {
            "VENDOR": "SARAD GmbH",
            "MODEL_ENC": self.instr_name,
            "SERIAL_SHORT": self.service_name,
            "DEVICE_ID": self.device_id,
            "OCCUPIED": self.occupied,
        }
        service_type = lan_frontend_config["TYPE"]
        self.service = ServiceInfo(
            service_type,
            f"{self.service_name}.{service_type}",
            port=self.tcp_port,
            weight=0,
            priority=0,
            properties=properties,
            server=get_hostname(get_ip(False)),
            addresses=[socket.inet_aton(self.address)],
        )
        register_thread = Thread(target=self.register_service, daemon=True)
        register_thread.start()

    def register_service(self):
        """Function for register_thread"""
        try:
            self.zeroconf.register_service(self.service)
        except (EventLoopBlocked, AssertionError) as exception:
            logger.critical("Exception in __start_advertising: %s", exception)
            system_shutdown()
        self.virgin = False
        self.__update_service()

    def __update_service(self):
        logger.debug(
            "Update service for %s: occupied = %s", self.device_id, self.occupied
        )
        if not self.virgin:
            properties = {
                "VENDOR": "SARAD GmbH",
                "MODEL_ENC": self.instr_name,
                "SERIAL_SHORT": self.service_name,
                "DEVICE_ID": self.device_id,
                "OCCUPIED": self.occupied,
            }
            service_type = lan_frontend_config["TYPE"]
            self.service = ServiceInfo(
                service_type,
                f"{self.service_name}.{service_type}",
                port=self.tcp_port,
                weight=0,
                priority=0,
                properties=properties,
                server=get_hostname(get_ip(False)),
                addresses=[socket.inet_aton(self.address)],
            )
            update_thread = Thread(target=self.update_service, daemon=True)
            update_thread.start()

    def update_service(self):
        """Function for update_thread"""
        try:
            self.zeroconf.update_service(self.service)
        except (EventLoopBlocked, AssertionError) as exception:
            logger.critical(
                "Exception in __update_service: %s, %s", exception, self.service
            )
