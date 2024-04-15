"""Device Actor for a NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from dataclasses import replace
from datetime import timedelta

from hashids import Hashids  # type: ignore
from overrides import overrides
from regserver.actor_messages import (ActorType, KillMsg, SetDeviceStatusMsg,
                                      SetupUsbActorMsg)
from regserver.config import config
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from regserver.modules.backend.usb.zigbee_device_actor import ZigBeeDeviceActor
from sarad.mapping import id_family_mapping  # type: ignore
from sarad.sari import sarad_family  # type: ignore


class NetUsbActor(UsbActor):
    """Device Actor for a NetMonitors Coordinator"""

    @overrides
    def __init__(self):
        super().__init__()
        self.actor_type = ActorType.NODE
        self.channels = set()
        self.blocked = False

    @overrides
    def _setup(self, family_id=None, route=None):
        self.instrument = id_family_mapping.get(family_id)
        if self.instrument is None:
            logger.critical("Family %s not supported", family_id)
            self.is_connected = False
            return
        self.instrument.route = route
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
        logger.debug("NetMonitors Coordinator with Id %s detected.", self.my_id)
        # self.instrument.coordinator_reset()
        self.scan()
        self.wakeupAfter(timedelta(seconds=30), payload="scan")
        return

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        self.instrument.close_channel()
        return super()._kill_myself(register, resurrect)

    @overrides
    def receiveMsg_WakeupMessage(self, msg, _sender):
        super().receiveMsg_WakeupMessage(msg, _sender)
        if (msg.payload == "scan") and not self.blocked:
            self.scan()
        self.wakeupAfter(timedelta(seconds=30), payload="scan")

    @overrides
    def receiveMsg_ReserveDeviceMsg(self, msg, sender):
        self.blocked = True
        self._forward_to_children(msg)

    @overrides
    def receiveMsg_FreeDeviceMsg(self, msg, sender):
        self.blocked = False
        self._forward_to_children(msg)

    def scan(self):
        """Scan for instruments connected to this NetMonitors Coordinator"""
        logger.info("Rescan")
        known_channels = self.channels.copy()
        self.channels = self.instrument.scan()
        logger.debug("Instruments connected via ZigBee: %s", self.channels)
        new_channels = self.channels.difference(known_channels)
        gone_channels = known_channels.difference(self.channels)
        if gone_channels:
            logger.info("Instruments removed from ZigBee: %s", gone_channels)
            for frozen_channel in gone_channels:
                actor_id = self.get_actor_id(frozen_channel)
                logger.info("Kill actor %s on %s", actor_id, self.my_id)
                for child_id, child_actor in self.child_actors.items():
                    if child_id == actor_id:
                        self.send(child_actor["actor_address"], KillMsg())
        if new_channels:
            logger.info("New instruments connected via ZigBee: %s", new_channels)
            for frozen_channel in new_channels:
                actor_id = self.get_actor_id(frozen_channel)
                logger.info("Create actor %s on %s", actor_id, self.my_id)
                self._create_actor(ZigBeeDeviceActor, actor_id, None)
                channel = dict(frozen_channel)
                route_to_instr = replace(self.instrument.route)
                route_to_instr.zigbee_address = channel["short_address"]
                for child_id, child_actor in self.child_actors.items():
                    if child_id == actor_id:
                        child_actor["initialized"] = False
                        child_actor["route_to_instr"] = route_to_instr
                        child_actor["family_id"] = channel["family_id"]
        self.instrument.release_instrument()
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
        logger.info("%s for %s from %s", msg, self.my_id, sender)
        for _child_id, child_actor in self.child_actors.items():
            if child_actor["actor_address"] == sender:
                child_actor["initialized"] = True
        self.setup_one_child()

    def get_actor_id(self, frozen_channel):
        """Generate the actor_id from the channel information gained from
        NetMonitors Coordinator"""
        channel = dict(frozen_channel)
        family_id = channel["family_id"]
        instr_id = Hashids().encode(
            family_id,
            channel["device_type"],
            channel["serial_number"],
        )
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
        return f"{instr_id}.{sarad_type}.local"

    def receiveMsg_ReservationStatusMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Handle the ReservationStatusMsg from child ZigBeeDeviceActor"""
        logger.info("%s for %s from %s", msg, self.my_id, sender)
