"""Actor handling the creation and the setup of Host Actors of the LAN backend.
Forwards messages to setup Device Actors from the mDNS Listener to the Host Actors.

:Created:
    2025-05-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""

from overrides import overrides  # type: ignore
from regserver.actor_messages import (SetDeviceStatusMsg, SetupHostActorMsg,
                                      SetupLanDeviceMsg)
from regserver.base_actor import BaseActor
from regserver.config import config, lan_backend_config
from regserver.hostname_functions import compare_hostnames
from regserver.logger import logger
from regserver.modules.backend.mdns.host_actor import HostActor


class HostCreatorActor(BaseActor):
    """Class handling the creation of a host Actors."""

    @overrides
    def __init__(self):
        super().__init__()
        self.hosts_whitelist = lan_backend_config.get("HOSTS_WHITELIST", [])
        self.pending = {}

    @overrides
    def receiveMsg_SetupMsg(self, msg, sender):
        super().receiveMsg_SetupMsg(msg, sender)
        self._subscribe_to_actor_dict_msg()
        for host in self.hosts_whitelist:
            hostname = host[0]
            logger.debug("Tell Registrar to create Host Actor %s", hostname)
            self._create_actor(HostActor, hostname, self.myAddress)
            self.pending[hostname] = SetupLanDeviceMsg(
                host=hostname,
                port=host[1],
                scan_interval=lan_backend_config["SCAN_INTERVAL"],
                device_status={},
            )

    def receiveMsg_ActorCreatedMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Complete the setup of the HostActor."""
        setup_lan_device_msg = self.pending[msg.hostname]
        self.send(
            sender,
            SetupHostActorMsg(
                host=setup_lan_device_msg.host,
                port=setup_lan_device_msg.port,
                scan_interval=setup_lan_device_msg.scan_interval,
            ),
        )
        self.pending.pop(msg.hostname)

    def receiveMsg_SetupLanDeviceMsg(self, msg, _sender):
        # pylint: disable=invalid-name
        """Handle message comming from mDNS Listener. Trigger the creation of
        the HostActor if it doesn't exist. Trigger an existing HostActor to
        check for a new LAN device."""
        logger.debug("Create %s. Already existing: %s", msg.host, list(self.actor_dict))
        if msg.host in self.actor_dict:
            self.send(
                self.actor_dict[msg.host]["address"],
                SetDeviceStatusMsg(msg.device_status),
            )
            return
        # check blacklist
        my_hostname = config["MY_HOSTNAME"]
        hosts_blacklist = lan_backend_config.get("HOSTS_BLACKLIST", [])
        if (msg.host not in hosts_blacklist) and (
            not compare_hostnames(my_hostname, msg.host)
            and (msg.host not in self.pending)
        ):
            self._create_actor(HostActor, msg.host, self.myAddress)
            self.pending[msg.host] = msg
