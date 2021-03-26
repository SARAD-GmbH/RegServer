from typing import Any

from registrationserver2 import actor_system as actor_system
from registrationserver2.modules.device_base_actor import \
    DeviceBaseActor as DeviceBaseActor
from registrationserver2.modules.messages import \
    RETURN_MESSAGES as RETURN_MESSAGES
from thespian.actors import Actor
from thespian.actors import ActorAddress as ActorAddress


class DeviceActorManager(Actor):
    ACCEPTED_MESSAGES: Any = ...
    actors: dict
    def receiveMessage(self, msg: Any, sender: Any) -> None: ...
    @staticmethod
    def _echo(msg: dict) -> dict: ...
    def _create(self, msg: dict) -> dict: ...
    def _kill(self, msg: dict) -> dict: ...

DEVICE_ACTOR_MANAGER: ActorAddress
