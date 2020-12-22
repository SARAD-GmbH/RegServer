'''initialization of rfc2217 module, starting up mdns listener'''
from registrationserver2 import config
from registrationserver2.modules.rfc2217.mdns_listener import SaradMdnsListener

if isinstance(config['TYPE'], list):
    Test = []
    for __type in config['TYPE']:
        Test.append(SaradMdnsListener(_type=__type))
else:
    Test = SaradMdnsListener(_type=config['TYPE'])
