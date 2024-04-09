"""Device Actor for a NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from overrides import overrides
from regserver.actor_messages import ActorType
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor


class NetUsbActor(UsbActor):
    """Device Actor for a NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.actor_type = ActorType.NODE
        logger.info("NetUsbActor")
