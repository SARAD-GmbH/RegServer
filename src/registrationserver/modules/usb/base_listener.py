"""Process listening for new connected SARAD instruments -- Windows implementation.

Created
    2021-05-17

Author
    Riccardo Foerster <rfoerster@sarad.de>

"""
import json

import polling2  # type: ignore
from registrationserver.config import config
from registrationserver.logger import logger
from registrationserver.modules.usb.usb_actor import UsbActor
from sarad.cluster import SaradCluster
from thespian.actors import ActorExitRequest, ActorSystem, Actor  # type: ignore


class BaseListener:
    # pylint: disable=too-few-public-methods
    """Process listening for new connected SARAD instruments
    -- base for OS specific implementations."""

    def __init__(self):
        native_ports = config.get("NATIVE_SERIAL_PORTS", [])
        ignore_ports = config.get("IGNORED_SERIAL_PORTS", [])
        self._cluster = SaradCluster(
            native_ports=native_ports, ignore_ports=ignore_ports
        )
        self._active_ports = set(self._cluster.active_ports)
        self._actors = {}

    def run(self):
        """Start listening for new devices"""
        native_ports = set(self._cluster.native_ports)
        if native_ports is not set():
            logger.info("Start polling RS-232 ports %s", native_ports)
            polling2.poll(
                lambda: self.update_native_ports(), step=60, poll_forever=True
            )

    def update_native_ports(self):
        """Check all RS-232 ports that are listed in the config
        for connected instruments. This function has to be called either by the app
        or by a polling routine."""
        native_ports = set(self._cluster.native_ports)
        active_ports = set(self._actors.keys())
        old_activ_native_ports = native_ports.intersection(active_ports)
        logger.debug("[Poll] Old active native ports: %s", old_activ_native_ports)
        system = ActorSystem()
        cluster = system.createActor(Actor, globalName="cluster")
        cluster_awnser = system.ask(cluster, {"CMD": "LIST-NATIVE"})
        new_instruments = cluster_awnser["RESULT"]["DATA"]

        for instrument in new_instruments:
            self._create_actor(instrument)
        current_active_ports = set(
            instr.port for instr in self._cluster.connected_instruments
        )
        current_active_native_ports = native_ports.intersection(current_active_ports)
        gone_ports = old_activ_native_ports.difference(current_active_native_ports)
        for gone_port in gone_ports:
            try:
                ActorSystem().ask(self._actors[gone_port], ActorExitRequest())
                del self._actors[gone_port]
            except KeyError:
                logger.error("%s removed, that never was added properly", gone_port)
                self._actors.pop(gone_port, None)
            try:
                assert current_active_ports == set(self._actors.keys())
            except AssertionError:
                logger.error(
                    "%s must be equal to %s",
                    current_active_ports,
                    set(self._actors.keys()),
                )

    def _create_actor(self, instrument):
        serial_device = instrument["Serial Device"]
        family = instrument["Family"]
        device_id = instrument["Device ID"]
        if family == 5:
            sarad_type = "sarad-dacm"
        elif family in [1, 2]:
            sarad_type = "sarad-1688"
        else:
            logger.error(
                "[Add Instrument]: unknown instrument family (index: %s)",
                family,
            )
            sarad_type = "unknown"
        global_name = f"{device_id}.{sarad_type}.local"
        logger.debug("Create actor %s", global_name)
        self._actors[serial_device] = ActorSystem().createActor(
            UsbActor, globalName=global_name
        )
        data = json.dumps(
            {
                "Identification": {
                    "Name": instrument["NAME"],
                    "Family": family,
                    "Type": instrument["Type"],
                    "Serial number": instrument["Serial number"],
                    "Host": "127.0.0.1",
                    "Protocol": sarad_type,
                },
                "Serial": serial_device,
            }
        )
        msg = {"CMD": "SETUP", "PAR": data}
        logger.info("Ask to setup device actor %s with msg %s", global_name, msg)
        ActorSystem().ask(self._actors[serial_device], msg)

    def _remove_actor(self, gone_port):
        if gone_port in self._actors:
            try:
                ActorSystem().ask(self._actors[gone_port], ActorExitRequest())
                self._actors.pop(gone_port, None)
            except KeyError:
                logger.error("%s removed, that never was added properly", gone_port)
        else:
            logger.error(
                "Tried to remove %s, that never was added properly.", gone_port
            )
