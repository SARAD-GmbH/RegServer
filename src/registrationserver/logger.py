"""Creation of the logger singleton

:Created:
    2021-06-17

:Author:
    | Michael Strey <strey@sarad.de>
"""
import logging
import logging.config

from registrationserver.logdef import logcfg

try:
    logger  # pylint: disable=used-before-assignment
except NameError:
    logging.config.dictConfig(logcfg)
    logger: logging.Logger = logging.getLogger("Reg. Server")
