from pymodbus.client import ModbusTcpClient
import time

WAVESHARE_IP = "192.168.0.200"
WAVESHARE_PORT = 502

VFD1 = 1
VFD2 = 2

# Delta MS300 Modbus registers
REG_COMMAND = 0x2000
REG_FREQUENCY = 0x2001

REG_ERROR_STATUS = 0x2100
REG_OPERATION_STATUS = 0x2101
REG_OUTPUT_FREQUENCY = 0x2103


class DeltaMS300:

    def __init__(self, slave_id):
        self.slave_id = slave_id
        self.client = ModbusTcpClient(
            WAVESHARE_IP,
            port=WAVESHARE_PORT,
            timeout=3
        )

    def connect(self):
        if self.client.connect():
            print(f"VFD {self.slave_id}: Connected")
            return True

        print(f"VFD {self.slave_id}: Connection failed")
        return False

    def close(self):
        self.client.close()

    def set_frequency(self, hz):
        """
        MS300 frequency command:
        3000 = 30.00 Hz
        5000 = 50.00 Hz
        """

        value = int(hz * 100)

        result = self.client.write_register(
            address=REG_FREQUENCY,
            value=value,
            slave=self.slave_id
        )

        if result.isError():
            print(f"VFD {self.slave_id}: Frequency write failed")
            return False

        print(f"VFD {self.slave_id}: Frequency = {hz:.2f} Hz")
        return True

    def start(self):
        """
        0x0012:
        bit 1~0 = 10 -> RUN
        bit 5~4 = 01 -> Forward
        """

        command = 0x0012

        result = self.client.write_register(
            address=REG_COMMAND,
            value=command,
            slave=self.slave_id
        )

        if result.isError():
            print(f"VFD {self.slave_id}: START failed")
            return False

        print(f"VFD {self.slave_id}: START")
        return True

    def stop(self):
        """
        0x0001:
        bit 1~0 = 01 -> STOP
        """

        command = 0x0001

        result = self.client.write_register(
            address=REG_COMMAND,
            value=command,
            slave=self.slave_id
        )

        if result.isError():
            print(f"VFD {self.slave_id}: STOP failed")
            return False

        print(f"VFD {self.slave_id}: STOP")
        return True

    def read_status(self):

        result = self.client.read_holding_registers(
            address=REG_OPERATION_STATUS,
            count=1,
            slave=self.slave_id
        )

        if result.isError():
            print(f"VFD {self.slave_id}: Status read failed")
            return None

        status = result.registers[0]

        print(
            f"VFD {self.slave_id}: "
            f"Status = 0x{status:04X}"
        )

        return status

    def read_output_frequency(self):

        result = self.client.read_holding_registers(
            address=REG_OUTPUT_FREQUENCY,
            count=1,
            slave=self.slave_id
        )

        if result.isError():
            print(
                f"VFD {self.slave_id}: "
                f"Frequency read failed"
            )
            return None

        frequency = result.registers[0] / 100.0

        print(
            f"VFD {self.slave_id}: "
            f"Output frequency = {frequency:.2f} Hz"
        )

        return frequency


if __name__ == "__main__":

    vfd1 = DeltaMS300(VFD1)
    vfd2 = DeltaMS300(VFD2)

    try:

        if not vfd1.connect():
            exit(1)

        if not vfd2.connect():
            exit(1)

        # First test: READ ONLY
        vfd1.read_status()
        vfd2.read_status()

        vfd1.read_output_frequency()
        vfd2.read_output_frequency()

        # Don't start motors until communication is verified.

    finally:

        vfd1.close()
        vfd2.close()