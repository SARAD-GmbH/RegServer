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
                                               SetupHostActorMsg)
from registrationserver.config import config, mdns_backend_config
from registrationserver.helpers import (get_actor, sanitize_hn, sarad_protocol,
                                        short_id, transport_technology)
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.host_actor import HostActor
from registrationserver.shutdown import system_shutdown
from thespian.actors import ActorSystem  # type: ignore
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

# logger.debug("%s -> %s", __package__, __file__)


class MdnsListener(ServiceListener):
    """Listens for mDNS multicast messages

    * adds new services (SARAD Instruments) to the system by creating a device actor
    * updates services with the latest info from mDNS multicast messages
    * removes services when they disapear from the network
    """

    @staticmethod
    def device_id(name):
        """Convert mDNS name into a proper device_id/actor_id"""
        if transport_technology(name) == mdns_backend_config["TYPE"]:
            return f"{short_id(name, check=False)}.{sarad_protocol(name)}.mdns"
        return name

    @staticmethod
    def get_host_addr(info=None):
        """Helper function to get the host name from mdns service information"""
        if info is None:
            logger.error("info in Zeroconf message is None")
            return None
        try:
            addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            return socket.gethostbyaddr(addr_ip)[0]
        except socket.herror:
            logger.error("No network connection.")
        except Exception:  # pylint: disable=broad-except
            logger.critical("Fatal error -> Emergency shutdown")
            system_shutdown()
        return None

    def convert_properties(self, zc, type_, name):
        # pylint: disable=invalid-name
        """Helper function to convert mdns service information
        to the desired dictionary"""
        info = zc.get_service_info(
            type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
        )
        if not info or not name:
            logger.error("info in Zeroconf message is None")
            return None
        properties = info.properties
        if properties is not None:
            model = properties.get(b"MODEL_ENC")
            if model is None:
                logger.error("model in Zeroconf message is None")
                return None
        model = model.decode("utf-8")
        occupied = bool(properties.get(b"OCCUPIED").decode("utf-8") == "True")
        serial_short = properties.get(b"SERIAL_SHORT")
        if serial_short is None:
            logger.error("_serial_short is None")
            return None
        instr_id = serial_short.decode("utf-8").split(".")[0]
        sarad_protocol_ = serial_short.decode("utf-8").split(".")[1]
        hids = hashids.Hashids()
        ids = hids.decode(instr_id)
        if ids is None:
            logger.error("ids is None")
            return None
        if len(ids) != 3:
            logger.error("len(ids) != 3")
            return None
        addr = ""
        try:
            addr_ip = ipaddress.IPv4Address(info.addresses[0]).exploded
            addr = socket.gethostbyaddr(addr_ip)[0]
        except socket.herror:
            logger.error("No network connection.")
            addr_ip = info.addresses[0]
        except Exception:  # pylint: disable=broad-except
            logger.critical("Fatal error")
            system_shutdown()
        return {
            self.device_id(name): {
                "Identification": {
                    "Name": properties[b"MODEL_ENC"].decode("utf-8"),
                    "Family": ids[0],
                    "Type": ids[1],
                    "Serial number": ids[2],
                    "Host": addr,
                    "Protocol": sarad_protocol_,
                },
                "Remote": {
                    "Address": addr_ip,
                    "Name": name,
                    "API port": info.port,
                    "Device Id": properties.get(b"DEVICE_ID").decode("utf-8"),
                },
                "Reservation": {
                    "Active": occupied,
                    "Host": "unknown",
                },
            }
        }

    def _get_host_actor(self, zc, type_, name):
        # pylint: disable=invalid-name
        info = zc.get_service_info(
            type_, name, timeout=mdns_backend_config["MDNS_TIMEOUT"]
        )
        hostname = sanitize_hn(self.get_host_addr(info))
        if hostname is None:
            logger.warning("Cannot handle Zeroconf service with info=%s", info)
            host_actor = None
        else:
            host_actor = get_actor(self.registrar, hostname)
        return host_actor, hostname

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
        self.hosts = mdns_backend_config["HOSTS"]
        if self.hosts:
            for host in self.hosts:
                hostname = sanitize_hn(host[0])
                logger.info("Ask Registrar to create Host Actor %s", hostname)
                with ActorSystem().private() as add_host:
                    try:
                        reply = add_host.ask(
                            self.registrar, CreateActorMsg(HostActor, hostname)
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                if not isinstance(reply, ActorCreatedMsg):
                    logger.critical("Got %s instead of ActorCreateMsg", reply)
                    logger.critical("-> Stop and shutdown system")
                    system_shutdown()
                elif reply.actor_address is None:
                    return
                else:
                    host_actor = reply.actor_address
                    ActorSystem().tell(
                        host_actor,
                        SetupHostActorMsg(
                            host=hostname,
                            port=host[1],
                            scan_interval=mdns_backend_config["SCAN_INTERVAL"],
                        ),
                    )

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a new service
        representing a device is being detected"""
        logger.debug("[Add] Service %s of type %s", name, type_)
        with self.lock:
            host_actor, hostname = self._get_host_actor(zc, type_, name)
            logger.debug("hostname: %s, host_actor: %s", hostname, host_actor)
            if hostname is None:
                return
            hostname = sanitize_hn(hostname)
            my_hostname = sanitize_hn(config["MY_HOSTNAME"])
            logger.debug("Host to add: %s", hostname)
            logger.debug("My hostname: %s", my_hostname)
            known_hostnames = set()
            for host in self.hosts:
                known_hostnames.add(sanitize_hn(host[0]))
            if (host_actor is None) and (my_hostname != hostname):
                logger.info("Ask Registrar to create Host Actor %s", hostname)
                with ActorSystem().private() as create_host:
                    try:
                        reply = create_host.ask(
                            self.registrar, CreateActorMsg(HostActor, hostname)
                        )
                    except ConnectionResetError as exception:
                        logger.debug(exception)
                        reply = None
                if not isinstance(reply, ActorCreatedMsg):
                    logger.critical("Got %s instead of ActorCreateMsg", reply)
                    logger.critical("-> Stop and shutdown system")
                    system_shutdown()
                elif reply.actor_address is None:
                    return
                else:
                    host_actor = reply.actor_address
            data = self.convert_properties(zc, type_, name)
            if (data is not None) and (host_actor is not None):
                logger.debug("Tell Host Actor to setup device actor with %s", data)
                ActorSystem().tell(host_actor, SetDeviceStatusMsg(data))
            elif data is None:
                logger.error(
                    "add_service was called with bad parameters: %s, %s, %s",
                    zc,
                    type_,
                    name,
                )

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # pylint: disable=invalid-name
        """Hook, being called when a service
        representing a device is being updated"""
        logger.debug("[Update] Service %s of type %s", name, type_)
        self.add_service(zc, type_, name)

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
            if device_actor is None:
                logger.warning("Actor %s does not exist.", device_id)
            else:
                logger.debug("Kill device actor %s", device_id)
                ActorSystem().tell(device_actor, KillMsg())

    def shutdown(self) -> None:
        """Cleanup"""
        self.zeroconf.close()
