"""
Module for handing the configuration
Created on 30.09.2020

@author: rfoerster
"""
from logging import DEBUG
from typing import Any, Dict

config: Dict[str, Any] = {
    "MDNS_TIMEOUT": 3000,
    "TYPE": ["_sarad-1688._rfc2217._tcp.local.", "_rfc2217._tcp.local."],
    # 'FOLDER':          r'D:\test\rfc2217',
    "LEVEL": DEBUG,
}
"""
    Configuration Object
    TODO: Load from yaml file instead of a 'executable' file format
"""
