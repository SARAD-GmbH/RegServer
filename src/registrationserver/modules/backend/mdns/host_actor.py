"""Actor representing an instrument server host in mDNS backend

:Created:
    2022-10-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg, SetDeviceStatusMsg,
                                               SetupMdnsActorMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.logger import logger
from registrationserver.modules.backend.mdns.device_actor import DeviceActor


class HostActor(BaseActor):
    """Class representing a host providing at least one SARAD instrument."""

    @overrides
    def __init__(self):
        super().__init__()
        self.is_device_actor = False
        self.on_kill = True

    def receiveMsg_SetDeviceStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for SetDeviceStatusMsg initialising the device status information."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        device_id = list(msg.device_status)[0]
        data = msg.device_status[device_id]
        is_host = data["Remote"]["Address"]
        api_port = data["Remote"]["API port"]
        remote_device_id = data["Remote"]["Device Id"]
        if device_id not in self.child_actors:
            device_actor = self._create_actor(DeviceActor, device_id)
            self.send(
                device_actor, SetupMdnsActorMsg(is_host, api_port, remote_device_id)
            )
        else:
            device_actor = self.child_actors[device_id]["actor_address"]
        self.send(device_actor, SetDeviceStatusMsg(data))

    def receiveMsg_RemoveMdnsActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for RemoveMdnsActorMsg commanding the Host Actor to remove a Device Actor."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.device_id in self.child_actors:
            self.send(self.child_actors[msg.device_id]["actor_address"], KillMsg())
