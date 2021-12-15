"""Listening for mDNS multicast messages announcing the existence of new
services (SARAD devices) in the local network.

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-mdns_listener.puml

"""
import socket
import threading

from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf

from registrationserver import config
from registrationserver.logger import logger

logger.debug("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    @staticmethod
    def get_ip():
        """Find my own IP address"""
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            test_socket.connect(("10.255.255.255", 1))
            ip_address = test_socket.getsockname()[0]
        except Exception:  # pylint: disable=broad-except
            ip_address = "127.0.0.1"
        finally:
            test_socket.close()
        logger.debug("My IP address is %s", ip_address)
        return ip_address

    def __init__(self, _type):
        """
        Initialize a mdns Listener for a specific device group
        """
        self.__type: str = type
        self.__lock = threading.Lock()
        self.__zeroconf = Zeroconf(
            ip_version=IPVersion.All, interfaces=[self.get_ip(), "127.0.0.1"]
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

    listener = MdnsListener(_type=config["TYPE"])
