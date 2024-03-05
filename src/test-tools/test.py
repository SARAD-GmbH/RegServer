"""Listening for mDNS multicast messages announcing the existence of new
services (SARAD devices) in the local network.

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

"""
import threading

from registrationserver import mdns_backend_config
from registrationserver.helpers import get_ip
from registrationserver.logger import logger
from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf

logger.debug("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    def __init__(self, _type):
        """
        Initialize a mdns Listener for a specific device group
        """
        self.__type: str = type
        self.__lock = threading.Lock()
        self.__zeroconf = Zeroconf(
            ip_version=IPVersion.All, interfaces=[get_ip(ipv6=False), "127.0.0.1"]
        )
        self.__browser = ServiceBrowser(self.__zeroconf, _type, self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a new service
        representing a device is being detected"""
        logger.info("[Add] Found service %s of type %s", name, type_)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=C0103
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        logger.info("[Del] Service %s of type %s", name, type_)


if __name__ == "__main__":
    listener = MdnsListener(_type=mdns_backend_config["TYPE"])
