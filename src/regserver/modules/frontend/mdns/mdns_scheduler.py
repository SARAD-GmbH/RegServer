"""mDNS Scheduler Actor for LAN frontend

This actor will be created as singleton by the Registrar Actor if the LAN
frontend is active. It manages the creation and removal of
MdnsAdvertiserActors.

Created
    2022-05-05

Author
    Michael Strey <strey@sarad.de>

"""

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, KillMsg,
                                      SetupMdnsAdvertiserActorMsg)
from regserver.base_actor import BaseActor
from regserver.helpers import diff_of_dicts, transport_technology
from regserver.logger import logger
from regserver.modules.frontend.mdns.mdns_advertiser import MdnsAdvertiserActor

# logger.debug("%s -> %s", __package__, __file__)


class MdnsSchedulerActor(BaseActor):
    """Actor interacting with a new device"""

    @staticmethod
    def _advertiser(device_id):
        return f"advertiser-{device_id}"

    @staticmethod
    def _active_device_actors(actor_dict):
        """Extract only active device actors from actor_dict"""
        active_device_actor_dict = {}
        for actor_id, description in actor_dict.items():
            if description["actor_type"] == ActorType.DEVICE:
                active_device_actor_dict[actor_id] = description
        return active_device_actor_dict

    @overrides
    def __init__(self):
        super().__init__()

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._subscribe_to_actor_dict_msg()

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        old_actor_dict = self._active_device_actors(self.actor_dict)
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        new_actor_dict = self._active_device_actors(self.actor_dict)
        new_device_actors = diff_of_dicts(new_actor_dict, old_actor_dict)
        logger.debug("New device actors %s", new_device_actors)
        gone_device_actors = diff_of_dicts(old_actor_dict, new_actor_dict)
        logger.debug("Gone device actors %s", gone_device_actors)
        for actor_id in new_device_actors:
            if transport_technology(actor_id) not in ("mdns", "mqtt"):
                self._create_instrument(actor_id)
        for actor_id in gone_device_actors:
            if transport_technology(actor_id) not in ("mdns", "mqtt"):
                self._remove_instrument(actor_id)

    def _create_instrument(self, device_id):
        """Create advertiser actor if it does not exist already"""
        logger.debug("Create MdnsAdvertiserActor of %s", device_id)
        my_advertiser = self._create_actor(
            MdnsAdvertiserActor, self._advertiser(device_id), None
        )
        self.send(
            my_advertiser,
            SetupMdnsAdvertiserActorMsg(
                device_actor=self.actor_dict[device_id]["address"]
            ),
        )

    def _remove_instrument(self, device_id):
        # pylint: disable=invalid-name
        """Remove the advertiser actor for instr_id."""
        logger.debug("Remove advertiser of %s", device_id)
        self.send(
            self.child_actors[self._advertiser(device_id)]["actor_address"], KillMsg()
        )
