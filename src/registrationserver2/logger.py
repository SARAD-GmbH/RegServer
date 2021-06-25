# =======================
# Logging configuration
# The order is important! Setup logger after the actor system.
# =======================
import logging
import logging.config

from registrationserver2.logdef import logcfg

try:
    logger
except NameError:
    logging.config.dictConfig(logcfg)
    logger = logging.getLogger("Reg. Server")
    logger.info("Logging system initialized.")
