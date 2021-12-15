"""Process listening for new connected SARAD instruments

:Created:
    2021-05-17

:Authors:
    | Riccardo Foerster <rfoerster@sarad.de>
    | Michael Strey <strey@sarad.de>

"""

import os

from registrationserver.config import config
from registrationserver.logger import logger
from thespian.actors import Actor, ActorSystem  # type: ignore


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self):
        self._system = ActorSystem()
        self._cluster = self._system.createActor(Actor, globalName="cluster")
        self.__dev_folder: str = config["DEV_FOLDER"] + os.path.sep
        if not os.path.exists(self.__dev_folder):
            os.makedirs(self.__dev_folder)
        logger.debug("Write device files to: %s", self.__dev_folder)
        # Clean __dev_folder for a fresh start
        self._remove_all_services()

    def run(self):
        """Start listening for new devices"""
        self._system.tell(self._cluster, {"CMD": "DO_LOOP"})
        logger.debug("Start polling RS-232 ports.")

    def _remove_all_services(self) -> None:
        """Kill all device actors and remove all device files from device folder."""
        if os.path.exists(self.__dev_folder):
            for root, _, files in os.walk(self.__dev_folder):
                for name in files:
                    if "local" in name:
                        dev_file = os.path.join(root, name)
                        logger.debug("[Del] Removed %s", name)
                        os.remove(dev_file)
