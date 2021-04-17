"""Main actor of the Registration Server -- implementation for RFC 2217

Created
    2020-10-14

Authors
    Riccardo Förster <foerster@sarad.de>,
    Michael Strey <strey@sarad.de>

.. uml :: uml-rfc2217_actor.puml
"""
import time

import serial.rfc2217  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver2 import logger
from registrationserver2.modules.device_base_actor import DeviceBaseActor
from registrationserver2.modules.messages import RETURN_MESSAGES
from thespian.actors import ActorSystem  # type: ignore

logger.info("%s -> %s", __package__, __file__)

CMD_CYCLE_TIMEOUT = 1


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
        if self.df_content:
            address = self.df_content.get("Remote", {}).get("Address", None)
            port = self.df_content.get("Remote", {}).get("Port", None)
            if not address or not port:
                return RETURN_MESSAGES.get("ILLEGAL_STATE")
            port_ident = fr"rfc2217://{address}:{port}"
        if port_ident and not (self.__port and self.__port.is_open):
            try:
                self.__port = serial.rfc2217.Serial(port_ident)
                # move the send ( test if connection is up and if not create)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Fatal error")
        if self.__port and self.__port.is_open:
            return True
        return False

    def _send(self, msg: dict, _sender) -> None:
        if self._connect():
            data = msg["PAR"]["DATA"]
            logger.info("Actor %s received: %s", self.globalName, data)
            self.__port.write(data)
            logger.debug("and wrote it to serial.rfc2217.Serial")
            _return = b""
            perf_time_0 = time.perf_counter()
            while True:
                _return_part = (
                    self.__port.read_all() if self.__port.inWaiting() else b""
                )
                if _return_part != b"":
                    if chr(_return_part[-1]) == "E":
                        _return = _return + _return_part
                        break
                _return = _return + _return_part
                perf_time_1 = time.perf_counter()
                if perf_time_1 - perf_time_0 > CMD_CYCLE_TIMEOUT:
                    logger.debug("Timeout receiving a reply. Retrying...")
                    # TODO This is an ugly workaround for a problem that's
                    # most probably between the Instrument Server and the instrument.
                    self.send(self.myAddress, msg)
                    break
            return_message = {
                "RETURN": "SEND",
                "ERROR_CODE": RETURN_MESSAGES["OK"]["ERROR_CODE"],
                "RESULT": {"DATA": _return},
            }
            self.send(self.my_redirector, return_message)
            return
        return_message = {
            "RETURN": "SEND",
            "ERROR_CODE": RETURN_MESSAGES["ILLEGAL_STATE"]["ERROR_CODE"],
        }
        self.send(self.my_redirector, return_message)
        return

    @overrides
    def _free(self, msg: dict, sender):
        logger.debug("Start to cleanup RFC2217")
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        super()._free(msg, sender)

    @overrides
    def _kill(self, msg: dict, sender):
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        super()._kill(msg, sender)

    @overrides
    def _reserve_at_is(self, app, host, user) -> bool:
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules."""
        return True


def _test():
    act = ActorSystem().createActor(
        Rfc2217Actor, globalName="0ghMF8Y.sarad-1688._rfc2217._tcp.local."
    )
    ActorSystem().ask(act, {"CMD": "SETUP"})
    print(
        ActorSystem().ask(
            act, {"CMD": "SEND", "PAR": {"DATA": b"\x42\x80\x7f\x01\x01\x00\x45"}}
        )
    )
    # print(sys.ask(act, {"CMD": "FREE", "DATA": b"\x42\x80\x7f\x0c\x00\x0c\x45"}))
    input("Press Enter to End\n")
    logger.info("!")


if __name__ == "__main__":
    _test()
