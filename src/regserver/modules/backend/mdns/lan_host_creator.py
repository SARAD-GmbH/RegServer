"""Actor handling the creation and the setup of Host Actors of the LAN backend.
Forwards messages to setup Device Actors from the mDNS Listener to the Host Actors.

:Created:
    2025-05-14

:Authors:
    | Michael Strey <strey@sarad.de>

"""

from datetime import timedelta

from overrides import overrides  # type: ignore
from regserver.actor_messages import (ActorType, SetDeviceStatusMsg,
                                      SetupHostActorMsg, SetupLanDeviceMsg)
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

    @overrides
    def receiveMsg_UpdateActorDictMsg(self, msg, sender):
        super().receiveMsg_UpdateActorDictMsg(msg, sender)
        for hostname in msg.actor_dict:
            if msg.actor_dict[hostname]["actor_type"] == ActorType.HOST:
                if hostname in self.pending:
                    setup_lan_device_msg = self.pending[hostname]
                    self.send(
                        msg.actor_dict[hostname]["address"],
                        SetupHostActorMsg(
                            host=setup_lan_device_msg.host,
                            port=setup_lan_device_msg.port,
                            scan_interval=setup_lan_device_msg.scan_interval,
                        ),
                    )
                    self.send(
                        self.actor_dict[hostname]["address"],
                        SetDeviceStatusMsg(setup_lan_device_msg.device_status),
                    )
                    self.pending.pop(hostname)
                    logger.debug("%s created and setup", hostname)

    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name
        """Handler for WakeupMessage to re-send the SetupLanDeviceMsg to myself."""
        logger.debug("%s for %s from %s", msg, self.my_id, sender)
        if isinstance(msg, SetupLanDeviceMsg):
            self.receiveMessage(msg, self)

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
        if msg.host in self.pending:
            # wait a bit and try again
            self.wakeupAfter(timedelta(seconds=0.5), payload=msg)
            return
        # check blacklist
        my_hostname = config["MY_HOSTNAME"]
        hosts_blacklist = lan_backend_config.get("HOSTS_BLACKLIST", [])
        if (msg.host not in hosts_blacklist) and (
            not compare_hostnames(my_hostname, msg.host)
        ):
            self._create_actor(HostActor, msg.host, self.myAddress)
            self.pending[msg.host] = msg
