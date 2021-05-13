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

config = {
    "MDNS_TIMEOUT": 3000,
    "TYPE": "_rfc2217._tcp.local.",
    "LEVEL": logging.DEBUG,
    "PORT_RANGE": range(50000, 50500),
    "ip_version": IPVersion.All,
}

# if LOCAL:
# TODO: The following line is only for the test phase.
if os.name == "nt":
    config["Host"] = "0.0.0.0"
else:
    config["Host"] = "192.168.10.19"

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
}
