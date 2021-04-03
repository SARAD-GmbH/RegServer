"""Main actor of the Registration Server -- implementation for RFC 2217

Created
    2020-10-14

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-rfc2217_actor.puml
"""
import time
import traceback

import serial.rfc2217  # type: ignore
import thespian  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.messages import RETURN_MESSAGES

logger.info("%s -> %s", __package__, __file__)


class Rfc2217Actor(DeviceBaseActor):
    """Actor for dealing with RFC2217 Connections, creates and maintains
    a RFC2217Protocol handler and relays messages towards it
    https://pythonhosted.org/pyserial/pyserial_api.html#module-serial.aio"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new RFC2217 actor.")
        super().__init__()
        self.__port: serial.rfc2217.Serial = None
        logger.debug("RFC2217 actor created.")

    def _connect(self):
        """internal Function to connect to instrument server 2 over rfc2217"""
        if self._file:
            address = self._file.get("Remote", {}).get("Address", None)
            port = self._file.get("Remote", {}).get("Port", None)
            if not address or not port:
                return RETURN_MESSAGES.get("ILLEGAL_STATE")
            port_ident = fr"rfc2217://{address}:{port}"

        if port_ident and not (self.__port and self.__port.is_open):
            try:
                self.__port = serial.rfc2217.Serial(port_ident)
                # move the send ( test if connection is up and if not create)
            except Exception as error:  # pylint: disable=broad-except
                logger.error(
                    "! %s\t%s\t%s\t%s",
                    type(error),
                    error,
                    vars(error) if isinstance(error, dict) else "-",
                    traceback.format_exc(),
                )
        if self.__port and self.__port.is_open:
            return RETURN_MESSAGES.get("OK")
        return RETURN_MESSAGES.get("ILLEGAL_STATE")

    def _send(self, msg: dict):
        if self._connect() is RETURN_MESSAGES["OK"]["RETURN"]:
            data = msg["PAR"]["DATA"]
            logger.info("Actor %s received: %s", self.globalName, data)
            self.__port.write(data)
            _return = b""
            while True:
                time.sleep(0.5)
                _return_part = self.__port.read_all() if self.__port.inWaiting() else ""
                if _return_part == "":
                    break
                _return = _return + _return_part
            full_return = RETURN_MESSAGES["OK"]
            full_return["RESULT"] = {"DATA": _return}
            return full_return
        return RETURN_MESSAGES.get("ILLEGAL_STATE")

    @overrides
    def _free(self, msg: dict):
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        return super()._free(msg)

    @overrides
    def _kill(self, msg: dict):
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        return super()._kill(msg)

    @overrides
    def _reserve_at_is(self, app, host, user) -> bool:
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules."""
        return True


def _test():
    sys = thespian.actors.ActorSystem()
    act = sys.createActor(
        Rfc2217Actor, globalName="0ghMF8Y.sarad-1688._rfc2217._tcp.local."
    )
    sys.ask(act, {"CMD": "SETUP"})
    print(
        sys.ask(act, {"CMD": "SEND", "PAR": {"DATA": b"\x42\x80\x7f\x01\x01\x00\x45"}})
    )
    # print(sys.ask(act, {"CMD": "FREE", "DATA": b"\x42\x80\x7f\x0c\x00\x0c\x45"}))
    input("Press Enter to End\n")
    logger.info("!")


if __name__ == "__main__":
    _test()
