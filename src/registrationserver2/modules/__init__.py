'''Loading all modules'''
# https://stackoverflow.com/a/3365846
import pkgutil
import logging

logging.getLogger('Registration Server V2').info(f'{__package__}->{__file__}')

__all__ = []
for loader, module_name, is_pkg in pkgutil.walk_packages(__path__):
    __all__.append(module_name)
    _module = loader.find_module(module_name).load_module(module_name)
    globals()[module_name] = _module
