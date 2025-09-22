"""Main actor of the Registration Server -- implementation for local connection

:Created:
    2021-06-01

:Authors:
    | Michael Strey <strey@sarad.de>
    | Riccardo Förster <foerster@sarad.de>

"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Thread
from time import sleep

from overrides import overrides
from regserver.actor_messages import (ControlFunctionalityMsg, Frontend,
                                      MqttPublishMsg, RecentValueMsg,
                                      ReserveDeviceMsg, RxBinaryMsg,
                                      SetDeviceStatusMsg, SetRtcAckMsg, Status)
from regserver.config import (config, frontend_config, local_backend_config,
                              monitoring_config, mqtt_config, unique_id)
from regserver.helpers import short_id
from regserver.logger import logger
from regserver.modules.device_actor import DeviceBaseActor
from sarad.global_helpers import encode_instr_id  # type: ignore
from sarad.global_helpers import get_sarad_type
from sarad.instrument import Gps  # type: ignore
from sarad.mapping import id_family_mapping  # type: ignore
from sarad.sari import SaradInst  # type: ignore
from serial import SerialException  # type: ignore


class Purpose(Enum):
    """One item for every possible purpose the HTTP request is be made for."""

    WAKEUP = 2
    RESERVE = 3


@dataclass
class MonitoringState:
    """Object storing the current state of the monitoring mode.

    Args:
        monitoring_shall_be_active: True, if the monitoring mode was configured
                                    to be active.
        monitoring_active: True, if the monitoring mode currently is active.
        start_timestamp (int): Posix timestamp of the start datetime
    """

    monitoring_shall_be_active: bool
    monitoring_active: bool
    start_timestamp: int


@dataclass
class Parameter:
    """Object to store the attributes of a measuring parameter.

    Args:
        component (int): Component Id.
        sensor (int): Sensor Id.
        measurand (int): Measurand Id.
        interval (int): Interval in seconds used for fetching in monitoring mode.
    """

    component: int
    sensor: int
    measurand: int
    interval: int


class UsbActor(DeviceBaseActor):
    """Actor for dealing with direct serial connections via USB or RS-232"""

    @overrides
    def __init__(self):
        logger.debug("Initialize a new USB actor.")
        super().__init__()
        self.instrument: SaradInst = None
        self.is_connected: bool = True
        self.inner_thread: Thread = Thread(
            target=self._setup,
            kwargs={"family_id": None, "poll": False, "route": None},
            daemon=True,
        )
        self.mon_state = MonitoringState(
            monitoring_shall_be_active=False,
            monitoring_active=False,
            start_timestamp=0,
        )
        self._set_rtc_pending: bool = False
        self._missed_monitoring_values: list[Parameter] = []

    @staticmethod
    def _calc_next_wakeup(
        start: int, margin: int, interval: int, fetched: float
    ) -> float:
        """Calculate the time delay in seconds for the next wakupAfter in monitoring mode.

        Args:
            start (int): Start timestamp.
            margin (int): Security margin in seconds (typ. 2 s).
            interval (int): Time interval for fetching in seconds.
            fetched (float): Timestamp of now.
        """
        return (margin + start - fetched) % interval

    def _start_thread(self, thread):
        if not self.inner_thread.is_alive():
            self.inner_thread = thread
            self.inner_thread.start()
        else:
            logger.debug("Waiting for %s to finish...", self.inner_thread)
            self.wakeupAfter(timedelta(seconds=0.5), payload=thread)

    def _check_connection(self, purpose: Purpose = Purpose.WAKEUP):
        logger.debug("Check if %s is still connected", self.my_id)
        if self.instrument is not None:
            try:
                self.is_connected = self.instrument.get_description()
            except TypeError:
                logger.error("Cannot get instrument description of %s", self.my_id)
                self.is_connected = False
            finally:
                self.instrument.release_instrument()
        if purpose == Purpose.WAKEUP:
            self._finish_poll()
        elif purpose == Purpose.RESERVE:
            self._finish_reserve()

    def receiveMsg_SetupUsbActorMsg(self, msg, sender):
        # pylint: disable=invalid-name
        """Set the SaradInst object for serial communication."""
        logger.debug(
            "SetupUsbActorMsg(route=%s, family=%d) for %s from %s",
            msg.route,
            msg.family["family_id"],
            self.my_id,
            sender,
        )
        self._subscribe_to_actor_dict_msg()
        family_id = msg.family["family_id"]
        if msg.poll:
            self.wakeupAfter(local_backend_config["LOCAL_RETRY_INTERVAL"])
        self._start_thread(
            thread=Thread(
                target=self._setup,
                kwargs={"family_id": family_id, "route": msg.route},
                daemon=True,
            )
        )

    def _setup(self, family_id=None, route=None):
        self.instrument = id_family_mapping.get(family_id)
        if self.instrument is None:
            logger.critical("Family %s not supported", family_id)
            self.is_connected = False
            return
        self.instrument.route = route
        self.instrument.device_id = self.my_id
        device_status = {
            "Identification": {
                "Name": self.instrument.type_name,
                "Family": family_id,
                "Type": self.instrument.type_id,
                "Serial number": self.instrument.serial_number,
                "Firmware version": self.instrument.software_version,
                "Host": "127.0.0.1",
                "Protocol": get_sarad_type(self.instr_id),
            },
            "Serial": self.instrument.route.port,
            "State": 2,
        }
        self.receiveMsg_SetDeviceStatusMsg(SetDeviceStatusMsg(device_status), self)
        monitoring_conf = monitoring_config.get(self.instr_id, {})
        self.mon_state.monitoring_shall_be_active = monitoring_conf.get("active", False)
        if local_backend_config["SET_RTC"]:
            self._request_set_rtc_at_is(confirm=False, sender=self.myAddress)
        if self.mon_state.monitoring_shall_be_active:
            logger.debug("Monitoring mode for %s shall be active", self.instr_id)
            self._request_start_monitoring_at_is(confirm=False, sender=self.myAddress)
        self.instrument.release_instrument()
        logger.debug("Instrument with Id %s detected.", self.instr_id)
        return

    @overrides
    def receiveMsg_WakeupMessage(self, msg, sender):
        # pylint: disable=invalid-name, disable=too-many-branches
        """Handler for WakeupMessage"""
        # logger.debug("Wakeup %s, payload = %s", self.my_id, msg.payload)
        super().receiveMsg_WakeupMessage(msg, sender)
        if msg.payload is None:
            logger.debug("Check connection of %s", self.my_id)
            self.wakeupAfter(local_backend_config["LOCAL_RETRY_INTERVAL"])
            try:
                is_reserved = self.device_status["Reservation"]["Active"]
            except (KeyError, TypeError):
                is_reserved = False
            if (not self.on_kill) and (not is_reserved):
                if not self.inner_thread.is_alive():
                    logger.debug("Start check connection thread for %s", self.my_id)
                    self._start_thread(
                        Thread(
                            target=self._check_connection,
                            kwargs={
                                "purpose": Purpose.WAKEUP,
                            },
                            daemon=True,
                        )
                    )
        elif isinstance(msg.payload, Thread):
            self._start_thread(msg.payload)
        elif msg.payload == "start_monitoring":
            self._start_monitoring()
        elif msg.payload == "set_rtc":
            self._set_rtc()
        elif msg.payload == "resume_monitoring":
            logger.info("Check whether it's possible to resume the monitoring mode")
            if self.mon_state.monitoring_shall_be_active:
                if not self.mon_state.monitoring_active and not self._is_reserved():
                    logger.info("Resume monitoring mode at %s", self.my_id)
                    self.reserve_device_msg = ReserveDeviceMsg(
                        host="localhost", user="self", app="monitoring"
                    )
                    self._handle_reserve_reply_from_is(
                        success=Status.OK,
                        requester=self.myAddress,
                    )
                    self.mon_state.monitoring_active = True
                    for parameter in self._missed_monitoring_values:
                        logger.info(
                            "Fetch a missed value for %s on %s", parameter, self.my_id
                        )
                        self._start_thread(
                            Thread(
                                target=self._get_recent_value_for_monitoring,
                                kwargs={
                                    "parameter": parameter,
                                    "wakeup": False,
                                },
                                daemon=True,
                            ),
                        )
                    self._missed_monitoring_values = []
                else:
                    self.wakeupAfter(timedelta(seconds=10), "resume_monitoring")
        elif msg.payload == "request_set_rtc_at_is":
            self._request_set_rtc_at_is(sender=self.myAddress, confirm=False)

    def _finish_poll(self):
        """Finalize the handling of WakeupMessage for regular rescan"""
        if not self.is_connected and not self.on_kill:
            logger.info("Nothing connected -> Killing %s", self.my_id)
            self._kill_myself()
        elif self.instrument.family.get("family_id", False):
            instr_id = encode_instr_id(
                self.instrument.family["family_id"],
                self.instrument.type_id,
                self.instrument.serial_number,
            )
            old_instr_id = short_id(self.my_id)
            if instr_id != old_instr_id:
                logger.info(
                    "Instr_id was %s and now is %s -> Rescan",
                    old_instr_id,
                    instr_id,
                )
                self._kill_myself()

    def dummy_reply(self, data) -> bytes:
        """Filter TX message and give a dummy reply.

        This function was invented in order to prevent messages destined for
        the WLAN module to be sent to the instrument.
        """
        tx_rx = {b"B\x80\x7f\xe6\xe6\x00E": b"B\x80\x7f\xe7\xe7\x00E"}
        if data in tx_rx:
            logger.debug("Reply %s with %s", data, tx_rx[data])
            return tx_rx[data]
        return b""

    @overrides
    def _request_bin_at_is(self, data):
        logger.debug(data)
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved:
            dummy_reply = self.dummy_reply(data)
            if dummy_reply:
                self._handle_bin_reply_from_is(RxBinaryMsg(dummy_reply))
                return
            if not self.instrument.check_cmd(data):
                logger.error("Command %s from app is invalid", data)
                self._handle_bin_reply_from_is(RxBinaryMsg(b""))
                return
            emergency = False
            read_next = True
            while read_next:
                try:
                    start_time = datetime.now()
                    reply = self.instrument.get_message_payload(
                        data, timeout=self.instrument.ext_ser_timeout
                    )
                    stop_time = datetime.now()
                except (SerialException, OSError, TypeError) as exception:
                    logger.error(
                        "Connection to %s lost: %s", self.instrument, exception
                    )
                    emergency = True
                if emergency:
                    logger.info("Killing myself")
                    self._kill_myself()
                    return
                logger.debug("Instrument replied %s", reply)
                if reply["is_valid"]:
                    self._handle_bin_reply_from_is(RxBinaryMsg(reply["standard_frame"]))
                    read_next = not reply["is_last_frame"]
                    data = b""
                    continue
                logger.warning(
                    "Invalid binary message from %s after %s: %s",
                    self.my_id,
                    stop_time - start_time,
                    reply,
                )
                logger.error(
                    "Timeout in %s on binary command %s",
                    self.my_id,
                    data,
                )
                self._handle_bin_reply_from_is(RxBinaryMsg(self.RET_TIMEOUT))
                return

    @overrides
    def _request_reserve_at_is(self, sender):
        """Reserve the requested instrument.

        To avoid wrong reservations of instruments like DOSEman sitting on an
        IR cradle that might stay connected to USB or instruments connected via
        RS-232, we have to double-check the availability of the instrument.

        """
        if self._set_rtc_pending:
            self.reserve_device_msg = ReserveDeviceMsg(
                host="localhost", user="self", app="set-rtc"
            )
            self._handle_reserve_reply_from_is(
                success=Status.OCCUPIED,
                requester=sender,
            )
            return
        try:
            is_reserved = self.device_status["Reservation"]["Active"]
        except (KeyError, TypeError):
            is_reserved = False
        if not is_reserved:
            self._start_thread(
                Thread(
                    target=self._check_connection,
                    kwargs={
                        "purpose": Purpose.RESERVE,
                    },
                    daemon=True,
                )
            )
        else:
            self._finish_reserve()

    def _finish_reserve(self):
        """Forward the reservation state from the Instrument Server to the REST API."""
        logger.debug("_finish_reserve")
        if not self.is_connected:
            success = Status.NOT_FOUND
        else:
            success = Status.OK
        self._handle_reserve_reply_from_is(
            success=success,
            requester=self.request_locks["Reserve"].request.sender,
        )
        if (success == Status.NOT_FOUND) and not self.on_kill:
            logger.info("Killing myself")
            self._kill_myself()

    @overrides
    def _request_free_at_is(self, sender):
        """Free the instrument

        The USB Actor is already the last in the chain. There is no need to ask
        somebody else to free the instrument.
        """
        self.instrument.release_instrument()
        self._handle_free_reply_from_is(
            success=Status.OK,
            requester=sender,
        )
        if self.mon_state.monitoring_shall_be_active:
            if self.mon_state.monitoring_active:
                self._stop_monitoring()
                self.wakeupAfter(timedelta(seconds=10), "resume_monitoring")
                logger.info("Suspend monitoring mode at %s", self.my_id)
                self.mon_state.monitoring_active = False

    @overrides
    def _request_set_rtc_at_is(self, sender, confirm=False):
        if self.instrument.family["family_id"] == 2:
            logger.debug("Features of %s: %s", self.my_id, self.instrument.features)
            rtc_set_seconds = self.instrument.features.get("rtc_set_seconds", False)
        else:
            rtc_set_seconds = True
        status = Status.OK
        if rtc_set_seconds:
            wait = 0
            if not self._set_rtc():
                status = Status.ERROR
        else:
            self._set_rtc_pending = True
            wait = 60 - datetime.now().time().second
            self.wakeupAfter(timedelta(seconds=wait), "set_rtc")
        logger.debug("Wait %d seconds before setting the RTC of %s", wait, self.my_id)
        utc_offset = self.instrument.utc_offset
        self._handle_set_rtc_reply_from_is(
            answer=SetRtcAckMsg(
                instr_id=self.instr_id,
                status=status,
                utc_offset=utc_offset,
                wait=wait,
            ),
            requester=sender,
            confirm=confirm,
        )
        if local_backend_config["SET_RTC"]:
            self.wakeupAfter(timedelta(days=7), "request_set_rtc_at_is")

    def _set_rtc(self) -> bool:
        success: bool = self.instrument.set_real_time_clock(
            local_backend_config["UTC_OFFSET"]
        )
        if not success:
            logger.warning("Error in set RTC on %s. I will try it again.", self.my_id)
            sleep(0.5)
            success = self.instrument.set_real_time_clock(
                local_backend_config["UTC_OFFSET"]
            )
            if not success:
                logger.error("Permanent error in set RTC on %s", self.my_id)
        self.instrument.release_instrument()
        self._set_rtc_pending = False
        return success

    def _check_monitoring_config(self) -> bool:
        """Check correctness of configuration. Return True, if correct."""
        config_tuples = []
        try:
            monitoring_conf = monitoring_config[self.instr_id]
            for value in monitoring_conf.get("values", []):
                config_tuples.append(
                    (value["component"], value["sensor"], value["measurand"])
                )
                _interval = value["interval"]
        except (KeyError, TypeError) as exception:
            logger.error(
                "Uncomplete [monitoring] section in 'config.toml': %s", exception
            )
            return False
        instr_tuples = []
        for component, c_obj in self.instrument.components.items():
            for sensor, s_obj in c_obj.sensors.items():
                for measurand in s_obj.measurands:
                    instr_tuples.append((component, sensor, measurand))
        for config_tuple in config_tuples:
            if config_tuple not in instr_tuples:
                logger.error(
                    "Config tuple %s not in instr_tuples %s", config_tuple, instr_tuples
                )
                return False
        return True

    @overrides
    def _request_start_monitoring_at_is(self, sender, start_time=None, confirm=False):
        super()._request_start_monitoring_at_is(
            sender=sender, start_time=start_time, confirm=confirm
        )
        if not start_time:
            start_time = datetime.now(timezone.utc)
        self.reserve_device_msg = ReserveDeviceMsg(
            host="localhost", user="self", app="monitoring"
        )
        self._handle_reserve_reply_from_is(
            success=Status.OK,
            requester=self.myAddress,
        )
        if Frontend.MQTT not in frontend_config:
            self.send(
                self.registrar,
                ControlFunctionalityMsg(actor_id="mqtt_scheduler", on=True),
            )
        if self._check_monitoring_config():
            status = Status.OK
        else:
            status = Status.INDEX_ERROR
        offset = max(start_time - datetime.now(timezone.utc), timedelta(0))
        self._handle_start_monitoring_reply_from_is(
            status=status,
            requester=self.request_locks["StartMonitoring"].request.sender,
            confirm=confirm,
            offset=offset,
        )
        if status == Status.OK:
            monitoring_conf = monitoring_config[self.instr_id]
            if monitoring_conf.get("active", False):
                self.mon_state.monitoring_shall_be_active = True
            else:
                self.mon_state.monitoring_shall_be_active = False
            if offset > timedelta(0):
                logger.info("Monitoring Mode will be started in %s", offset)
                self.wakeupAfter(offset, payload="start_monitoring")
            else:
                logger.info("Monitoring Mode will be started now")
                self._start_monitoring()
        else:
            logger.error(
                "Cannot start monitoring mode because of error in 'config.toml'"
            )
            self.mon_state.monitoring_shall_be_active = False
            self._request_free_at_is(sender=sender)

    @overrides
    def _request_stop_monitoring_at_is(self, sender):
        super()._request_stop_monitoring_at_is(sender)
        self.mon_state.monitoring_shall_be_active = False
        has_reservation_section = self.device_status.get("Reservation", False)
        if has_reservation_section:
            is_reserved = self.device_status["Reservation"].get("Active", False)
        else:
            is_reserved = False
        if is_reserved and self.mon_state.monitoring_active:
            self._stop_monitoring()
            self._request_free_at_is(sender)
            status = Status.OK
        else:
            status = Status.OK_SKIPPED
        self._handle_stop_monitoring_reply_from_is(
            status=status,
            requester=self.request_locks["StopMonitoring"].request.sender,
        )

    def _start_monitoring(self):
        self._start_thread(
            Thread(
                target=self._start_monitoring_function,
                daemon=True,
            )
        )

    def _stop_monitoring(self):
        self.mon_state.monitoring_active = False
        self._publish_monitoring_stopped()
        if (
            Frontend.MQTT not in frontend_config
        ) and not self.mon_state.monitoring_shall_be_active:
            self.send(
                self.registrar,
                ControlFunctionalityMsg(actor_id="mqtt_scheduler", on=False),
            )

    def _start_monitoring_function(self):
        monitoring_conf = monitoring_config.get(self.instr_id, {})
        self.instrument.set_real_time_clock(local_backend_config["UTC_OFFSET"])
        cycle = monitoring_conf.get("cycle", 0)
        if cycle:
            success = False
            try:
                success = self.instrument.start_cycle(cycle)
                logger.info(
                    "Device %s started with cycle %d",
                    self.instrument.device_id,
                    cycle,
                )
                sleep(3)  # DACM needs some time to wakeup from standby
            except Exception as exception:  # pylint: disable=broad-except
                logger.error(
                    "Failed to start cycle on %s. Exception: %s",
                    self.my_id,
                    exception,
                )
            finally:
                self.instrument.release_instrument()
            if not success:
                logger.error("Start/Stop not supported by %s", self.my_id)
        else:
            logger.error("Error in config.toml. Cycle not configured.")
            self.mon_state.monitoring_active = False
            self._request_free_at_is(self.myAddress)
            return
        self.mon_state.monitoring_active = True
        self.mon_state.start_timestamp = int(
            datetime.now(timezone.utc).replace(microsecond=0).timestamp()
        )
        logger.info("Monitoring mode started at %s", self.my_id)
        self._publish_instr_meta()
        for value in monitoring_conf.get("values", []):
            parameter = Parameter(
                component=value.get("component", 0),
                sensor=value.get("sensor", 0),
                measurand=value.get("measurand", 0),
                interval=value.get("interval", 0),
            )
            self._get_meta_data(
                parameter.component, parameter.sensor, parameter.measurand
            )
            if parameter.interval and self.mon_state.monitoring_active:
                self.wakeupAfter(
                    timedelta(seconds=parameter.interval + 2),
                    Thread(
                        target=self._get_recent_value_for_monitoring,
                        kwargs={
                            "parameter": parameter,
                            "wakeup": True,
                        },
                        daemon=True,
                    ),
                )

    def _publish_value(
        self,
        answer: RecentValueMsg,
        component: int,
        sensor: int,
        measurand: int,
    ):
        """Publish a value via MqttScheduler.

        This is part of the Monitoring Mode functionality.

        """

        qos = mqtt_config["QOS"]
        group = mqtt_config["GROUP"]
        client_id = unique_id(config["IS_ID"])
        topic = f"{group}/{client_id}/{self.instr_id}/{component}/{sensor}/{measurand}/value"
        timestamp = int(answer.timestamp)
        if component == 255:
            if answer.gps and answer.gps.valid:
                gps = answer.gps
                valid = 1
                payload = (
                    f"{valid},{gps.latitude},{gps.longitude},{gps.altitude},"
                    + f"{gps.deviation},{timestamp}"
                )
            else:
                valid = 0
                payload = f"{valid}"
        else:
            payload = f"{answer.operator},{answer.value},{timestamp}"
        if self.actor_dict.get("mqtt_scheduler", False):
            self.send(
                self.actor_dict["mqtt_scheduler"]["address"],
                MqttPublishMsg(topic=topic, payload=payload, qos=qos, retain=False),
            )

    def _publish_instr_meta(self):
        """Publish meta data for Monitoring Mode via MqttScheduler.

        This is part of the Monitoring Mode functionality.

        """

        qos = mqtt_config["QOS"]
        group = mqtt_config["GROUP"]
        client_id = unique_id(config["IS_ID"])
        topic = f"{group}/{client_id}/{self.instr_id}/meta"
        payload = {
            "State": 2,
            "start_timestamp": self.mon_state.start_timestamp,
            "monitoring_active": self.mon_state.monitoring_active,
        }
        if self.actor_dict.get("mqtt_scheduler", False):
            self.send(
                self.actor_dict["mqtt_scheduler"]["address"],
                MqttPublishMsg(
                    topic=topic, payload=json.dumps(payload), qos=qos, retain=False
                ),
            )

    def _publish_meta(
        self,
        answer: RecentValueMsg,
        component: int,
        sensor: int,
        measurand: int,
    ):
        """Publish meta data for Monitoring Mode via MqttScheduler.

        This is part of the Monitoring Mode functionality.

        """

        qos = mqtt_config["QOS"]
        group = mqtt_config["GROUP"]
        client_id = unique_id(config["IS_ID"])
        topic = (
            f"{group}/{client_id}/{self.instr_id}/{component}/{sensor}/{measurand}/meta"
        )
        payload = {
            "component_name": answer.component_name,
            "sensor_name": answer.sensor_name,
            "measurand_name": answer.measurand_name,
            "unit": answer.unit,
            "interval": answer.sample_interval,
        }
        if self.actor_dict.get("mqtt_scheduler", False):
            self.send(
                self.actor_dict["mqtt_scheduler"]["address"],
                MqttPublishMsg(
                    topic=topic, payload=json.dumps(payload), qos=qos, retain=True
                ),
            )

    def _publish_monitoring_stopped(self):
        """Publish meta data for the stop of Monitoring Mode via MqttScheduler.

        This is part of the Monitoring Mode functionality.

        """

        qos = mqtt_config["QOS"]
        group = mqtt_config["GROUP"]
        client_id = unique_id(config["IS_ID"])
        topic = f"{group}/{client_id}/{self.instr_id}/meta"
        payload = {
            "State": 2,
            "start_timestamp": self.mon_state.start_timestamp,
            "stop_timestamp": int(
                datetime.now(timezone.utc).replace(microsecond=0).timestamp()
            ),
            "monitoring_active": self.mon_state.monitoring_active,
        }
        if self.actor_dict.get("mqtt_scheduler", False):
            self.send(
                self.actor_dict["mqtt_scheduler"]["address"],
                MqttPublishMsg(
                    topic=topic, payload=json.dumps(payload), qos=qos, retain=False
                ),
            )

    @overrides
    def _request_recent_value_at_is(self, msg, sender):
        super()._request_recent_value_at_is(msg, sender)
        answer = self._get_recent_value_inner(msg.component, msg.sensor, msg.measurand)
        self._handle_recent_value_reply_from_is(
            answer=answer,
            requester=self.request_locks["GetRecentValue"].request.sender,
        )

    def _get_recent_value_for_monitoring(self, parameter: Parameter, wakeup: bool):
        next_wakeup = self._calc_next_wakeup(
            start=self.mon_state.start_timestamp,
            margin=2,
            interval=parameter.interval,
            fetched=datetime.now(timezone.utc).timestamp(),
        )
        logger.info("Next wakeup in %f s", next_wakeup)
        if wakeup:
            self.wakeupAfter(
                timedelta(seconds=next_wakeup),
                Thread(
                    target=self._get_recent_value_for_monitoring,
                    kwargs={
                        "parameter": parameter,
                        "wakeup": True,
                    },
                    daemon=True,
                ),
            )
        if self.mon_state.monitoring_active:
            answer = self._get_recent_value_inner(
                parameter.component, parameter.sensor, parameter.measurand
            )
            if answer.status == Status.CRITICAL:
                logger.error("Connection lost to %s", self.my_id)
                self._kill_myself()
                return
            self._publish_value(
                answer, parameter.component, parameter.sensor, parameter.measurand
            )
        else:
            parameter_is_already_listed = False
            for missed_parameter in self._missed_monitoring_values:
                if (
                    parameter.component == missed_parameter.component
                    and parameter.sensor == missed_parameter.sensor
                    and parameter.measurand == missed_parameter.measurand
                ):
                    logger.warning(
                        "We have lost at least one value of %s on %s",
                        parameter,
                        self.my_id,
                    )
                    parameter_is_already_listed = True
            if not parameter_is_already_listed:
                self._missed_monitoring_values.append(parameter)

    def _get_meta_data(self, component, sensor, measurand):
        answer = self._get_recent_value_inner(component, sensor, measurand)
        if answer.status == Status.CRITICAL:
            logger.error("Connection lost to %s in _get_meta_data", self.my_id)
            self._kill_myself()
            return
        self._publish_meta(answer, component, sensor, measurand)

    def _get_recent_value_inner(
        self, component: int, sensor: int, measurand: int
    ) -> RecentValueMsg:
        if component == 255:
            gps = self.instrument.geopos
            if not gps.valid and not gps.timestamp:
                logger.info("Initialize instrument position from config.toml")
                if config["LATITUDE"] or config["LONGITUDE"]:
                    gps = Gps(
                        valid=True,
                        timestamp=int(datetime.now(timezone.utc).timestamp()),
                        latitude=config["LATITUDE"],
                        longitude=config["LONGITUDE"],
                        altitude=config["ALTITUDE"],
                        deviation=0,
                    )
                    self.instrument.geopos = gps
            c_obj = self.instrument.components[component]
            s_obj = c_obj.sensors.get(sensor, False)
            if not s_obj:
                return RecentValueMsg(status=Status.INDEX_ERROR, instr_id=self.instr_id)
            m_obj = s_obj.measurands.get(measurand, False)
            if not m_obj:
                return RecentValueMsg(status=Status.INDEX_ERROR, instr_id=self.instr_id)
            return RecentValueMsg(
                status=Status.OK,
                instr_id=self.instr_id,
                component_name=c_obj.name,
                sensor_name=s_obj.name,
                measurand_name=m_obj.name,
                measurand="",
                operator="",
                value=0,
                unit="",
                timestamp=gps.timestamp,
                utc_offset=self.instrument.utc_offset,
                sample_interval=0,
                gps=gps,
            )
        try:
            reply = self.instrument.get_recent_value(component, sensor, measurand)
        except (IndexError, AttributeError) as exception:
            logger.error("Error in _get_recent_value_inner: %s", exception)
            return RecentValueMsg(status=Status.INDEX_ERROR, instr_id=self.instr_id)
        finally:
            self.instrument.release_instrument()
        logger.debug(
            "get_recent_value(%d, %d, %d) came back with %s",
            component,
            sensor,
            measurand,
            reply,
        )
        if reply:
            if not reply["gps"].valid:
                if config["LATITUDE"] or config["LONGITUDE"]:
                    gps = Gps(
                        valid=True,
                        timestamp=reply["datetime"].timestamp(),
                        latitude=config["LATITUDE"],
                        longitude=config["LONGITUDE"],
                        altitude=config["ALTITUDE"],
                        deviation=0,
                    )
                    self.instrument.geopos = gps
                else:
                    gps = Gps(valid=False)
            else:
                gps = reply["gps"]
            try:
                timestamp = reply["datetime"].timestamp()
            except OSError:
                logger.error(
                    "%s delivered %s as datetime. Cannot convert to timestamp.",
                    self.my_id,
                    reply["datetime"],
                )
                timestamp = 0
            return RecentValueMsg(
                status=Status.OK,
                instr_id=self.instr_id,
                component_name=reply["component_name"],
                sensor_name=reply["sensor_name"],
                measurand_name=reply["measurand_name"],
                measurand=reply["measurand"],
                operator=reply["measurand_operator"],
                value=reply["value"],
                unit=reply["measurand_unit"],
                timestamp=timestamp,
                utc_offset=self.instrument.utc_offset,
                sample_interval=reply["sample_interval"].total_seconds(),
                gps=gps,
            )
        return RecentValueMsg(
            status=Status.CRITICAL,
            instr_id=self.instr_id,
        )

    @overrides
    def receiveMsg_ChildActorExited(self, msg, sender):
        super().receiveMsg_ChildActorExited(msg, sender)

    @overrides
    def _kill_myself(self, register=True, resurrect=False):
        if self.mon_state.monitoring_active:
            self._stop_monitoring()
        try:
            self.instrument.release_instrument()
        except AttributeError:
            logger.warning("The USB Actor to be killed wasn't initialized properly.")
        super()._kill_myself(register=register)


if __name__ == "__main__":
    pass
