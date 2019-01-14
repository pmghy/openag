import time, os, sys
from pyftdi.i2c import I2cController

# Set system path
sys.path.append(os.environ["OPENAG_BRAIN_ROOT"])

from device.utilities import bitwise

# Initialize i2c instance
i2c_controller = I2cController()
i2c_controller.configure("ftdi://ftdi:232h/1")
i2c = i2c_controller.get_port(0x15)

# Get status data bytes
i2c.write([0x04, 0x13, 0x8b, 0x00, 0x01])
bytes_ = i2c.read(4)

# Parse status data bytes
_, _, status_msb, status_lsb = bytes_
error_condition = bool(bitwise.get_bit_from_byte(0, status_lsb)),
flash_error = bool(bitwise.get_bit_from_byte(1, status_lsb)),
calibration_error = bool(bitwise.get_bit_from_byte(2, status_lsb)),
rs232 = bool(bitwise.get_bit_from_byte(0, status_msb)),
rs485 = bool(bitwise.get_bit_from_byte(1, status_msb)),
i2c_ = bool(bitwise.get_bit_from_byte(2, status_msb)),
warm_up_mode = bool(bitwise.get_bit_from_byte(3, status_msb)),
single_point_calibration = bool(bitwise.get_bit_from_byte(7, status_msb)),

# Print results
print("Error Condition: {}".format(bool(error_condition)))
print("Flash Error: {}".format(bool(flash_error)))
print("Calibration Error: {}".format(bool(calibration_error)))
print("RS232: {}".format(bool(rs232)))
print("RS485: {}".format(bool(rs485)))
print("I2C: {}".format(bool(i2c_)))
print("Warm Up Mode: {}".format(bool(warm_up_mode)))
print("Single Point Calibration: {}".format(bool(single_point_calibration)))
