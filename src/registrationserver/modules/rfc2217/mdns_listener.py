"""Listening for mDNS multicast messages announcing the existence of new
services (SARAD devices) in the local network.

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml:: uml-mdns_listener.puml

"""
import ipaddress
import json
import socket
import threading

import hashids  # type: ignore
from registrationserver.actor_messages import (AppType, SetDeviceStatusMsg,
                                               SetupMsg)
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.rfc2217.rfc2217_actor import Rfc2217Actor
from registrationserver.shutdown import system_shutdown
from thespian.actors import ActorExitRequest, ActorSystem  # type: ignore
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

logger.debug("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    @staticmethod
    def convert_properties(info=None, name=""):
        """Helper function to convert mdns service information
        to the desired yaml format"""
        if not info or not name:
            return None
        properties = info.properties
        if properties is not None:
            _model = properties.get(b"MODEL_ENC", None)
            if _model is None:
                return None
        _model = _model.decode("utf-8")
        _serial_short = properties.get(b"SERIAL_SHORT", None)
        if _serial_short is None:
            return None
        _device_id = _serial_short.decode("utf-8").split(".")[0]
        _sarad_protocol = _serial_short.decode("utf-8").split(".")[1]
        hids = hashids.Hashids()
        _ids = hids.decode(_device_id)
        if _ids is None:
            return None
        if (len(_ids) != 3) or not info.port:
            return None
        _addr = ""
        try:
            _addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            _addr = socket.gethostbyaddr(_addr_ip)[0]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Fatal error")
        out = {
            "Identification": {
                "Name": properties[b"MODEL_ENC"].decode("utf-8"),
                "Family": _ids[0],
                "Type": _ids[1],
                "Serial number": _ids[2],
                "Host": _addr,
                "Protocol": _sarad_protocol,
            },
            "Remote": {"Address": _addr_ip, "Port": info.port, "Name": name},
        }
        logger.debug(out)
        return json.dumps(out)

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

    def __init__(self, service_type):
        """
        Initialize a mdns Listener for a specific device group
        """
        self.lock = threading.Lock()
        self.cluster = {}  # stores a dict of device actors {device_id: <actor address>}
        with self.lock:
            self.zeroconf = Zeroconf(
                ip_version=config["IP_VERSION"], interfaces=[self.get_ip(), "127.0.0.1"]
            )
            _ = ServiceBrowser(self.zeroconf, service_type, self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a new service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Add] Found service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            if info is not None:
                logger.info("[Add] %s", info.properties)
                device_actor = ActorSystem().createActor(Rfc2217Actor)
                # Take the first 3 elements to form a short_name
                short_name = ".".join(name.split(".", 3)[:-1])
                data = self.convert_properties(name=name, info=info)
                logger.debug("Ask to setup the device actor with %s", data)
                ActorSystem().tell(
                    device_actor, SetupMsg(short_name, "actor_system", AppType.RS)
                )
                ActorSystem().tell(device_actor, SetDeviceStatusMsg(data))
                self.cluster[short_name] = device_actor

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=C0103
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Del] Service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            logger.debug("[Del] Info: %s", info)
            try:
                device_actor = self.cluster[name]
            except KeyError:
                logger.critical("The actor to remove does not exist.")
                system_shutdown()
            logger.debug("Kill the device actor...")
            ActorSystem().tell(device_actor, ActorExitRequest())
            self.cluster.pop(name)

    def shutdown(self) -> None:
        """Cleanup"""
        self.zeroconf.close()
