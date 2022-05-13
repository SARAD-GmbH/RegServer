"""Module for handling of the configuration

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>
"""
import logging
import os
import socket
import sys
from typing import List
from uuid import getnode as get_mac

import toml
from zeroconf import IPVersion

from registrationserver.actor_messages import Backend, Frontend


def unique_id(ambiguous_id):
    """Create a unique id out of given id and MAC address of computer"""
    return f"{ambiguous_id}-{hex(get_mac())}"


home = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
app_folder = f"{home}{os.path.sep}SARAD{os.path.sep}"
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # We are running in a bundle
    config_path = f"{os.path.dirname(sys.executable)}{os.path.sep}"
else:
    config_path = f"{os.path.abspath(os.getcwd())}{os.path.sep}"
windows_config_file = f"{config_path}config_windows.toml"
linux_config_file = f"{config_path}config_linux.toml"
try:
    if os.name == "nt":
        config_file = windows_config_file
    else:
        config_file = linux_config_file
    customization = toml.load(config_file)
except OSError:
    customization = {}

DEFAULT_MDNS_TIMEOUT = 3000
DEFAULT_TYPE = "_raw._tcp.local."
DEFAULT_LEVEL = logging.INFO
DEFAULT_IP_VERSION = IPVersion.All
DEFAULT_PORT_RANGE = range(50000, 50500)
if os.name == "nt":
    DEFAULT_NATIVE_SERIAL_PORTS = ["COM1"]
else:
    DEFAULT_NATIVE_SERIAL_PORTS = ["/dev/ttyS0"]
DEFAULT_IGNORED_SERIAL_PORTS: List[str] = []
DEFAULT_LOCAL_RETRY_INTERVAL = 30  # in seconds
DEFAULT_API_PORT = 8008
DEFAULT_HOST = "localhost"
level_dict = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "debug": logging.DEBUG,
    "fatal": logging.FATAL,
}
if customization.get("debug_level") in level_dict:
    DEBUG_LEVEL = level_dict[customization["debug_level"]]
else:
    DEBUG_LEVEL = DEFAULT_LEVEL
ip_version_dict = {
    "all": IPVersion.All,
    "v4only": IPVersion.V4Only,
    "v6only": IPVersion.V6Only,
}
if customization.get("ip_version") in ip_version_dict:
    IP_VERSION = ip_version_dict[customization["ip_version"]]
else:
    IP_VERSION = DEFAULT_IP_VERSION
try:
    port_range_list = customization["port_range"]
    PORT_RANGE = range(port_range_list[0], port_range_list[-1])
except Exception:  # pylint: disable=broad-except
    PORT_RANGE = DEFAULT_PORT_RANGE

config = {
    "MDNS_TIMEOUT": customization.get("mdns_timeout", DEFAULT_MDNS_TIMEOUT),
    "TYPE": customization.get("type", DEFAULT_TYPE),
    "LEVEL": DEBUG_LEVEL,
    "IP_VERSION": IP_VERSION,
    "PORT_RANGE": PORT_RANGE,
    "NATIVE_SERIAL_PORTS": customization.get(
        "native_serial_ports", DEFAULT_NATIVE_SERIAL_PORTS
    ),
    "IGNORED_SERIAL_PORTS": customization.get(
        "ignored_serial_ports", DEFAULT_IGNORED_SERIAL_PORTS
    ),
    "LOCAL_RETRY_INTERVAL": customization.get(
        "local_retry_interval", DEFAULT_LOCAL_RETRY_INTERVAL
    ),
    "API_PORT": customization.get("api_port", DEFAULT_API_PORT),
    "HOST": customization.get("host", DEFAULT_HOST),
}

frontend_config = set()
DEFAULT_FRONTENDS = {Frontend.REST}
if customization.get("frontends") is None:
    frontend_config = DEFAULT_FRONTENDS
else:
    if customization["frontends"].get("rest", False):
        frontend_config.add(Frontend.REST)
    if customization["frontends"].get("mqtt", False):
        frontend_config.add(Frontend.MQTT)
    if customization["frontends"].get("mdns", False):
        frontend_config.add(Frontend.MDNS)

backend_config = set()
DEFAULT_BACKENDS = {Backend.USB, Backend.MDNS, Backend.MQTT, Backend.IS1}
if customization.get("backends") is None:
    backend_config = DEFAULT_BACKENDS
else:
    if customization["backends"].get("usb", False):
        backend_config.add(Backend.USB)
    if customization["backends"].get("mqtt", False):
        backend_config.add(Backend.MQTT)
    if customization["backends"].get("mdns", False):
        backend_config.add(Backend.MDNS)
    if customization["backends"].get("is1", False):
        backend_config.add(Backend.IS1)

DEFAULT_MDNS_PORT_RANGE = range(5560, 5580)
try:
    mdns_port_range_list = customization["mdns_frontend"]["port_range"]
    MDNS_PORT_RANGE = range(mdns_port_range_list[0], mdns_port_range_list[-1])
except Exception:  # pylint: disable=broad-except
    MDNS_PORT_RANGE = DEFAULT_MDNS_PORT_RANGE
mdns_frontend_config = {
    "MDNS_PORT_RANGE": MDNS_PORT_RANGE,
}

DEFAULT_SYSTEM_BASE = "multiprocTCPBase"
DEFAULT_ADMIN_PORT = 1901
DEFAULT_WINDOWS_METHOD = "spawn"
DEFAULT_LINUX_METHOD = "fork"
DEFAULT_CONVENTION_ADDRESS = None
if customization.get("actor") is None:
    if os.name == "nt":
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_WINDOWS_METHOD,
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
        }
    else:
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_LINUX_METHOD,
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
        }
else:
    if os.name == "nt":
        actor_config = {
            "systemBase": customization["actor"].get(
                "system_base", DEFAULT_SYSTEM_BASE
            ),
            "capabilities": {
                "Admin Port": customization["actor"].get(
                    "admin_port", DEFAULT_ADMIN_PORT
                ),
                "Process Startup Method": customization["actor"].get(
                    "process_startup_method", DEFAULT_WINDOWS_METHOD
                ),
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
        }
    else:
        actor_config = {
            "systemBase": customization["actor"].get(
                "system_base", DEFAULT_SYSTEM_BASE
            ),
            "capabilities": {
                "Admin Port": customization["actor"].get(
                    "admin_port", DEFAULT_ADMIN_PORT
                ),
                "Process Startup Method": customization["actor"].get(
                    "process_startup_method", DEFAULT_LINUX_METHOD
                ),
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
        }

DEFAULT_MQTT_CLIENT_ID = "RegistrationServer"
DEFAULT_MQTT_BROKER = "85.214.243.156"  # Mosquitto running on sarad.de
DEFAULT_PORT = 1883
DEFAULT_RETRY_INTERVAL = 5
DEFAULT_TLS_USE_TLS = False


DEFAULT_TLS_CA_FILE = f"{app_folder}tls_cert_sarad.pem"
DEFAULT_TLS_KEY_FILE = f"{app_folder}tls_key_personal.pem"
DEFAULT_TLS_CERT_FILE = f"{app_folder}tls_cert_personal.crt"


if customization.get("mqtt") is None:
    mqtt_config = {
        "MQTT_CLIENT_ID": unique_id(DEFAULT_MQTT_CLIENT_ID),
        "MQTT_BROKER": DEFAULT_MQTT_BROKER,
        "PORT": DEFAULT_PORT,
        "RETRY_INTERVAL": DEFAULT_RETRY_INTERVAL,
        "TLS_CA_FILE": DEFAULT_TLS_CA_FILE,
        "TLS_CERT_FILE": DEFAULT_TLS_CERT_FILE,
        "TLS_KEY_FILE": DEFAULT_TLS_KEY_FILE,
        "TLS_USE_TLS": DEFAULT_TLS_USE_TLS,
    }
else:
    use_tls = customization["mqtt"].get("tls_use_tls", DEFAULT_TLS_USE_TLS)
    mqtt_config = {
        "MQTT_CLIENT_ID": unique_id(
            customization["mqtt"].get("mqtt_client_id", DEFAULT_MQTT_CLIENT_ID)
        ),
        "MQTT_BROKER": customization["mqtt"].get("mqtt_broker", DEFAULT_MQTT_BROKER),
        "PORT": customization["mqtt"].get("port", DEFAULT_PORT),
        "RETRY_INTERVAL": customization["mqtt"].get(
            "retry_interval", DEFAULT_RETRY_INTERVAL
        ),
        "TLS_USE_TLS": use_tls,
        "TLS_CA_FILE": customization["mqtt"].get(
            "tls_ca_file",
            DEFAULT_TLS_CA_FILE,
        ),
        "TLS_CERT_FILE": customization["mqtt"].get(
            "tls_cert_file",
            DEFAULT_TLS_CERT_FILE,
        ),
        "TLS_KEY_FILE": customization["mqtt"].get(
            "tls_key_file",
            DEFAULT_TLS_KEY_FILE,
        ),
    }

try:
    DEFAULT_ISMQTT_IS_ID = socket.gethostname()
except Exception:  # pylint: disable=broad-except
    DEFAULT_ISMQTT_IS_ID = "IS_MQTT"
DEFAULT_ISMQTT_DESCRIPTION = "SARAD Instrument Server"
DEFAULT_ISMQTT_PLACE = "Dresden"
DEFAULT_ISMQTT_LATITUDE = 0
DEFAULT_ISMQTT_LONGITUDE = 0
DEFAULT_ISMQTT_HEIGHT = 0
if customization.get("ismqtt") is None:
    ismqtt_config = {
        "IS_ID": DEFAULT_ISMQTT_IS_ID,
        "DESCRIPTION": DEFAULT_ISMQTT_DESCRIPTION,
        "PLACE": DEFAULT_ISMQTT_PLACE,
        "LATITUDE": DEFAULT_ISMQTT_LATITUDE,
        "LONGITUDE": DEFAULT_ISMQTT_LONGITUDE,
        "HEIGHT": DEFAULT_ISMQTT_HEIGHT,
    }
else:
    ismqtt_config = {
        "IS_ID": customization["ismqtt"].get("is_id", DEFAULT_ISMQTT_IS_ID),
        "DESCRIPTION": customization["ismqtt"].get(
            "description", DEFAULT_ISMQTT_DESCRIPTION
        ),
        "PLACE": customization["ismqtt"].get("place", DEFAULT_ISMQTT_PLACE),
        "LATITUDE": customization["ismqtt"].get("latitude", DEFAULT_ISMQTT_LATITUDE),
        "LONGITUDE": customization["ismqtt"].get("longitude", DEFAULT_ISMQTT_LONGITUDE),
        "HEIGHT": customization["ismqtt"].get("height", DEFAULT_ISMQTT_HEIGHT),
    }
