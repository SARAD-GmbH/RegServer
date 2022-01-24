"""Main actor of the Registration Server -- implementation for RFC 2217

:Created:
    2020-10-14

:Authors:
    | Riccardo Förster <foerster@sarad.de>,
    | Michael Strey <strey@sarad.de>

.. uml :: uml-rfc2217_actor.puml
"""

import serial.rfc2217  # type: ignore
from overrides import overrides  # type: ignore
from registrationserver.actor_messages import RxBinaryMsg
from registrationserver.logger import logger
from registrationserver.modules.device_actor import DeviceBaseActor
from registrationserver.shutdown import system_shutdown
from thespian.actors import ActorSystem  # type: ignore

logger.debug("%s -> %s", __package__, __file__)

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
        if self.device_status:
            address = self.device_status.get("Remote", {}).get("Address", None)
            port = self.device_status.get("Remote", {}).get("Port", None)
            if not address or not port:
                return False
            port_ident = fr"rfc2217://{address}:{port}"
        if port_ident and not (self.__port and self.__port.is_open):
            try:
                self.__port = serial.rfc2217.Serial(port_ident)
                # move the send ( test if connection is up and if not create)
            except Exception:  # pylint: disable=broad-except
                logger.critical(
                    "Fatal error connecting Instrument Server. System shutdown."
                )
                system_shutdown()
                return False
        if self.__port and self.__port.is_open:
            return True
        return False

    def receiveMsg_TxBinaryMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handler for TxBinaryMsg from App to Instrument."""
        if self._connect():
            logger.info("Actor %s received: %s", self.globalName, msg.data)
            self.__port.write(msg.data)
            logger.debug("and wrote it to serial.rfc2217.Serial")
            _return = b""
            while True:
                _return_part = (
                    self.__port.read_all() if self.__port.inWaiting() else b""
                )
                if _return_part != b"":
                    if chr(_return_part[-1]) == "E":
                        _return = _return + _return_part
                        break
                _return = _return + _return_part
            return_message = RxBinaryMsg(_return)
        else:
            return_message = RxBinaryMsg(b"")
        self.send(self.my_redirector, return_message)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        logger.debug("[FreeDeviceMsg]")
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        super().receiveMsg_FreeDeviceMsg(msg, sender)

    @overrides
    def receiveMsg_KillMsg(self, msg, sender):
        if self.__port is not None:
            if self.__port.isOpen():
                self.__port.close()
            self.__port = None
        super().receiveMsg_KillMsg(msg, sender)

    @overrides
    def _reserve_at_is(self):
        # pylint: disable=unused-argument, no-self-use
        """Reserve the requested instrument at the instrument server. This function has
        to be implemented (overridden) in the protocol specific modules.
        TODO: Read the reply from the REST API of the Instrument Server.
        In this dummy we suppose, that the instrument is always available for us.
        """
        self._forward_reservation(True)


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
