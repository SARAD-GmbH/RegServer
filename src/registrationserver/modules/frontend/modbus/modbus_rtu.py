""" Modbus RTU frontend module

Provides measuring values from a local DACM instrument via Modbus RTU.

:Created:
    2022-11-19

:Authors:
    | Michael Strey <strey@sarad.de>
"""

import struct
from datetime import timedelta

import modbus_tk.defines as cst  # type: ignore
from BitVector import BitVector  # type: ignore
from modbus_tk import hooks, modbus_rtu
from registrationserver.actor_messages import (GetRecentValueMsg,
                                               RecentValueMsg, Status)
from registrationserver.config import modbus_rtu_frontend_config
from registrationserver.helpers import (get_actor, get_device_status,
                                        transport_technology)
from registrationserver.logger import logger  # type: ignore
from registrationserver.restapi import check_msg
from registrationserver.shutdown import system_shutdown
from serial import Serial  # type: ignore
from thespian.actors import ActorSystem  # type: ignore

SLAVE_ADDRESS = modbus_rtu_frontend_config["SLAVE_ADDRESS"]
PORT = modbus_rtu_frontend_config["PORT"]
BAUDRATE = modbus_rtu_frontend_config["BAUDRATE"]
PARITY = modbus_rtu_frontend_config["PARITY"]
DEVICE_ID = modbus_rtu_frontend_config["DEVICE_ID"]
STOPBITS = 1
TIMEOUT = 0.1
RETURN_VALUE = 13.2
MAX_FLOAT = 3.4028235e38


class ModbusRtu:
    """Modbus RTU frontend

    Provides measuring values from a local DACM instrument via Modbus RTU.
    """

    @staticmethod
    def address_2_indexes(address):
        """Convert a Modbus start address into a trio of DACM indexes"""
        address_bits = BitVector(intVal=address, size=16)
        measurand_id = int(address_bits[0:3])
        sensor_id = int(address_bits[3:8])
        component_id = int(address_bits[8:15])
        return (component_id, sensor_id, measurand_id)

    def __init__(self, registrar_actor):
        # Create the server
        self.server = modbus_rtu.RtuServer(
            Serial(port=PORT, baudrate=BAUDRATE, parity=PARITY, stopbits=STOPBITS),
            error_on_missing_slave=False,
        )
        self.server.set_timeout(TIMEOUT)
        self.server.set_verbose(True)
        self.registrar = registrar_actor

    def start(self):
        """Start Modbus RTU server and handle Modbus requests"""

        def get_value(component_id, sensor_id, measurand_id):
            # Here we will have to hook in to get the value from instrument
            device_state = get_device_status(self.registrar, DEVICE_ID)
            if (
                (device_state == {})
                or (transport_technology(DEVICE_ID) not in ["local"])
                or ("sarad-dacm" not in DEVICE_ID)
            ):
                logger.error("Request only supported for local DACM instruments.")
                return MAX_FLOAT
            device_actor = get_actor(self.registrar, DEVICE_ID)
            with ActorSystem().private() as modbus_sys:
                try:
                    value_return = modbus_sys.ask(
                        device_actor,
                        GetRecentValueMsg(component_id, sensor_id, measurand_id),
                        timeout=timedelta(seconds=10),
                    )
                except ConnectionResetError:
                    logger.critical(
                        "No response from Actor System. -> Emergency shutdown"
                    )
                    system_shutdown()
                    return MAX_FLOAT
            reply_is_corrupted = check_msg(value_return, RecentValueMsg)
            if reply_is_corrupted:
                return MAX_FLOAT
            if value_return.status == Status.INDEX_ERROR:
                logger.error(
                    "The requested value is not available. %s", value_return.status
                )
                return MAX_FLOAT
            return value_return.value

        def on_read_holding_registers_request(args):
            slave = args[0]
            request_pdu = args[1]
            (starting_address, _quantity_of_x) = struct.unpack(">HH", request_pdu[1:5])
            logger.debug("starting_address = %d", starting_address)
            component_id, sensor_id, measurand_id = self.address_2_indexes(
                starting_address
            )
            logger.debug("DACM trio: %d/%d/%d", component_id, sensor_id, measurand_id)
            my_value = get_value(component_id, sensor_id, measurand_id)
            my_bytes = struct.pack("!f", my_value)
            slave.set_values(
                "0",
                starting_address,
                [
                    int.from_bytes(my_bytes[2:4], "big"),
                    int.from_bytes(my_bytes[0:2], "big"),
                ],
            )

        def on_error(_args):
            logger.critical("Emergency shutdown")
            system_shutdown()
            self.server.stop()

        hooks.install_hook(
            "modbus.Slave.handle_read_holding_registers_request",
            on_read_holding_registers_request,
        )
        hooks.install_hook("modbus_rtu.RtuServer.on_error", on_error)
        logger.info(
            "Modbus RTU frontend running at %d Bd, parity = %s", BAUDRATE, PARITY
        )
        self.server.start()
        slave_1 = self.server.add_slave(SLAVE_ADDRESS)
        slave_1.add_block("0", cst.HOLDING_REGISTERS, 0, 65536)

    def stop(self):
        """Stop Modbus RTU server"""
        self.server.stop()
        logger.info("Modbus RTU frontend stopped")
