from typing import Any

from registrationserver2 import theLogger as theLogger
from registrationserver2.modules.device_base_actor import \
    DeviceBaseActor as DeviceBaseActor
from registrationserver2.modules.messages import \
    RETURN_MESSAGES as RETURN_MESSAGES


class Rfc2217Actor(DeviceBaseActor):
    def _send(self, msg: dict) -> Any: ...
    def _reserve(self, msg: Any): ...
    def _free(self, msg: Any) -> None: ...
    def _kill(self, msg: dict) -> Any: ...

def _test() -> None: ...
