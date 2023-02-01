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


def get_ip(ipv6=False):
    """Find the external IP address of the computer running the RegServer.
    TODO: The IPv6 part of this function is not yet functional!
    https://pypi.org/project/netifaces/ might help

    Returns:
        string: IP address
    """
    if ipv6:
        my_socket = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        my_socket.settimeout(0)
        try:
            # doesn't even have to be reachable
            my_socket.connect(("fe80::b630:531e:1381:33a3", 1))
            ipv6_address = my_socket.getsockname()[0]
        except Exception:  # pylint: disable=broad-except
            ipv6_address = "::1"
        finally:
            my_socket.close()
        return ipv6_address
    my_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    my_socket.settimeout(0)
    try:
        # doesn't even have to be reachable
        my_socket.connect(("10.255.255.255", 1))
        ipv4_address = my_socket.getsockname()[0]
    except Exception:  # pylint: disable=broad-except
        ipv4_address = "127.0.0.1"
    finally:
        my_socket.close()
    return ipv4_address


def get_hostname(ip_address):
    """Find the host name for the given IP address"""
    try:
        return socket.gethostbyaddr(ip_address)[0]
    except Exception:  # pylint: disable=broad-except
        return "unknown host"


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

# General configuration
DEFAULT_DESCRIPTION = "SARAD Instrument Server"
DEFAULT_PLACE = "Dresden"
DEFAULT_LATITUDE = 0
DEFAULT_LONGITUDE = 0
DEFAULT_HEIGHT = 0
level_dict = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "debug": logging.DEBUG,
    "fatal": logging.FATAL,
}
DEFAULT_LEVEL = logging.INFO
if customization.get("debug_level") in level_dict:
    DEBUG_LEVEL = level_dict[customization["debug_level"]]
else:
    DEBUG_LEVEL = DEFAULT_LEVEL
try:
    DEFAULT_IS_ID = socket.gethostname()
except Exception:  # pylint: disable=broad-except
    DEFAULT_IS_ID = "Instrument Server"
DEFAULT_MY_IP = get_ip(ipv6=False)
DEFAULT_MY_HOSTNAME = get_hostname(DEFAULT_MY_IP)

config = {
    "LEVEL": DEBUG_LEVEL,
    "IS_ID": customization.get("is_id", DEFAULT_IS_ID),
    "DESCRIPTION": customization.get("description", DEFAULT_DESCRIPTION),
    "PLACE": customization.get("place", DEFAULT_PLACE),
    "LATITUDE": customization.get("latitude", DEFAULT_LATITUDE),
    "LONGITUDE": customization.get("longitude", DEFAULT_LONGITUDE),
    "HEIGHT": customization.get("height", DEFAULT_HEIGHT),
    "MY_IP": customization.get("my_ip", DEFAULT_MY_IP),
    "MY_HOSTNAME": customization.get("my_hostname", DEFAULT_MY_HOSTNAME),
}

# Frontend configuration
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
        # REST frontend is part of the mDNS frontend
        frontend_config.add(Frontend.REST)
    if customization["frontends"].get("modbus_rtu", False):
        frontend_config.add(Frontend.MODBUS_RTU)

# Backend configuration
backend_config = set()
DEFAULT_BACKENDS = {Backend.USB, Backend.MDNS}

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

# Configuration of REST frontend
DEFAULT_API_PORT = 8008
DEFAULT_PORT_RANGE = range(50000, 50500)

if customization.get("rest_frontend") is None:
    rest_frontend_config = {
        "API_PORT": DEFAULT_API_PORT,
        "PORT_RANGE": DEFAULT_PORT_RANGE,
    }
else:
    try:
        port_range_list = customization["rest_frontend"]["port_range"]
        PORT_RANGE = range(port_range_list[0], port_range_list[-1])
    except Exception:  # pylint: disable=broad-except
        PORT_RANGE = DEFAULT_PORT_RANGE
    rest_frontend_config = {
        "API_PORT": customization["rest_frontend"].get("api_port", DEFAULT_API_PORT),
        "PORT_RANGE": PORT_RANGE,
    }

# Configuration of Modbus RTU frontend
DEFAULT_SLAVE_ADDRESS = 1
DEFAULT_PORT = "/dev/serial/by-id/usb-FTDI_Atil_UD-101i_USB__-__RS422_485-if00-port0"
DEFAULT_BAUDRATE = 9600
DEFAULT_PARITY = "N"
DEFAULT_DEVICE_ID = None
if customization.get("modbus_rtu_frontend") is None:
    modbus_rtu_frontend_config = {
        "SLAVE_ADDRESS": DEFAULT_SLAVE_ADDRESS,
        "PORT": DEFAULT_PORT,
        "BAUDRATE": DEFAULT_BAUDRATE,
        "PARITY": DEFAULT_PARITY,
        "DEVICE_ID": DEFAULT_DEVICE_ID,
    }
else:
    modbus_rtu_frontend_config = {
        "SLAVE_ADDRESS": customization["modbus_rtu_frontend"].get(
            "slave_address", DEFAULT_SLAVE_ADDRESS
        ),
        "PORT": customization["modbus_rtu_frontend"].get("port", DEFAULT_PORT),
        "BAUDRATE": customization["modbus_rtu_frontend"].get(
            "baudrate", DEFAULT_BAUDRATE
        ),
        "PARITY": customization["modbus_rtu_frontend"].get("parity", DEFAULT_PARITY),
        "DEVICE_ID": customization["modbus_rtu_frontend"].get(
            "device_id", DEFAULT_DEVICE_ID
        ),
    }

# mDNS defaults for frontend and backend
DEFAULT_TYPE = "_raw._tcp.local."
ip_version_dict = {
    "all": IPVersion.All,
    "v4only": IPVersion.V4Only,
    "v6only": IPVersion.V6Only,
}
DEFAULT_IP_VERSION = IPVersion.All

# mDNS backend configuration
DEFAULT_MDNS_TIMEOUT = 3000

if customization.get("mdns_backend") is None:
    mdns_backend_config = {
        "MDNS_TIMEOUT": DEFAULT_MDNS_TIMEOUT,
        "TYPE": DEFAULT_TYPE,
        "IP_VERSION": DEFAULT_IP_VERSION,
    }
else:
    if customization["mdns_backend"].get("ip_version") in ip_version_dict:
        IP_VERSION = ip_version_dict[customization["mdns_backend"]["ip_version"]]
    else:
        IP_VERSION = DEFAULT_IP_VERSION
    mdns_backend_config = {
        "MDNS_TIMEOUT": int(
            customization["mdns_backend"].get("mdns_timeout", DEFAULT_MDNS_TIMEOUT)
        ),
        "TYPE": customization["mdns_backend"].get("type", DEFAULT_TYPE),
        "IP_VERSION": IP_VERSION,
    }

# mDNS frontend configuration
if customization.get("mdns_frontend") is None:
    mdns_frontend_config = {
        "TYPE": DEFAULT_TYPE,
        "IP_VERSION": DEFAULT_IP_VERSION,
    }
else:
    if customization["mdns_frontend"].get("ip_version") in ip_version_dict:
        IP_VERSION = ip_version_dict[customization["ip_version"]]
    else:
        IP_VERSION = DEFAULT_IP_VERSION
    mdns_frontend_config = {
        "TYPE": customization["mdns_frontend"].get("type", DEFAULT_TYPE),
        "IP_VERSION": IP_VERSION,
    }

# USB backend configuration
if os.name == "nt":
    DEFAULT_POLL_SERIAL_PORTS = ["COM1"]
else:
    DEFAULT_POLL_SERIAL_PORTS = ["/dev/ttyS0"]
DEFAULT_IGNORED_SERIAL_PORTS: List[str] = []
DEFAULT_LOCAL_RETRY_INTERVAL = 30  # in seconds

if customization.get("usb_backend") is None:
    usb_backend_config = {
        "POLL_SERIAL_PORTS": DEFAULT_POLL_SERIAL_PORTS,
        "IGNORED_SERIAL_PORTS": DEFAULT_IGNORED_SERIAL_PORTS,
        "LOCAL_RETRY_INTERVAL": DEFAULT_LOCAL_RETRY_INTERVAL,
    }
else:
    usb_backend_config = {
        "POLL_SERIAL_PORTS": customization["usb_backend"].get(
            "poll_serial_ports", DEFAULT_POLL_SERIAL_PORTS
        ),
        "IGNORED_SERIAL_PORTS": customization["usb_backend"].get(
            "ignored_serial_ports", DEFAULT_IGNORED_SERIAL_PORTS
        ),
        "LOCAL_RETRY_INTERVAL": customization["usb_backend"].get(
            "local_retry_interval", DEFAULT_LOCAL_RETRY_INTERVAL
        ),
    }

rs485_backend_config = customization.get("rs485_backend", {})

# IS1 backend configuration
DEFAULT_REG_PORT = 50002
DEFAULT_SCAN_INTERVAL = 60

if customization.get("is1_backend") is None:
    is1_backend_config = {
        "REG_PORT": DEFAULT_REG_PORT,
        "SCAN_INTERVAL": DEFAULT_SCAN_INTERVAL,
    }
else:
    is1_backend_config = {
        "REG_PORT": customization["is1_backend"].get(
            "registration_port", DEFAULT_REG_PORT
        ),
        "SCAN_INTERVAL": customization["is1_backend"].get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        ),
    }

# Configuration of Actor system
DEFAULT_SYSTEM_BASE = "multiprocTCPBase"
DEFAULT_ADMIN_PORT = 1901
DEFAULT_WINDOWS_METHOD = "spawn"
DEFAULT_LINUX_METHOD = "fork"
DEFAULT_CONVENTION_ADDRESS = None
DEFAULT_KEEPALIVE_INTERVAL = 10  # in minutes
DEFAULT_WAIT_BEFORE_CHECK = 20  # in seconds, min. is set by cluster_actor
DEFAULT_CHECK = False
DEFAULT_OUTER_WATCHDOG_INTERVAL = 30  # in seconds
DEFAULT_OUTER_WATCHDOG_TRIALS = 3  # number of attempts to check Registrar

if customization.get("actor") is None:
    if os.name == "nt":
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_WINDOWS_METHOD,
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
            "KEEPALIVE_INTERVAL": DEFAULT_KEEPALIVE_INTERVAL,
            "WAIT_BEFORE_CHECK": DEFAULT_WAIT_BEFORE_CHECK,
            "CHECK": DEFAULT_CHECK,
            "OUTER_WATCHDOG_INTERVAl": DEFAULT_OUTER_WATCHDOG_INTERVAL,
            "OUTER_WATCHDOG_TRIALS": DEFAULT_OUTER_WATCHDOG_TRIALS,
        }
    else:
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_LINUX_METHOD,
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
            "KEEPALIVE_INTERVAL": DEFAULT_KEEPALIVE_INTERVAL,
            "WAIT_BEFORE_CHECK": DEFAULT_WAIT_BEFORE_CHECK,
            "CHECK": DEFAULT_CHECK,
            "OUTER_WATCHDOG_INTERVAl": DEFAULT_OUTER_WATCHDOG_INTERVAL,
            "OUTER_WATCHDOG_TRIALS": DEFAULT_OUTER_WATCHDOG_TRIALS,
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
                "Convention Address.IPv4": customization["actor"].get(
                    "convention_address", DEFAULT_CONVENTION_ADDRESS
                ),
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
                "Convention Address.IPv4": customization["actor"].get(
                    "convention_address", DEFAULT_CONVENTION_ADDRESS
                ),
            },
        }
    actor_config["KEEPALIVE_INTERVAL"] = customization["actor"].get(
        "watchdog_interval", DEFAULT_KEEPALIVE_INTERVAL
    )
    actor_config["WAIT_BEFORE_CHECK"] = customization["actor"].get(
        "watchdog_wait", DEFAULT_WAIT_BEFORE_CHECK
    )
    actor_config["CHECK"] = customization["actor"].get("watchdog_check", DEFAULT_CHECK)
    actor_config["OUTER_WATCHDOG_INTERVAl"] = customization["actor"].get(
        "outer_watchdog_interval", DEFAULT_OUTER_WATCHDOG_INTERVAL
    )
    actor_config["OUTER_WATCHDOG_TRIALS"] = customization["actor"].get(
        "outer_watchdog_trials", DEFAULT_OUTER_WATCHDOG_TRIALS
    )

# Configuration of MQTT clients used in MQTT frontend and MQTT backend
DEFAULT_MQTT_CLIENT_ID = "RegistrationServer"
DEFAULT_MQTT_BROKER = "85.214.243.156"  # Mosquitto running on sarad.de
DEFAULT_MQTT_PORT = 1883
DEFAULT_RETRY_INTERVAL = 5
DEFAULT_TLS_USE_TLS = False
DEFAULT_GROUP = "lan"
DEFAULT_TLS_CA_FILE = f"{app_folder}tls_cert_sarad.pem"
DEFAULT_TLS_KEY_FILE = f"{app_folder}tls_key_personal.pem"
DEFAULT_TLS_CERT_FILE = f"{app_folder}tls_cert_personal.crt"

if customization.get("mqtt") is None:
    mqtt_config = {
        "MQTT_CLIENT_ID": unique_id(DEFAULT_MQTT_CLIENT_ID),
        "MQTT_BROKER": DEFAULT_MQTT_BROKER,
        "GROUP": DEFAULT_GROUP,
        "PORT": DEFAULT_MQTT_PORT,
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
        "GROUP": customization["mqtt"].get("group", DEFAULT_GROUP),
        "PORT": customization["mqtt"].get("port", DEFAULT_MQTT_PORT),
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
# TODO Read GROUP from TLS_CERT_FILE
