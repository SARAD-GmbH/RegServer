"""Device Actor for a NetMonitors Coordinator

:Created:
    2024-04-09

:Author:
    | Michael Strey <strey@sarad.de>

"""

from overrides import overrides
from regserver.actor_messages import (ActorType, SetDeviceStatusMsg,
                                      SetupUsbActorMsg)
from regserver.config import config
from regserver.logger import logger
from regserver.modules.backend.usb.usb_actor import UsbActor
from sarad.mapping import id_family_mapping  # type: ignore
from sarad.network import NetworkInst  # type: ignore
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
        if family_id == 4:
            family_class = NetworkInst
        else:
            logger.critical("Family %s not supported", family_id)
            self.is_connected = False
            return
        self.instrument = family_class()
        self.instrument.route = route
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
                if family_id == 3:
                    family_id = 5
                if sarad_family(family_id) is None:
                    logger.error("Family %d not defined in instruments.yaml", family_id)
                    continue
                instrument = SaradInst(family=sarad_family(family_id))
                instrument.route = route_to_instr
                instrument.release_instrument()
                self._create_and_setup_actor(instrument)
        return

    def _create_and_setup_actor(self, instrument):
        logger.info("[_create_and_setup_actor] on %s", self.my_id)
        try:
            family = instrument.family["family_id"]
        except AttributeError:
            logger.error("_create_and_setup_called but instrument is %s", instrument)
            return
        instr_id = instrument.device_id
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "Add Instrument on %s: unknown instrument family (index: %s)",
                self.my_id,
                family,
            )
            sarad_type = "unknown"
        actor_id = f"{instr_id}.{sarad_type}.local"
        logger.debug("Create actor %s on %s", actor_id, self.my_id)
        device_actor = self._create_actor(UsbActor, actor_id, None)
        device_status = {
            "Identification": {
                "Name": instrument.type_name,
                "Family": family,
                "Type": instrument.type_id,
                "Serial number": instrument.serial_number,
                "Firmware version": instrument.software_version,
                "Host": "127.0.0.1",
                "Protocol": sarad_type,
                "IS Id": config["IS_ID"],
            },
            "Serial": instrument.route.port,
            "State": 2,
        }
        logger.debug("Setup device actor %s with %s", actor_id, device_status)
        self.send(device_actor, SetDeviceStatusMsg(device_status))
        self.send(
            device_actor,
            SetupUsbActorMsg(
                instrument.route,
                instrument.family,
                False,
            ),
        )
