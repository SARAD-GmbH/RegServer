"""Creation of the logger singleton

Created
    2021-06-17

Authors
    Michael Strey <strey@sarad.de>
"""
import logging
import logging.config

from registrationserver.logdef import logcfg

try:
    logger
except NameError:
    logging.config.dictConfig(logcfg)
    logger = logging.getLogger("Reg. Server")
