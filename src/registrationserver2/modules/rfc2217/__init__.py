"""initialization of rfc2217 module, starting up mdns listener"""
from registrationserver2 import theLogger
from registrationserver2.config import config
from registrationserver2.modules.rfc2217.mdns_listener import SaradMdnsListener

theLogger.info("%s -> %s", __package__, __file__)

Test = SaradMdnsListener(_type=config["TYPE"])
