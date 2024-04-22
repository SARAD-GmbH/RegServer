"""Device Actor for a NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from dataclasses import replace
from datetime import timedelta
from threading import Thread

from overrides import overrides
from regserver.actor_messages import (ActorType, KillMsg, SetDeviceStatusMsg,
                                      SetupUsbActorMsg)
from regserver.config import config
from regserver.helpers import decode_instr_id, short_id
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from regserver.modules.backend.usb.zigbee_device_actor import (
    COM_TIMEOUT, ZigBeeDeviceActor)
from sarad.mapping import id_family_mapping  # type: ignore
from sarad.sari import sarad_family  # type: ignore
from serial import SerialException  # type: ignore

# period in seconds to ask coordinator for updated instrument list
SCAN_INTERVAL = 15  # must be longer than COM_TIMEOUT


class NetUsbActor(UsbActor):
    """Device Actor for a NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.actor_type = ActorType.NODE
        self.blocked = False
        self.scan_thread = Thread(target=self.scan, daemon=True)
        self.close_channel_thread = Thread(target=self._close_channel, daemon=True)

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._subscribe_to_actor_dict_msg()

    @overrides
    def _setup(self, family_id=None, route=None):
        self.instrument = id_family_mapping.get(family_id)
        if self.instrument is None:
            logger.critical("Family %s not supported", family_id)
            self.is_connected = False
            return
        self.instrument.route = route
        self.instrument.COM_TIMEOUT = COM_TIMEOUT
        if family_id == 5:
            sarad_type = "sarad-dacm"
        elif family_id in [1, 2, 4]:
            sarad_type = "sarad-1688"
        device_status = {
            "Identification": {
                "Name": self.instrument.type_name,
                "Family": family_id,
                "Type": self.instrument.type_id,
                "Serial number": self.instrument.serial_number,
                "Firmware version": self.instrument.software_version,
                "Host": "127.0.0.1",
                "Protocol": sarad_type,
                "IS Id": config["IS_ID"],
            },
            "Serial": self.instrument.route.port,
            "State": 2,
        }
        self.receiveMsg_SetDeviceStatusMsg(SetDeviceStatusMsg(device_status), self)
        self._publish_status_change()
        logger.info("NetMonitors Coordinator with Id %s detected.", self.my_id)
        self.instrument.coordinator_reset()
        self.instrument.release_instrument()
        self.wakeupAfter(timedelta(seconds=SCAN_INTERVAL), payload="scan")
        return

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if not self.close_channel_thread.is_alive():
            self.close_channel_thread = Thread(target=self._close_channel, daemon=True)
            self.close_channel_thread.start()
        return super()._kill_myself(register, resurrect)

    def _close_channel(self):
        try:
            self.instrument.close_channel()
            self.instrument.release_instrument()
        except (SerialException, TypeError) as exception:
            logger.warning("%s during _close_channel from %s", exception, self.my_id)

    @overrides
    def receiveMsg_WakeupMessage(self, msg, _sender):
        super().receiveMsg_WakeupMessage(msg, _sender)
        if (msg.payload == "scan") and not self.blocked:
            if not self.scan_thread.is_alive():
                self.scan_thread = Thread(target=self.scan, daemon=True)
                self.scan_thread.start()
        self.wakeupAfter(timedelta(seconds=SCAN_INTERVAL), payload="scan")

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        self.blocked = True
        self._forward_to_children(msg)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        self.blocked = False
        self._forward_to_children(msg)

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        if not self.child_actors:
            self.blocked = False
        return super().receiveMsg_ChildActorExited(msg, sender)

    def scan(self):
        """Scan for instruments connected to this NetMonitors Coordinator"""
        logger.debug("Rescan")
        channels = self.instrument.scan()
        self.instrument.release_instrument()
        logger.debug("Instruments connected via ZigBee: %s", channels)
        new_channels = {}
        for instr_id, address in channels.items():
            actor_id = self.get_actor_id(instr_id)
            if self.child_actors.get(actor_id, False):
                old_zb_address = self.child_actors[actor_id][
                    "route_to_instr"
                ].zigbee_address
            else:
                old_zb_address = 0
            new_zb_address = channels[short_id(actor_id)]
            if actor_id not in self.child_actors:
                new_channels[actor_id] = address
            elif old_zb_address != new_zb_address:
                logger.warning(
                    "%s has changed its ZigBee address from %d to %d",
                    actor_id,
                    old_zb_address,
                    new_zb_address,
                )
                new_channels[actor_id] = address
        gone_channels = []
        for actor_id, info in self.child_actors.items():
            instr_id = short_id(actor_id)
            old_zb_address = info["route_to_instr"].zigbee_address
            if channels and channels.get(instr_id, False):
                new_zb_address = channels[instr_id]
            else:
                new_zb_address = old_zb_address
            if instr_id not in channels:
                gone_channels.append(actor_id)
            elif old_zb_address != new_zb_address:
                logger.warning(
                    "%s has changed its ZigBee address from %d to %d",
                    actor_id,
                    old_zb_address,
                    new_zb_address,
                )
                gone_channels.append(actor_id)
        if gone_channels:
            logger.info("Instruments removed from ZigBee: %s", gone_channels)
            for actor_id in gone_channels:
                logger.debug("Kill actor %s on %s", actor_id, self.my_id)
                self.send(self.child_actors[actor_id]["actor_address"], KillMsg())
        if new_channels:
            logger.info("New instruments connected via ZigBee: %s", new_channels)
            for actor_id, address in new_channels.items():
                instr_already_represented = False
                for existing_device_id in self.actor_dict:
                    if short_id(existing_device_id) == short_id(actor_id):
                        logger.info(
                            "%s is already represented by %s",
                            short_id(actor_id),
                            existing_device_id,
                        )
                        instr_already_represented = True
                        break
                if not instr_already_represented:
                    logger.debug("Create actor %s on %s", actor_id, self.my_id)
                    self._create_actor(ZigBeeDeviceActor, actor_id, None)
                    family_id = decode_instr_id(short_id(actor_id))[0]
                    route_to_instr = replace(self.instrument.route)
                    route_to_instr.zigbee_address = address
                    self.child_actors[actor_id]["initialized"] = False
                    self.child_actors[actor_id]["route_to_instr"] = route_to_instr
                    self.child_actors[actor_id]["family_id"] = family_id
        self.setup_one_child()

    def setup_one_child(self):
        """Go through the list of child Actors and initialize the first uninitialized Actor."""
        for _child_id, child_actor in self.child_actors.items():
            if not child_actor["initialized"]:
                self.send(
                    child_actor["actor_address"],
                    SetupUsbActorMsg(
                        child_actor["route_to_instr"],
                        sarad_family(child_actor["family_id"]),
                        False,
                    ),
                )
                return

    def receiveMsg_FinishSetupUsbActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """The initialization of one of the child actors was finished"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if msg.success:
            for child_id, child_actor in self.child_actors.items():
                if child_actor["actor_address"] == sender:
                    logger.info("%s initialized", child_id)
                    child_actor["initialized"] = True
        else:
            self.send(sender, KillMsg())
        self.setup_one_child()

    def get_actor_id(self, instr_id):
        """Generate the actor_id from the channel information gained from
        NetMonitors Coordinator"""
        family_id = decode_instr_id(instr_id)[0]
        if family_id == 5:
            sarad_type = "sarad-dacm"
        elif family_id in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "Add Instrument on %s: unknown instrument family (index: %s)",
                self.my_id,
                family_id,
            )
            sarad_type = "unknown"
        return f"{instr_id}.{sarad_type}.zigbee"

    def receiveMsg_ReservationStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle the ReservationStatusMsg from child ZigBeeDeviceActor"""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
