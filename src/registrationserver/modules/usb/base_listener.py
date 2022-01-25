"""Process listening for new connected SARAD instruments

:Created:
    2021-05-17

:Authors:
    | Riccardo Foerster <rfoerster@sarad.de>
    | Michael Strey <strey@sarad.de>

"""
from registrationserver.modules.usb.cluster_actor import ClusterActor
from thespian.actors import ActorSystem  # type: ignore


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self):
        self._system = ActorSystem()
        self._cluster = self._system.createActor(ClusterActor, globalName="cluster")
