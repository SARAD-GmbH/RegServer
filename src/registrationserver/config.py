"""Module for handing the configuration

Created
    2020-09-30

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>
"""
import logging
import os
import sys
from typing import List

import toml
from zeroconf import IPVersion

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
DEFAULT_TYPE = "_rfc2217._tcp.local."
DEFAULT_LEVEL = logging.INFO
DEFAULT_IP_VERSION = IPVersion.All
DEFAULT_DEV_FOLDER = f"{app_folder}devices"
DEFAULT_IC_HOST_FOLDER = f"{app_folder}hosts"
DEFAULT_PORT_RANGE = range(50000, 50500)
if os.name == "nt":
    DEFAULT_NATIVE_SERIAL_PORTS = ["COM1"]
else:
    DEFAULT_NATIVE_SERIAL_PORTS = ["/dev/ttyS0"]
DEFAULT_IGNORED_SERIAL_PORTS: List[str] = []
DEFAULT_LOCAL_RETRY_INTERVAL = 30  # in seconds
DEFAULT_API_PORT = 8000
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
port_range_list = customization.get("port_range")
try:
    PORT_RANGE = range(port_range_list[0], port_range_list[-1])
except Exception:  # pylint: disable=broad-except
    PORT_RANGE = DEFAULT_PORT_RANGE

config = {
    "MDNS_TIMEOUT": customization.get("mdns_timeout", DEFAULT_MDNS_TIMEOUT),
    "TYPE": customization.get("type", DEFAULT_TYPE),
    "LEVEL": DEBUG_LEVEL,
    "IP_VERSION": IP_VERSION,
    "DEV_FOLDER": DEFAULT_DEV_FOLDER,
    "IC_HOSTS_FOLDER": DEFAULT_IC_HOST_FOLDER,
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

DEFAULT_SYSTEM_BASE = "multiprocTCPBase"
DEFAULT_ADMIN_PORT = 1901
DEFAULT_WINDOWS_METHOD = "spawn"
DEFAULT_LINUX_METHOD = "fork"
if customization.get("actor") is None:
    if os.name == "nt":
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_WINDOWS_METHOD,
            },
        }
    else:
        actor_config = {
            "systemBase": DEFAULT_SYSTEM_BASE,
            "capabilities": {
                "Admin Port": DEFAULT_ADMIN_PORT,
                "Process Startup Method": DEFAULT_LINUX_METHOD,
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
            },
        }

DEFAULT_MQTT_CLIENT_ID = "SARAD_Subscriber"
DEFAULT_MQTT_BROKER = "85.214.243.156"  # Mosquitto running on sarad.de
DEFAULT_PORT = 1883
DEFAULT_RETRY_INTERVAL = 5
if customization.get("mqtt") is None:
    mqtt_config = {
        "MQTT_CLIENT_ID": DEFAULT_MQTT_CLIENT_ID,
        "MQTT_BROKER": DEFAULT_MQTT_BROKER,
        "PORT": DEFAULT_PORT,
        "RETRY_INTERVAL": DEFAULT_RETRY_INTERVAL,
    }
else:
    mqtt_config = {
        "MQTT_CLIENT_ID": customization["mqtt"].get(
            "mqtt_client_id", DEFAULT_MQTT_CLIENT_ID
        ),
        "MQTT_BROKER": customization["mqtt"].get("mqtt_broker", DEFAULT_MQTT_BROKER),
        "PORT": customization["mqtt"].get("port", DEFAULT_PORT),
        "RETRY_INTERVAL": customization["mqtt"].get(
            "retry_interval", DEFAULT_RETRY_INTERVAL
        ),
    }
