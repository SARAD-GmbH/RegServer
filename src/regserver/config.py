"""Module for handling of the configuration

:Created:
    2020-09-30

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>
"""

import logging
import os
import re
import socket
from typing import TypedDict
from uuid import getnode as get_mac

import tomlkit
from platformdirs import PlatformDirs
from zeroconf import IPVersion

from regserver.actor_messages import Backend, Frontend


class RestFrontendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for rest_frontend_config."""
    API_PORT: int
    PORT_RANGE: range


class ModbusRtuFrontendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for modbus_rtu_frontend_config."""
    SLAVE_ADDRESS: int
    PORT: str
    BAUDRATE: int
    PARITY: str
    DEVICE_ID: str


class LocalBackendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for local_backend_config."""
    POLL_SERIAL_PORTS: list[str]
    IGNORED_SERIAL_PORTS: list[str]
    IGNORED_HWIDS: list[str]
    LOCAL_RETRY_INTERVAL: float
    SET_RTC: bool
    UTC_OFFSET: float


class Is1BackendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for is1_backend_config."""
    REG_PORT: int
    SCAN_INTERVAL: float
    IS1_HOSTS: list[str]
    IS1_PORT: int


class LanBackendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for lan_backend_config."""
    MDNS_TIMEOUT: int
    TYPE: str
    IP_VERSION: IPVersion
    HOSTS_WHITELIST: list[tuple[str, int]]
    HOSTS_BLACKLIST: list[str]
    SCAN_INTERVAL: int


class MqttConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for mqtt_config."""
    MQTT_CLIENT_ID: str
    MQTT_BROKER: str
    GROUP: str
    PORT: int
    KEEPALIVE: int
    QOS: int
    RETRY_INTERVAL: int
    TLS_CA_FILE: str
    TLS_CERT_FILE: str
    TLS_KEY_FILE: str
    TLS_USE_TLS: bool


class LanFrontendConfig(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for lan_frontend_config."""
    TYPE: str
    IP_VERSION: IPVersion


class ActorConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for actor_config."""
    systemBase: str
    capabilities: dict
    KEEPALIVE_INTERVAL: float
    WAIT_BEFORE_CHECK: float
    CHECK: bool
    OUTER_WATCHDOG_INTERVAL: float
    OUTER_WATCHDOG_TRIALS: int


class MqttFrontendConfigDict(TypedDict):
    # pylint: disable=inherit-non-class, too-few-public-methods
    """Type declaration for mqtt_frontend_config."""
    REBOOT_AFTER: float
    RESTART_INSTEAD_OF_REBOOT: int


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


os.environ["XDG_CONFIG_DIRS"] = "/etc:/usr/local/etc"
if os.name == "nt":
    APP_NAME = "RegServer-Service"
else:
    APP_NAME = "regserver"
APP_VENDOR = "SARAD"
dirs = PlatformDirs(APP_NAME, APP_VENDOR)
if os.name == "nt":
    home = os.environ.get("LOCALAPPDATA")
else:
    home = os.environ.get("HOME") or f"{dirs.site_cache_dir}"
    os.makedirs(home, exist_ok=True)
CONFIG_FOLDER = f"{dirs.site_config_dir}{os.path.sep}"
CONFIG_FILE = f"{CONFIG_FOLDER}config.toml"
if os.name == "nt":
    TLS_FOLDER = f"{home}{os.path.sep}SARAD{os.path.sep}"
else:
    TLS_FOLDER = CONFIG_FOLDER
try:
    with open(CONFIG_FILE, encoding="utf8") as custom_file:
        customization = tomlkit.load(custom_file)
except OSError:
    customization = tomlkit.document()
PING_FILE_NAME = f"{home}{os.sep}ping"
os.makedirs(os.path.dirname(PING_FILE_NAME), exist_ok=True)
FRMT = "%Y-%m-%dT%H:%M:%S"

# General configuration
DEFAULT_DESCRIPTION = "SARAD Instrument Server"
DEFAULT_PLACE = ""
DEFAULT_LATITUDE = 0
DEFAULT_LONGITUDE = 0
DEFAULT_ALTITUDE = 0
level_dict = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "debug": logging.DEBUG,
    "fatal": logging.FATAL,
}
DEFAULT_LEVEL = logging.INFO
if customization.value.get("debug_level") in level_dict:
    DEBUG_LEVEL = level_dict[customization.value["debug_level"]]
else:
    DEBUG_LEVEL = DEFAULT_LEVEL
if os.name == "nt":
    DEFAULT_LOG_FOLDER = f"{TLS_FOLDER}log{os.path.sep}"
else:
    DEFAULT_LOG_FOLDER = "/var/log/"
DEFAULT_LOG_FILE = "regserver.log"
DEFAULT_NR_OF_LOG_FILES = 10
try:
    DEFAULT_IS_ID = socket.gethostname()
except Exception:  # pylint: disable=broad-except
    DEFAULT_IS_ID = "Instrument Server"
DEFAULT_MY_IP = get_ip(ipv6=False)
DEFAULT_MY_HOSTNAME = get_hostname(DEFAULT_MY_IP)

config = {
    "LEVEL": DEBUG_LEVEL,
    "LOG_FOLDER": customization.value.get("log_folder", DEFAULT_LOG_FOLDER),
    "LOG_FILE": customization.value.get("log_file", DEFAULT_LOG_FILE),
    "NR_OF_LOG_FILES": customization.value.get(
        "nr_of_log_files", DEFAULT_NR_OF_LOG_FILES
    ),
    "IS_ID": customization.value.get("is_id", DEFAULT_IS_ID),
    "DESCRIPTION": customization.value.get("description", DEFAULT_DESCRIPTION),
    "PLACE": customization.value.get("place", DEFAULT_PLACE),
    "LATITUDE": customization.value.get("latitude", DEFAULT_LATITUDE),
    "LONGITUDE": customization.value.get("longitude", DEFAULT_LONGITUDE),
    "ALTITUDE": customization.value.get("altitude", DEFAULT_ALTITUDE),
    "MY_IP": customization.value.get("my_ip", DEFAULT_MY_IP),
    "MY_HOSTNAME": customization.value.get("my_hostname", DEFAULT_MY_HOSTNAME),
}

# Frontend configuration
frontend_config = set()
DEFAULT_FRONTENDS = {Frontend.REST, Frontend.LAN}

if customization.value.get("frontends") is None:
    frontend_config = DEFAULT_FRONTENDS
else:
    if customization.value["frontends"].get("rest", True):
        frontend_config.add(Frontend.REST)
    if customization.value["frontends"].get("mqtt", False):
        frontend_config.add(Frontend.MQTT)
    if customization.value["frontends"].get("lan", True):
        frontend_config.add(Frontend.LAN)
        # REST frontend is part of the LAN frontend
        frontend_config.add(Frontend.REST)
    if customization.value["frontends"].get("modbus_rtu", False):
        frontend_config.add(Frontend.MODBUS_RTU)

# Configuration of MQTT clients used in MQTT frontend and MQTT backend
DEFAULT_MQTT_CLIENT_ID = "Id"
DEFAULT_MQTT_BROKER = "sarad.de"  # Mosquitto running on sarad.de
DEFAULT_MQTT_PORT = 8883
DEFAULT_KEEPALIVE = 60
DEFAULT_QOS = 1
DEFAULT_RETRY_INTERVAL = 5
DEFAULT_TLS_USE_TLS = True
DEFAULT_TLS_CA_FILE = f"{TLS_FOLDER}tls_cert_sarad.pem"
DEFAULT_TLS_KEY_FILE = f"{TLS_FOLDER}tls_key_personal.pem"
DEFAULT_TLS_CERT_FILE = f"{TLS_FOLDER}tls_cert_personal.crt"
tls_present = os.path.isfile(DEFAULT_TLS_CERT_FILE)
if tls_present:
    with open(DEFAULT_TLS_CERT_FILE, encoding="utf8") as cert_file:
        matches = re.match(r".+CN=(.+)[_][0-9]{4}.+", cert_file.read(), flags=re.S)
        if matches is not None:
            DEFAULT_GROUP = matches.group(1)
        else:
            DEFAULT_GROUP = "lan"
else:
    DEFAULT_GROUP = "lan"

if customization.value.get("mqtt") is None:
    mqtt_config: MqttConfigDict = {
        "MQTT_CLIENT_ID": unique_id(DEFAULT_MQTT_CLIENT_ID),
        "MQTT_BROKER": DEFAULT_MQTT_BROKER,
        "GROUP": DEFAULT_GROUP,
        "PORT": DEFAULT_MQTT_PORT,
        "KEEPALIVE": DEFAULT_KEEPALIVE,
        "QOS": DEFAULT_QOS,
        "RETRY_INTERVAL": DEFAULT_RETRY_INTERVAL,
        "TLS_CA_FILE": DEFAULT_TLS_CA_FILE,
        "TLS_CERT_FILE": DEFAULT_TLS_CERT_FILE,
        "TLS_KEY_FILE": DEFAULT_TLS_KEY_FILE,
        "TLS_USE_TLS": DEFAULT_TLS_USE_TLS,
    }
else:
    use_tls = customization.value["mqtt"].get("tls_use_tls", DEFAULT_TLS_USE_TLS)
    mqtt_config = {
        "MQTT_CLIENT_ID": unique_id(
            customization.value["mqtt"].get("mqtt_client_id", DEFAULT_MQTT_CLIENT_ID)
        ),
        "MQTT_BROKER": customization.value["mqtt"].get(
            "mqtt_broker", DEFAULT_MQTT_BROKER
        ),
        "GROUP": customization.value["mqtt"].get("group", DEFAULT_GROUP),
        "PORT": int(customization.value["mqtt"].get("port", DEFAULT_MQTT_PORT)),
        "KEEPALIVE": int(
            customization.value["mqtt"].get("keepalive", DEFAULT_KEEPALIVE)
        ),
        "QOS": int(customization.value["mqtt"].get("qos", DEFAULT_QOS)),
        "RETRY_INTERVAL": int(
            customization.value["mqtt"].get("retry_interval", DEFAULT_RETRY_INTERVAL)
        ),
        "TLS_USE_TLS": use_tls,
        "TLS_CA_FILE": customization.value["mqtt"].get(
            "tls_ca_file",
            DEFAULT_TLS_CA_FILE,
        ),
        "TLS_CERT_FILE": customization.value["mqtt"].get(
            "tls_cert_file",
            DEFAULT_TLS_CERT_FILE,
        ),
        "TLS_KEY_FILE": customization.value["mqtt"].get(
            "tls_key_file",
            DEFAULT_TLS_KEY_FILE,
        ),
    }

# Backend configuration
backend_config = set()
DEFAULT_BACKENDS = {Backend.LOCAL, Backend.LAN}

if customization.value.get("backends") is None:
    backend_config = DEFAULT_BACKENDS
    if tls_present:
        backend_config.add(Backend.MQTT)
else:
    if customization.value["backends"].get("local", True):
        backend_config.add(Backend.LOCAL)
    mqtt_backend = customization.value["backends"].get("mqtt", 2)
    if (mqtt_backend == 1) or ((mqtt_backend == 2) and tls_present):
        backend_config.add(Backend.MQTT)
    if customization.value["backends"].get("lan", True):
        backend_config.add(Backend.LAN)
    if customization.value["backends"].get("is1", False):
        backend_config.add(Backend.IS1)

# Configuration of REST frontend
DEFAULT_API_PORT = 8008
DEFAULT_PORT_RANGE = range(50003, 50500)

if customization.value.get("rest_frontend") is None:
    rest_frontend_config: RestFrontendConfigDict = {
        "API_PORT": DEFAULT_API_PORT,
        "PORT_RANGE": DEFAULT_PORT_RANGE,
    }
else:
    try:
        port_range_list = customization.value["rest_frontend"]["port_range"]
        PORT_RANGE = range(port_range_list[0], port_range_list[-1])
    except Exception:  # pylint: disable=broad-except
        PORT_RANGE = DEFAULT_PORT_RANGE
    rest_frontend_config = {
        "API_PORT": int(
            customization.value["rest_frontend"].get("api_port", DEFAULT_API_PORT)
        ),
        "PORT_RANGE": PORT_RANGE,
    }

# Configuration of Modbus RTU frontend
DEFAULT_SLAVE_ADDRESS = 1
DEFAULT_PORT = "/dev/serial/by-id/usb-FTDI_Atil_UD-101i_USB__-__RS422_485-if00-port0"
DEFAULT_BAUDRATE = 9600
DEFAULT_PARITY = "N"
DEFAULT_DEVICE_ID = ""
if customization.value.get("modbus_rtu_frontend") is None:
    modbus_rtu_frontend_config: ModbusRtuFrontendConfigDict = {
        "SLAVE_ADDRESS": DEFAULT_SLAVE_ADDRESS,
        "PORT": DEFAULT_PORT,
        "BAUDRATE": DEFAULT_BAUDRATE,
        "PARITY": DEFAULT_PARITY,
        "DEVICE_ID": DEFAULT_DEVICE_ID,
    }
else:
    modbus_rtu_frontend_config = {
        "SLAVE_ADDRESS": customization.value["modbus_rtu_frontend"].get(
            "slave_address", DEFAULT_SLAVE_ADDRESS
        ),
        "PORT": customization.value["modbus_rtu_frontend"].get("port", DEFAULT_PORT),
        "BAUDRATE": int(
            customization.value["modbus_rtu_frontend"].get("baudrate", DEFAULT_BAUDRATE)
        ),
        "PARITY": customization.value["modbus_rtu_frontend"].get(
            "parity", DEFAULT_PARITY
        ),
        "DEVICE_ID": customization.value["modbus_rtu_frontend"].get(
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

# LAN backend configuration
DEFAULT_MDNS_TIMEOUT = 3000
DEFAULT_HOSTS_WHITELIST: list[tuple[str, int]] = []
DEFAULT_HOSTS_BLACKLIST: list[str] = []
DEFAULT_HOSTS_SCAN_INTERVAL = 60  # in seconds

if customization.value.get("lan_backend") is None:
    lan_backend_config: LanBackendConfigDict = {
        "MDNS_TIMEOUT": DEFAULT_MDNS_TIMEOUT,
        "TYPE": DEFAULT_TYPE,
        "IP_VERSION": DEFAULT_IP_VERSION,
        "HOSTS_WHITELIST": DEFAULT_HOSTS_WHITELIST,
        "HOSTS_BLACKLIST": DEFAULT_HOSTS_BLACKLIST,
        "SCAN_INTERVAL": DEFAULT_HOSTS_SCAN_INTERVAL,
    }
else:
    if customization.value["lan_backend"].get("ip_version") in ip_version_dict:
        IP_VERSION = ip_version_dict[customization.value["lan_backend"]["ip_version"]]
    else:
        IP_VERSION = DEFAULT_IP_VERSION
    lan_backend_config = {
        "MDNS_TIMEOUT": int(
            customization.value["lan_backend"].get("mdns_timeout", DEFAULT_MDNS_TIMEOUT)
        ),
        "TYPE": customization.value["lan_backend"].get("type", DEFAULT_TYPE),
        "IP_VERSION": IP_VERSION,
        "HOSTS_WHITELIST": customization.value["lan_backend"].get(
            "hosts_whitelist", DEFAULT_HOSTS_WHITELIST
        ),
        "HOSTS_BLACKLIST": customization.value["lan_backend"].get(
            "hosts_blacklist", DEFAULT_HOSTS_BLACKLIST
        ),
        "SCAN_INTERVAL": int(
            customization.value["lan_backend"].get(
                "scan_interval", DEFAULT_HOSTS_SCAN_INTERVAL
            )
        ),
    }

# LAN frontend configuration
if customization.value.get("lan_frontend") is None:
    lan_frontend_config: LanFrontendConfig = {
        "TYPE": DEFAULT_TYPE,
        "IP_VERSION": DEFAULT_IP_VERSION,
    }
else:
    if customization.value["lan_frontend"].get("ip_version") in ip_version_dict:
        IP_VERSION = ip_version_dict[customization.value["ip_version"]]
    else:
        IP_VERSION = DEFAULT_IP_VERSION
    lan_frontend_config = {
        "TYPE": customization.value["lan_frontend"].get("type", DEFAULT_TYPE),
        "IP_VERSION": IP_VERSION,
    }

# Local backend configuration
if os.name == "nt":
    DEFAULT_POLL_SERIAL_PORTS = ["COM1"]
else:
    DEFAULT_POLL_SERIAL_PORTS = ["/dev/ttyS0"]
DEFAULT_IGNORED_SERIAL_PORTS: list[str] = []
DEFAULT_IGNORED_HWIDS: list[str] = ["BTHENUM", "2c7c"]
DEFAULT_LOCAL_RETRY_INTERVAL = 30  # in seconds
DEFAULT_SET_RTC = False
DEFAULT_UTC_OFFSET = 0

if customization.value.get("local_backend") is None:
    local_backend_config: LocalBackendConfigDict = {
        "POLL_SERIAL_PORTS": DEFAULT_POLL_SERIAL_PORTS,
        "IGNORED_SERIAL_PORTS": DEFAULT_IGNORED_SERIAL_PORTS,
        "IGNORED_HWIDS": DEFAULT_IGNORED_HWIDS,
        "LOCAL_RETRY_INTERVAL": DEFAULT_LOCAL_RETRY_INTERVAL,
        "SET_RTC": DEFAULT_SET_RTC,
        "UTC_OFFSET": DEFAULT_UTC_OFFSET,
    }
else:
    local_backend_config = {
        "POLL_SERIAL_PORTS": customization.value["local_backend"].get(
            "poll_serial_ports", DEFAULT_POLL_SERIAL_PORTS
        ),
        "IGNORED_SERIAL_PORTS": customization.value["local_backend"].get(
            "ignored_serial_ports", DEFAULT_IGNORED_SERIAL_PORTS
        ),
        "IGNORED_HWIDS": customization.value["local_backend"].get(
            "ignored_hwids", DEFAULT_IGNORED_HWIDS
        ),
        "LOCAL_RETRY_INTERVAL": int(
            customization.value["local_backend"].get(
                "local_retry_interval", DEFAULT_LOCAL_RETRY_INTERVAL
            )
        ),
        "SET_RTC": customization.value["local_backend"].get(
            "set_realtime_clock", DEFAULT_SET_RTC
        ),
        "UTC_OFFSET": customization.value["local_backend"].get(
            "utc_offset", DEFAULT_UTC_OFFSET
        ),
    }

rs485_backend_config = customization.value.get("rs485_backend", {})

# IS1 backend configuration
DEFAULT_REG_PORT = 50002
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_IS1_HOSTS: list[str] = []
DEFAULT_IS1_PORT = 50000

if customization.value.get("is1_backend") is None:
    is1_backend_config: Is1BackendConfigDict = {
        "REG_PORT": DEFAULT_REG_PORT,
        "SCAN_INTERVAL": DEFAULT_SCAN_INTERVAL,
        "IS1_HOSTS": DEFAULT_IS1_HOSTS,
        "IS1_PORT": DEFAULT_IS1_PORT,
    }
else:
    is1_backend_config = {
        "REG_PORT": int(
            customization.value["is1_backend"].get(
                "registration_port", DEFAULT_REG_PORT
            )
        ),
        "SCAN_INTERVAL": int(
            customization.value["is1_backend"].get(
                "scan_interval", DEFAULT_SCAN_INTERVAL
            )
        ),
        "IS1_HOSTS": customization.value["is1_backend"].get("hosts", DEFAULT_IS1_HOSTS),
        "IS1_PORT": customization.value["is1_backend"].get(
            "is1_port", DEFAULT_IS1_PORT
        ),
    }

# Configuration of Actor system
DEFAULT_SYSTEM_BASE = "multiprocTCPBase"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_ADMIN_PORT = 1901
DEFAULT_WINDOWS_METHOD = "spawn"
DEFAULT_LINUX_METHOD = "fork"
DEFAULT_CONVENTION_ADDRESS = f"{DEFAULT_HOST}:{DEFAULT_ADMIN_PORT}"
DEFAULT_KEEPALIVE_INTERVAL = 2  # in seconds
DEFAULT_WAIT_BEFORE_CHECK = 10  # in seconds
DEFAULT_CHECK = True
DEFAULT_OUTER_WATCHDOG_INTERVAL = 60  # in seconds
DEFAULT_OUTER_WATCHDOG_TRIALS = 1  # number of attempts to check Registrar

if customization.value.get("actor") is None:
    if os.name == "nt":
        actor_config: ActorConfigDict = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_WINDOWS_METHOD,
                "Convention Address.IPv4": DEFAULT_CONVENTION_ADDRESS,
            },
            "KEEPALIVE_INTERVAL": DEFAULT_KEEPALIVE_INTERVAL,
            "WAIT_BEFORE_CHECK": DEFAULT_WAIT_BEFORE_CHECK,
            "CHECK": DEFAULT_CHECK,
            "OUTER_WATCHDOG_INTERVAL": DEFAULT_OUTER_WATCHDOG_INTERVAL,
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
            "OUTER_WATCHDOG_INTERVAL": DEFAULT_OUTER_WATCHDOG_INTERVAL,
            "OUTER_WATCHDOG_TRIALS": DEFAULT_OUTER_WATCHDOG_TRIALS,
        }
else:
    if os.name == "nt":
        actor_config = {
            "systemBase": customization.value["actor"].get(
                "system_base", DEFAULT_SYSTEM_BASE
            ),
            "capabilities": {
                "Admin Port": int(
                    customization.value["actor"].get("admin_port", DEFAULT_ADMIN_PORT)
                ),
                "Process Startup Method": customization.value["actor"].get(
                    "process_startup_method", DEFAULT_WINDOWS_METHOD
                ),
                "Convention Address.IPv4": customization.value["actor"].get(
                    "convention_address", DEFAULT_CONVENTION_ADDRESS
                ),
            },
            "KEEPALIVE_INTERVAL": float(
                customization.value["actor"].get(
                    "watchdog_interval", DEFAULT_KEEPALIVE_INTERVAL
                )
            ),
            "WAIT_BEFORE_CHECK": float(
                customization.value["actor"].get(
                    "watchdog_wait", DEFAULT_WAIT_BEFORE_CHECK
                )
            ),
            "CHECK": customization.value["actor"].get("watchdog_check", DEFAULT_CHECK),
            "OUTER_WATCHDOG_INTERVAL": float(
                customization.value["actor"].get(
                    "outer_watchdog_interval", DEFAULT_OUTER_WATCHDOG_INTERVAL
                )
            ),
            "OUTER_WATCHDOG_TRIALS": int(
                customization.value["actor"].get(
                    "outer_watchdog_trials", DEFAULT_OUTER_WATCHDOG_TRIALS
                )
            ),
        }
    else:
        actor_config = {
            "systemBase": customization.value["actor"].get(
                "system_base", DEFAULT_SYSTEM_BASE
            ),
            "capabilities": {
                "Admin Port": int(
                    customization.value["actor"].get("admin_port", DEFAULT_ADMIN_PORT)
                ),
                "Process Startup Method": customization.value["actor"].get(
                    "process_startup_method", DEFAULT_LINUX_METHOD
                ),
                "Convention Address.IPv4": customization.value["actor"].get(
                    "convention_address", DEFAULT_CONVENTION_ADDRESS
                ),
            },
            "KEEPALIVE_INTERVAL": float(
                customization.value["actor"].get(
                    "watchdog_interval", DEFAULT_KEEPALIVE_INTERVAL
                )
            ),
            "WAIT_BEFORE_CHECK": float(
                customization.value["actor"].get(
                    "watchdog_wait", DEFAULT_WAIT_BEFORE_CHECK
                )
            ),
            "CHECK": customization.value["actor"].get("watchdog_check", DEFAULT_CHECK),
            "OUTER_WATCHDOG_INTERVAL": float(
                customization.value["actor"].get(
                    "outer_watchdog_interval", DEFAULT_OUTER_WATCHDOG_INTERVAL
                )
            ),
            "OUTER_WATCHDOG_TRIALS": int(
                customization.value["actor"].get(
                    "outer_watchdog_trials", DEFAULT_OUTER_WATCHDOG_TRIALS
                )
            ),
        }

# Configuration of MQTT frontend
DEFAULT_REBOOT_AFTER = 60
DEFAULT_RESTART_INSTEAD_OF_REBOOT = 0

if customization.value.get("mqtt_frontend") is None:
    mqtt_frontend_config: MqttFrontendConfigDict = {
        "REBOOT_AFTER": DEFAULT_REBOOT_AFTER,
        "RESTART_INSTEAD_OF_REBOOT": DEFAULT_RESTART_INSTEAD_OF_REBOOT,
    }
else:
    mqtt_frontend_config = {
        "REBOOT_AFTER": int(
            customization.value["mqtt_frontend"].get(
                "reboot_after", DEFAULT_REBOOT_AFTER
            )
        ),
        "RESTART_INSTEAD_OF_REBOOT": int(
            customization.value["mqtt_frontend"].get(
                "restart_instead_of_reboot", DEFAULT_RESTART_INSTEAD_OF_REBOOT
            )
        ),
    }

# Configuration of Monitoring Mode
monitoring_config = customization.value.get("monitoring", {})
