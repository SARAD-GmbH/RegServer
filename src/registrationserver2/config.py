"""
Module for handing the configuration
Created on 30.09.2020

@author: rfoerster
"""
import sys
import logging
from logging import DEBUG
import registrationserver2

logging.getLogger("Registration Server V2").info(f"{__package__}->{__file__}")

if __name__ == "__main__":
    exec(
        open(registrationserver2.mainpy).read()
    )  # Executes the main python file if this file is called directly
    sys.exit()

config = {
    "MDNS_TIMEOUT": 3000,
    "TYPE": ["_sarad-1688._rfc2217._tcp.local.", "_rfc2217._tcp.local."],
    # 'FOLDER':          r'D:\test\rfc2217',
    "LEVEL": DEBUG,
}
"""
    Configuration Object
    TODO: Load from yaml file instead of a 'executable' file format
"""
