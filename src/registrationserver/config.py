"""Module for handing the configuration

Created
    2020-09-30

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

Todo:
    * Load from yaml file instead of a 'executable' file format
"""
import logging
import os

from zeroconf import IPVersion

LOCAL = False

home = os.environ.get("HOME") or os.environ.get("LOCALAPPDATA")
app_folder = f"{home}{os.path.sep}SARAD{os.path.sep}"

config = {
    "MDNS_TIMEOUT": 3000,
    "TYPE": "_rfc2217._tcp.local.",
    "LEVEL": logging.INFO,
    "ip_version": IPVersion.All,
    "DEV_FOLDER": f"{app_folder}devices",
    "IC_HOSTS_FOLDER": f"{app_folder}hosts",
    "PORT_RANGE": range(50000, 50500),
    "NATIVE_SERIAL_PORTS": ["COM1"],
    "IGNORED_SERIAL_PORTS": ["COM2", "COM3", "COM4", "COM5", "COM6"],
    "LOCAL_RETRY_INTERVALL": 10,
}

if os.name == "nt":
    config["HOST"] = "127.0.0.1"
else:
    config["HOST"] = "192.168.10.19"  # Michael@HomeVPN
    # config["HOST"] = "192.168.10.116"  # Michael@Work
    # config["HOST"] = "192.168.178.20"  # Michael@Home

if os.name == "nt":
    actor_config = {
        "systemBase": "multiprocQueueBase",
        "capabilities": {"Admin Port": 1901, "Process Startup Method": "spawn"},
    }
else:
    actor_config = {
        "systemBase": "multiprocTCPBase",
        "capabilities": {"Admin Port": 1901, "Process Startup Method": "fork"},
    }

mqtt_config = {
    "MQTT_CLIENT_ID": "SARAD_Subscriber",
    # "MQTT_BROKER": "127.0.0.1",
    "MQTT_BROKER": "85.214.243.156",  # Mosquitto running on sarad.de
    "PORT": 1883,
    "RETRY_INTERVALL": 5,
}
