"""Device Actor for a NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from hashids import Hashids  # type: ignore
from overrides import overrides
from regserver.actor_messages import (ActorType, SetDeviceStatusMsg,
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
        self.channels = []

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
        self.channels = self.instrument.scan()
        self.instrument.release_instrument()
        logger.debug("NetMonitors Coordinator with Id %s detected.", self.my_id)
        if self.channels:
            logger.info("Instruments connected via ZigBee: %s", self.channels)
            for channel in self.channels:
                route_to_instr = route
                route_to_instr.zigbee_address = channel["short_address"]
                logger.info(route_to_instr)
                family_id = channel["family_id"]
                if family_id == 3:  # Workaround for bug in endpoint firmware
                    family_id = 5
                if sarad_family(family_id) is None:
                    logger.error("Family %d not defined in instruments.yaml", family_id)
                    continue
                instrument = id_family_mapping[family_id]
                instrument.route = route_to_instr
                family_dict = instrument.family
                hid = Hashids()
                instr_id = hid.encode(
                    family_id,
                    instrument.type_id,
                    instrument.serial_number,
                )
                instrument.release_instrument()
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
                actor_id = f"{instr_id}.{sarad_type}.local"
                logger.debug("Create actor %s on %s", actor_id, self.my_id)
                device_actor = self._create_actor(ZigBeeDeviceActor, actor_id, None)
                self.send(
                    device_actor,
                    SetupUsbActorMsg(
                        route_to_instr,
                        family_dict,
                        False,
                    ),
                )
        return

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        self.instrument.close_channel()
        return super()._kill_myself(register, resurrect)
