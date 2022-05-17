"""mDNS Advertiser -- actor to advertise instruments via mDNS (Zeroconf)

The mDNS Scheduler creates one pair of Advertiser/Redirector for every
connected instrument.

:Created:
    2022-05-06

:Authors:
    | Michael Strey <strey@sarad.de>

Based on work of Riccardo Förster <foerster@sarad.de>.

"""

import socket

from registrationserver.actor_messages import GetDeviceStatusMsg
from registrationserver.base_actor import BaseActor
from registrationserver.config import config
from registrationserver.helpers import short_id
from registrationserver.logger import logger
from zeroconf import ServiceInfo, Zeroconf


class MdnsAdvertiserActor(BaseActor):
    """Actor to advertise a listening server socket via mDNS"""

    def __init__(self):
        super().__init__()
        self.device_actor = None
        self.tcp_port = None
        self.address = config["MY_IP"]
        self.service = None
        self.zeroconf = Zeroconf()

    def receiveMsg_SetupMdnsAdvertiserActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for the initialisation message from MdnsRedirectorActor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        self.device_actor = msg.device_actor
        self.tcp_port = msg.tcp_port
        self.send(self.device_actor, GetDeviceStatusMsg())

    def receiveMsg_UpdateDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for UpdateDeviceStatusMsg from Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        instr_id = short_id(msg.device_id)
        sarad_protocol = msg.device_id.split(".")[1]
        instr_name = msg.device_status["Identification"]["Name"]
        service_name = f"{instr_id}.{sarad_protocol}"
        self.__start_advertising(service_name, instr_name)

    def receiveMsg_KillMsg(self, msg, sender):
        try:
            self.zeroconf.unregister_service(self.service)
            self.zeroconf.close()
        except Exception as exception:  # pylint: disable=broad-except
            logger.error(
                "%s raised when trying to unregister Zeroconf service", exception
            )
        super().receiveMsg_KillMsg(msg, sender)

    def __start_advertising(self, service_name, instr_name):
        properties = {
            "VENDOR": "SARAD GmbH",
            "MODEL_ENC": instr_name,
            "SERIAL_SHORT": service_name,
            "API_PORT": config["API_PORT"],
        }
        self.service = ServiceInfo(
            "_raw._tcp.local.",
            f"{service_name}._raw._tcp.local.",
            port=self.tcp_port,
            weight=0,
            priority=0,
            properties=properties,
            server=f"{socket.gethostname()}.local.",
            addresses=[socket.inet_aton(self.address)],
        )
        self.zeroconf.register_service(self.service)
