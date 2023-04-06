"""mDNS Advertiser -- actor to advertise instruments via mDNS (Zeroconf)

The mDNS Scheduler creates one Advertiser for every connected instrument.
The associated Redirector will be created by the Device Actor on Reservation.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

Based on work of Riccardo Förster <foerster@sarad.de>.

"""
import socket

from registrationserver.actor_messages import KillMsg
from registrationserver.base_actor import BaseActor
from registrationserver.config import (config, mdns_frontend_config,
                                       rest_frontend_config)
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from zeroconf import ServiceInfo, Zeroconf
from zeroconf._exceptions import NonUniqueNameException


class MdnsAdvertiserActor(BaseActor):
    # pylint: disable=too-many-instance-attributes
    """Actor to advertise a listening server socket via mDNS"""

    def __init__(self):
        super().__init__()
        self.device_actor = None
        self.tcp_port = rest_frontend_config["API_PORT"]
        self.address = config["MY_IP"]
        self.service = None
        self.zeroconf = Zeroconf(
            ip_version=mdns_frontend_config["IP_VERSION"],
            interfaces=[config["MY_IP"], "127.0.0.1"],
        )
        self.service_name = None
        self.instr_name = None
        self.device_id = None
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
        self.instr_name = msg.device_status["Identification"]["Name"]
        self.service_name = f"{instr_id}.{sarad_protocol}"
        self.device_id = msg.device_id
        if msg.device_status.get("Reservation") is None:
            self.occupied = False
        else:
            self.occupied = msg.device_status["Reservation"].get("Active", False)
            if self.occupied and (not self.virgin):
                self.__update_service()
        if self.virgin:
            try:
                self.__start_advertising()
            except NonUniqueNameException:
                logger.warning(
                    "%s is already availabel from another host in this LAN.",
                    msg.device_id,
                )
                self.send(self.myAddress, KillMsg())

    def receiveMsg_KillMsg(self, msg, sender):
        if self.service is not None:
            try:
                self.zeroconf.unregister_service(self.service)
                self.zeroconf.close()
            except Exception as exception:  # pylint: disable=broad-except
                logger.error(
                    "%s raised when trying to unregister Zeroconf service", exception
                )
        self._unsubscribe_from_device_status_msg(self.device_actor)
        super().receiveMsg_KillMsg(msg, sender)

    def __start_advertising(self):
        logger.info("Start advertising %s", self.service_name)
        properties = {
            "VENDOR": "SARAD GmbH",
            "MODEL_ENC": self.instr_name,
            "SERIAL_SHORT": self.service_name,
            "DEVICE_ID": self.device_id,
            "OCCUPIED": self.occupied,
        }
        service_type = mdns_frontend_config["TYPE"]
        self.service = ServiceInfo(
            service_type,
            f"{self.service_name}.{service_type}",
            port=self.tcp_port,
            weight=0,
            priority=0,
            properties=properties,
            addresses=[socket.inet_aton(self.address)],
        )
        self.zeroconf.register_service(self.service)
        self.virgin = False
        self.__update_service()

    def __update_service(self):
        logger.info("Update %s: occupied = %s", self.service.name, self.occupied)
        properties = {
            "VENDOR": "SARAD GmbH",
            "MODEL_ENC": self.instr_name,
            "SERIAL_SHORT": self.service_name,
            "DEVICE_ID": self.device_id,
            "OCCUPIED": self.occupied,
        }
        service_type = mdns_frontend_config["TYPE"]
        self.service = ServiceInfo(
            service_type,
            f"{self.service_name}.{service_type}",
            port=self.tcp_port,
            weight=0,
            priority=0,
            properties=properties,
            addresses=[socket.inet_aton(self.address)],
        )
        self.zeroconf.update_service(self.service)
