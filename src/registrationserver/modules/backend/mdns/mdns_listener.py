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
import socket
import threading

import hashids  # type: ignore
from registrationserver.actor_messages import (ActorCreatedMsg, CreateActorMsg,
                                               SetDeviceStatusMsg,
                                               SetupIs1ActorMsg)
from registrationserver.config import config
from registrationserver.helpers import get_actor
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.device_actor import DeviceActor
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
        to the desired dictionary"""
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
            logger.critical("Fatal error")
            system_shutdown()
        return {
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

    def __init__(self, registrar_actor, service_type):
        """
        Initialize a mdns Listener for a specific device group
        """
        self.registrar = registrar_actor
        self.lock = threading.Lock()
        with self.lock:
            self.zeroconf = Zeroconf(
                ip_version=config["IP_VERSION"], interfaces=[self.get_ip(), "127.0.0.1"]
            )
            _ = ServiceBrowser(self.zeroconf, service_type, self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a new service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Add] Found service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            if info is not None:
                logger.info("[Add] %s", info.properties)
                actor_id = name
                reply = ActorSystem().ask(
                    self.registrar, CreateActorMsg(DeviceActor, actor_id)
                )
                if not isinstance(reply, ActorCreatedMsg):
                    logger.critical("Got message object of unexpected type")
                    logger.critical("-> Stop and shutdown system")
                    system_shutdown()
                else:
                    device_actor = reply.actor_address
                    data = self.convert_properties(name=name, info=info)
                    is_host = data["Remote"]["Address"]
                    is_port = data["Remote"]["Port"]
                    ActorSystem().tell(
                        device_actor, SetupIs1ActorMsg(is_host, is_port, None)
                    )
                    logger.debug("Setup the device actor with %s", data)
                    ActorSystem().tell(device_actor, SetDeviceStatusMsg(data))

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Del] Service %s of type %s", name, type_)
            info = zc.get_service_info(type_, name, timeout=config["MDNS_TIMEOUT"])
            logger.debug("[Del] Info: %s", info)
            device_actor = get_actor(self.registrar, name)
            if (device_actor is not None) and (device_actor != {}):
                logger.debug("Kill device actor %s", name)
                ActorSystem().tell(device_actor, ActorExitRequest())
            else:
                logger.warning("Actor %s does not exist.", name)

    def shutdown(self) -> None:
        """Cleanup"""
        self.zeroconf.close()