from pymodbus.client import ModbusTcpClient
import struct
import time

# ==============================
# Waveshare
# ==============================
WAVESHARE_IP = "192.168.0.203"
WAVESHARE_PORT = 502

# ==============================
# Flow meter
# ==============================
SLAVE_ID = 1

# 40003 -> zero-based address 2
START_ADDRESS = 2


def decode_float(r1, r2):

    # AB - normal
    ab = struct.unpack(
        ">f",
        struct.pack(">HH", r1, r2)
    )[0]

    # BA - word swapped
    ba = struct.unpack(
        ">f",
        struct.pack(">HH", r2, r1)
    )[0]

    # Byte swapped
    r1_bs = ((r1 & 0xFF) << 8) | (r1 >> 8)
    r2_bs = ((r2 & 0xFF) << 8) | (r2 >> 8)

    byte_swap = struct.unpack(
        ">f",
        struct.pack(">HH", r1_bs, r2_bs)
    )[0]

    # Byte + word swapped
    both_swap = struct.unpack(
        ">f",
        struct.pack(">HH", r2_bs, r1_bs)
    )[0]

    return ab, ba, byte_swap, both_swap


client = ModbusTcpClient(
    WAVESHARE_IP,
    port=WAVESHARE_PORT,
    timeout=3
)

print("Connecting to Waveshare...")

if not client.connect():
    print("ERROR: Cannot connect to Waveshare")
    exit()

print("Connected.\n")

try:

    while True:

        # Read:
        #
        # 40003-40004 = Instantaneous flow
        # 40005-40006 = Instantaneous velocity
        # 40007-40008 = Sensor voltage
        #
        # Total = 6 registers

        result = client.read_holding_registers(
            address=START_ADDRESS,
            count=6,
            slave=SLAVE_ID
        )

        if result.isError():

            print("Modbus error:", result)

        else:

            regs = result.registers

            print("Raw registers:")
            print(regs)

            # ---------------------------------
            # Instantaneous Flow
            # 40003-40004
            # ---------------------------------

            flow = decode_float(
                regs[0],
                regs[1]
            )

            # ---------------------------------
            # Instantaneous Velocity
            # 40005-40006
            # ---------------------------------

            velocity = decode_float(
                regs[2],
                regs[3]
            )

            # ---------------------------------
            # Sensor Voltage
            # 40007-40008
            # ---------------------------------

            voltage = decode_float(
                regs[4],
                regs[5]
            )

            print("\nInstantaneous Flow")
            print("  AB       :", flow[0])
            print("  BA       :", flow[1])
            print("  Byte     :", flow[2])
            print("  Both     :", flow[3])

            print("\nInstantaneous Velocity")
            print("  AB       :", velocity[0])
            print("  BA       :", velocity[1])
            print("  Byte     :", velocity[2])
            print("  Both     :", velocity[3])

            print("\nSensor Voltage")
            print("  AB       :", voltage[0])
            print("  BA       :", voltage[1])
            print("  Byte     :", voltage[2])
            print("  Both     :", voltage[3])

            print("\n" + "=" * 60)

        time.sleep(1)

finally:

    client.close()
    print("Connection closed")