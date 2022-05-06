"""mDNS Scheduler Actor for mDNS frontend

This actor will be created as singleton by the Registrar Actor if mDNS frontend
is active. It manages the creation and removal of Rfc2217Redirector Actors.

Created
    2022-05-05

Author
    Michael Strey <strey@sarad.de>

"""
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import (KillMsg,
                                               SetupRfc2217RedirectorMsg)
from registrationserver.base_actor import BaseActor
from registrationserver.helpers import diff_of_dicts, short_id
from registrationserver.logger import logger
from registrationserver.modules.mdns_frontend.rfc2217_redirector import \
    Rfc2217RedirectorActor

logger.debug("%s -> %s", __package__, __file__)


class MdnsSchedulerActor(BaseActor):
    """Actor interacting with a new device"""

    @staticmethod
    def _redirector(instr_id):
        return f"redirector-{instr_id}"

    @overrides
    def __init__(self):
        super().__init__()
        self.instr_id_actor_dict = {}  # {instr_id: device_actor}

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._subscribe_to_actor_dict_msg()

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        old_instr_id_actor_dict = self.instr_id_actor_dict
        self.instr_id_actor_dict = {
            short_id(device_id): dict["address"]
            for device_id, dict in self.actor_dict.items()
            if dict["is_device_actor"]
        }
        new_instruments = diff_of_dicts(
            self.instr_id_actor_dict, old_instr_id_actor_dict
        )
        logger.debug("New instruments %s", new_instruments)
        gone_instruments = diff_of_dicts(
            old_instr_id_actor_dict, self.instr_id_actor_dict
        )
        logger.debug("Gone instruments %s", gone_instruments)
        for instr_id in new_instruments:
            self._create_instrument(instr_id)
        for instr_id in gone_instruments:
            self._remove_instrument(instr_id)

    def _create_instrument(self, instr_id):
        """Create advertiser actor if it does not exist already"""
        logger.debug("Create mDNS Advertiser of %s", instr_id)
        redirector = self._create_actor(
            Rfc2217RedirectorActor, self._redirector(instr_id)
        )
        self.send(
            redirector,
            SetupRfc2217RedirectorMsg(device_actor=self.instr_id_actor_dict[instr_id]),
        )

    def _remove_instrument(self, instr_id):
        # pylint: disable=invalid-name
        """Remove the redirector actor for instr_id."""
        logger.debug("Remove RFC2217 Redirector of %s", instr_id)
        self.send(
            self.child_actors[self._redirector(instr_id)]["actor_address"], KillMsg()
        )
