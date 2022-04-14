"""Process listening for new connected SARAD instruments

:Created:
    2021-05-17

:Authors:
    | Riccardo Foerster <rfoerster@sarad.de>
    | Michael Strey <strey@sarad.de>

"""
import time

from registrationserver.actor_messages import AppType
from registrationserver.helpers import get_actor
from registrationserver.shutdown import is_flag_set


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self, registrar_actor, app_type):
        """Wait for the Registrar Actor to create the Cluster Actor."""
        if app_type is AppType.ISMQTT:
            mqtt_scheduler = None
            while mqtt_scheduler is None and is_flag_set():
                mqtt_scheduler = get_actor(registrar_actor, "mqtt_scheduler")
                time.sleep(1)
        self.cluster_actor = None
        while self.cluster_actor is None and is_flag_set():
            self.cluster_actor = get_actor(registrar_actor, "cluster")
            time.sleep(1)
