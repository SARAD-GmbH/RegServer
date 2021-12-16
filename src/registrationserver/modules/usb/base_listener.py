"""Process listening for new connected SARAD instruments

:Created:
    2021-05-17

:Authors:
    | Riccardo Foerster <rfoerster@sarad.de>
    | Michael Strey <strey@sarad.de>

"""
from registrationserver.logger import logger
from thespian.actors import Actor, ActorSystem  # type: ignore


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self):
        self._system = ActorSystem()
        self._cluster = self._system.createActor(Actor, globalName="cluster")

    def run(self):
        """Start listening for new devices"""
        self._system.tell(self._cluster, {"CMD": "DO_LOOP"})
        logger.debug("Start polling RS-232 ports.")
