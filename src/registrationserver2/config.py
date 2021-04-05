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
from typing import Any, Dict

config: Dict[str, Any] = {
    "MDNS_TIMEOUT": 3000,
    "TYPE": "_rfc2217._tcp.local.",
    "LEVEL": logging.DEBUG,
    "PORT_RANGE": range(50000, 50500),
    "HOST": "192.168.178.20",
    "systemBase": "multiprocTCPBase",
    "capabilities": {"Admin Port": 1901, "Process Startup Method": "fork"},
}
