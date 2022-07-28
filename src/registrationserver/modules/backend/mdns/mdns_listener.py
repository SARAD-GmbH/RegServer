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
                                               KillMsg, SetDeviceStatusMsg,
                                               SetupMdnsActorMsg)
from registrationserver.config import config, mdns_backend_config
from registrationserver.helpers import (get_actor, sarad_protocol, short_id,
                                        transport_technology)
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.device_actor import DeviceActor
from registrationserver.shutdown import system_shutdown
from thespian.actors import ActorSystem  # type: ignore
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
            _model = properties.get(b"MODEL_ENC")
            if _model is None:
                return None
        _model = _model.decode("utf-8")
        _serial_short = properties.get(b"SERIAL_SHORT")
        if _serial_short is None:
            return None
        _device_id = _serial_short.decode("utf-8").split(".")[0]
        _sarad_protocol = _serial_short.decode("utf-8").split(".")[1]
        hids = hashids.Hashids()
        _ids = hids.decode(_device_id)
        if _ids is None:
            return None
        if len(_ids) != 3:
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
            "Remote": {
                "Address": _addr_ip,
                "Name": name,
                "API port": info.port,
                "Device Id": properties.get(b"DEVICE_ID").decode("utf-8"),
            },
        }

    @staticmethod
    def device_id(name):
        """Convert mDNS name into a proper device_id/actor_id"""
        if transport_technology(name) == mdns_backend_config["TYPE"]:
            return f"{short_id(name, check=False)}.{sarad_protocol(name)}.mdns"
        return name

    def __init__(self, registrar_actor, service_type):
        """
        Initialize a mdns Listener for a specific device group
        """
        self.registrar = registrar_actor
        self.lock = threading.Lock()
        with self.lock:
            self.zeroconf = Zeroconf(
                ip_version=mdns_backend_config["IP_VERSION"],
                interfaces=[config["MY_IP"], "127.0.0.1"],
            )
            _ = ServiceBrowser(self.zeroconf, service_type, self)

    def update_device_actor(self, device_actor, device_id, name, info):
        """Setup mDNS device actor with updated info"""
        logger.debug("Update %s with %s", device_id, info)
        if (device_actor is not None) and (info is not None):
            data = self.convert_properties(name=name, info=info)
            is_host = data["Remote"]["Address"]
            api_port = data["Remote"]["API port"]
            device_id = data["Remote"]["Device Id"]
            ActorSystem().tell(
                device_actor, SetupMdnsActorMsg(is_host, api_port, device_id)
            )
            logger.debug("Setup the device actor with %s", data)
            ActorSystem().tell(device_actor, SetDeviceStatusMsg(data))

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a new service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Add] Found service %s of type %s", name, type_)
            info = zc.get_service_info(
                type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
            )
            device_id = self.device_id(name)
            if info is not None:
                logger.info("[Add] %s", info.properties)
                actor_id = device_id
                with ActorSystem().private() as add_ser:
                    reply = add_ser.ask(
                        self.registrar, CreateActorMsg(DeviceActor, actor_id)
                    )
                if not isinstance(reply, ActorCreatedMsg):
                    logger.critical("Got message object of unexpected type")
                    logger.critical("-> Stop and shutdown system")
                    system_shutdown()
                elif reply.actor_address is not None:
                    device_actor = reply.actor_address
                    self.update_device_actor(device_actor, device_id, name, info)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a service
        representing a device is being updated"""
        logger.info("[Update] Service %s of type %s", name, type_)
        info = zc.get_service_info(
            type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
        )
        device_id = self.device_id(name)
        device_actor = get_actor(self.registrar, device_id)
        self.update_device_actor(device_actor, device_id, name, info)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a regular shutdown of a service
        representing a device is being detected"""
        with self.lock:
            logger.info("[Del] Service %s of type %s", name, type_)
            info = zc.get_service_info(
                type_, name, timeout=int(mdns_backend_config["MDNS_TIMEOUT"])
            )
            logger.debug("[Del] Info: %s", info)
            device_id = self.device_id(name)
            device_actor = get_actor(self.registrar, device_id)
            if (device_actor is not None) and (device_actor != {}):
                logger.debug("Kill device actor %s", device_id)
                ActorSystem().tell(device_actor, KillMsg())
            else:
                logger.warning("Actor %s does not exist.", device_id)

    def shutdown(self) -> None:
        """Cleanup"""
        self.zeroconf.close()
