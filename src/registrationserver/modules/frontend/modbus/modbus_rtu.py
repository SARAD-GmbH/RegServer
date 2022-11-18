#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
 Example demonstrating the dynamic change of a value
 depending on the Modbus address and the usage of Hooks

 (C)2022 - Michael Strey - strey@sarad.de
 (C)2022 - SARAD GmbH - https://sarad.de

 This is distributed under GNU LGPL license, see license.txt
"""

import struct
import sys

import modbus_tk
import modbus_tk.defines as cst
from BitVector import BitVector  # type: ignore
from modbus_tk import hooks, modbus_rtu
from registrationserver.config import modbus_rtu_frontend_config
from serial import Serial  # type: ignore

SLAVE_ADDRESS = modbus_rtu_frontend_config["SLAVE_ADDRESS"]
PORT = modbus_rtu_frontend_config["PORT"]
BAUDRATE = modbus_rtu_frontend_config["BAUDRATE"]
PARITY = modbus_rtu_frontend_config["PARITY"]
STOPBITS = 1
TIMEOUT = 0.1
RETURN_VALUE = 13.2


def address_2_indexes(address):
    """Convert a Modbus start address into a trio of DACM indexes"""
    bv = BitVector(intVal=address, size=16)
    measurand_id = int(bv[0:3])
    sensor_id = int(bv[3:8])
    component_id = int(bv[8:15])
    return (component_id, sensor_id, measurand_id)


def main():
    """main"""
    logger = modbus_tk.utils.create_logger(name="console", record_format="%(message)s")

    def on_read_holding_registers_request(args):
        slave = args[0]
        request_pdu = args[1]
        (starting_address, quantity_of_x) = struct.unpack(">HH", request_pdu[1:5])
        logger.info("starting_address = %d", starting_address)
        component_id, sensor_id, measurand_id = address_2_indexes(starting_address)
        logger.info("DACM trio: %d/%d/%d", component_id, sensor_id, measurand_id)
        # Here we will have to hook in to get the value from instrument
        my_value = RETURN_VALUE
        my_bytes = struct.pack("!f", my_value)
        try:
            slave.set_values(
                "0",
                starting_address,
                [
                    int.from_bytes(my_bytes[2:4], "big"),
                    int.from_bytes(my_bytes[0:2], "big"),
                ],
            )
        except Exception as exception:
            logger.info(exception)

    hooks.install_hook(
        "modbus.Slave.handle_read_holding_registers_request",
        on_read_holding_registers_request,
    )

    # Create the server
    server = modbus_rtu.RtuServer(
        Serial(port=PORT, baudrate=BAUDRATE, parity=PARITY, stopbits=STOPBITS),
        error_on_missing_slave=False,
    )
    server.set_timeout(TIMEOUT)
    server.set_verbose(True)

    try:
        logger.info("running...")
        logger.info("enter 'quit' for closing the server")
        server.start()
        slave_1 = server.add_slave(SLAVE_ADDRESS)
        slave_1.add_block("0", cst.HOLDING_REGISTERS, 0, 65536)
        while True:
            cmd = sys.stdin.readline()
            args = cmd.split(" ")
            if cmd.find("quit") == 0:
                sys.stdout.write("bye-bye\r\n")
                break
            sys.stdout.write("unknown command %s\r\n" % (args[0]))
    finally:
        server.stop()


if __name__ == "__main__":
    main()
