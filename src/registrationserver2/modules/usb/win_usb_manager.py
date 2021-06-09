# Standard library imports
from overrides import overrides  # type: ignore

# library imports
from thespian.actors import Actor, ActorExitRequest, ChildActorExited, ActorSystem  # type: ignore

# Self imports
from registrationserver2.modules.messages import RETURN_MESSAGES
from registrationserver2.modules.usb.usb_actor import UsbActor
from registrationserver2 import logger


class WinUsbManager(Actor):
    """
    classdocs
    """

    ACCEPTED_COMMANDS = {"PROCESS_LIST": "_process_list"}

    ACCEPTED_RETURNS = {
        "SETUP": "_return_with_socket",
        "KILL": "_return_from_kill",
    }

    _port_list = {}
    _actors = {}

    @overrides
    def receiveMessage(self, msg, sender):
        """
        Handles received Actor messages / verification of the message format
        """
        logger.debug("Msg: %s, Sender: %s", msg, sender)
        if isinstance(msg, ActorExitRequest):
            self._kill(msg, sender)
            return
        if isinstance(msg, ChildActorExited):
            # TODO error handling code could be placed here
            return
        if not isinstance(msg, dict):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGTYPE"]["ERROR_MESSAGE"])
            return
        return_key = msg.get("RETURN", None)
        cmd_key = msg.get("CMD", None)
        if ((return_key is None) and (cmd_key is None)) or (
            (return_key is not None) and (cmd_key is not None)
        ):
            logger.critical(
                "Received %s from %s. This should never happen.", msg, sender
            )
            logger.critical(RETURN_MESSAGES["ILLEGAL_WRONGFORMAT"]["ERROR_MESSAGE"])
            return
        if cmd_key is not None:
            cmd_function = self.ACCEPTED_COMMANDS.get(cmd_key, None)
            if cmd_function is None:
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(
                    RETURN_MESSAGES["ILLEGAL_UNKNOWN_COMMAND"]["ERROR_MESSAGE"]
                )
                return
            if getattr(self, cmd_function, None) is None:
                logger.critical(
                    "Received %s from %s. This should never happen.", msg, sender
                )
                logger.critical(
                    RETURN_MESSAGES["ILLEGAL_NOTIMPLEMENTED"]["ERROR_MESSAGE"]
                )
                return
            getattr(self, cmd_function)(msg, sender)
        elif return_key is not None:
            return_function = self.ACCEPTED_RETURNS.get(return_key, None)
            if return_function is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            if getattr(self, return_function, None) is None:
                logger.debug("Ask received the return %s from %s.", msg, sender)
                return
            getattr(self, return_function)(msg, sender)

    # Message Handling
    def _process_list(self, msg: dict, sender):
        data_key = msg.get("DATA", None)
        if data_key is not None:
            return
        list_key = msg.get("LIST", None)
        if list_key is not None:
            return

        if not isinstance(list_key, list):
            return

        sys = ActorSystem()

        for current in list_key:
            if current in self._port_list:
                continue
            self._port_list[current.deviceid] = current
            self._actors[current.serial] = ActorSystem().createActor(
                UsbActor, globalName=f"{current.deviceid}.serial"
            )
            sys.tell(
                self._actors[current.serial],
                {"CMD": "SETUP", "DATA": {"PORT": current}},
            )

        remove = []

        for old in self._port_list:
            if old in list_key:
                continue
            remove.append(old.serial)
            sys.tell(self._actors[old.serial], {"CMD": "KILL"})

        for remove_item in remove:
            self._port_list.pop(remove_item)

    def _kill(self, msg: dict, sender):
        sys = ActorSystem()
        for actor in self._actors:
            sys.tell(actor, {"CMD": "KILL"})
        self._port_list = {}