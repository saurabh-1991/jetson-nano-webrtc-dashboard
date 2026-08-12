# import struct
# import sys
# from datetime import datetime
# from pymodbus.client import ModbusTcpClient
# from pymodbus import FramerType


# GATEWAY_IP = "192.168.0.200"
# GATEWAY_PORT = 502
# SLAVE_ID = 1
# TIMEOUT_S = 3

# CHANNELS = {
#     1: {
#         "address": 0x0009,
#         "count": 3,
#         "reference_rtu": "01 03 00 09 00 03 D5 C9"
#     },
#     2: {
#         "address": 0x000C,
#         "count": 3,
#         "reference_rtu": "01 03 00 0C 00 03 C5 C8"
#     },
#     3: {
#         "address": 0x000F,
#         "count": 3,
#         "reference_rtu": "01 03 00 0F 00 03 35 C8"
#     },
# }


# def crc16_modbus(data: bytes) -> int:
#     crc = 0xFFFF

#     for byte in data:
#         crc ^= byte

#         for _ in range(8):
#             if crc & 0x0001:
#                 crc = (crc >> 1) ^ 0xA001
#             else:
#                 crc >>= 1

#     return crc


# def to_hex(data: bytes) -> str:
#     return " ".join(f"{value:02X}" for value in data)


# def make_tcp_request(transaction_id, slave_id, address, count):
#     pdu = struct.pack(">BHH", 0x03, address, count)
#     mbap = struct.pack(">HHHB", transaction_id, 0x0000, len(pdu) + 1, slave_id)
#     return mbap + pdu


# def make_rtu_request(slave_id, address, count):
#     request_without_crc = struct.pack(">BBHH", slave_id, 0x03, address, count)
#     crc = crc16_modbus(request_without_crc)
#     return request_without_crc + struct.pack("<H", crc)


# def make_tcp_response(transaction_id, slave_id, registers):
#     data = b"".join(struct.pack(">H", register) for register in registers)
#     pdu = struct.pack(">BB", 0x03, len(data)) + data
#     mbap = struct.pack(">HHHB", transaction_id, 0x0000, len(pdu) + 1, slave_id)
#     return mbap + pdu


# def print_channel_result(client, channel_number, cfg, transaction_id):
#     address = cfg["address"]
#     count = cfg["count"]

#     tcp_tx = make_tcp_request(
#         transaction_id,
#         SLAVE_ID,
#         address,
#         count
#     )

#     rtu_tx = make_rtu_request(
#         SLAVE_ID,
#         address,
#         count
#     )

#     print("-" * 82)
#     print(f"CHANNEL {channel_number}")
#     print(f"Timestamp                  : {datetime.now().isoformat(timespec='seconds')}")
#     print(f"Modbus TCP TX frame        : {to_hex(tcp_tx)}")
#     print(f"Expected RS485 RTU TX frame: {to_hex(rtu_tx)}")
#     print(f"Supplier RTU reference     : {cfg['reference_rtu']}")

#     # 'slave' is correct for the installed PyModbus version.
#     response = client.read_holding_registers(
#         address=address,
#         count=count,
#         slave=SLAVE_ID
#     )

#     if response.isError():
#         print(f"Modbus response            : {response}")
#         print("RESULT                     : FAIL")
#         return False

#     registers = response.registers
#     tcp_rx = make_tcp_response(
#         transaction_id,
#         SLAVE_ID,
#         registers
#     )

#     print(f"Modbus TCP RX frame        : {to_hex(tcp_rx)}")
#     print(f"Received registers (hex)   : {[f'0x{x:04X}' for x in registers]}")
#     print(f"Received registers (decimal): {registers}")
#     print("RESULT                     : PASS")
#     return True


# def main():
#     print("=" * 82)
#     print("THERMOCOUPLE LOGGER MODBUS TCP-TO-RTU COMMUNICATION TEST")
#     print(f"Gateway: {GATEWAY_IP}:{GATEWAY_PORT} | Logger slave ID: {SLAVE_ID}")
#     print("=" * 82)

#     client = ModbusTcpClient(
#         host=GATEWAY_IP,
#         port=GATEWAY_PORT,
#         timeout=TIMEOUT_S,
#         framer=FramerType.SOCKET
#     )

#     try:
#         if not client.connect():
#             print(f"FAIL: Cannot connect to {GATEWAY_IP}:{GATEWAY_PORT}")
#             sys.exit(1)

#         print("PASS: Connected to Waveshare gateway.")

#         results = []

#         for transaction_id, (channel_number, cfg) in enumerate(CHANNELS.items(), start=1):
#             passed = print_channel_result(
#                 client,
#                 channel_number,
#                 cfg,
#                 transaction_id
#             )
#             results.append(passed)

#         print("-" * 82)
#         print(f"TEST SUMMARY: {sum(results)}/{len(results)} channels responded successfully.")

#         sys.exit(0 if all(results) else 2)

#     except Exception as exc:
#         print(f"FAIL: {type(exc).__name__}: {exc}")
#         sys.exit(1)

#     finally:
#         client.close()


# if __name__ == "__main__":
#     main()

import struct
import sys
from datetime import datetime

from pymodbus.client import ModbusTcpClient
from pymodbus import FramerType


# ============================================================
# CONFIGURATION
# ============================================================

GATEWAY_IP = "192.168.0.200"
GATEWAY_PORT = 502

SLAVE_ID = 1
TIMEOUT_S = 10
RETRIES = 3

# Test one channel first.
# Set to None to test all channels.
TEST_ONLY_CHANNEL = None

CHANNELS = {
    1: {
        "address": 0x0009,
        "count": 3,
        "reference_rtu": "01 03 00 09 00 03 D5 C9",
    },

    2: {
        "address": 0x000C,
        "count": 3,
        "reference_rtu": "01 03 00 0C 00 03 C5 C8",
    },

    3: {
        "address": 0x000F,
        "count": 3,
        "reference_rtu": "01 03 00 0F 00 03 35 C8",
    },
}


# ============================================================
# MODBUS CRC16
# ============================================================

def crc16_modbus(data: bytes) -> int:
    """
    Standard Modbus RTU CRC16.

    Returns CRC as a 16-bit integer.

    IMPORTANT:
    Modbus transmits CRC LOW BYTE first.
    Therefore struct.pack("<H", crc) is used later.
    """

    crc = 0xFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc


# ============================================================
# HEX UTILITIES
# ============================================================

def to_hex(data: bytes) -> str:
    return " ".join(f"{value:02X}" for value in data)


def hex_to_bytes(text: str) -> bytes:
    return bytes.fromhex(text)


# ============================================================
# CREATE MODBUS TCP REQUEST
# ============================================================

def make_tcp_request(
    transaction_id: int,
    slave_id: int,
    address: int,
    count: int,
) -> bytes:

    # Modbus Function 03 = Read Holding Registers
    pdu = struct.pack(
        ">BHH",
        0x03,
        address,
        count,
    )

    # MBAP Header
    mbap = struct.pack(
        ">HHHB",
        transaction_id,
        0x0000,          # Protocol ID
        len(pdu) + 1,    # PDU length + Unit ID
        slave_id,
    )

    return mbap + pdu


# ============================================================
# CREATE MODBUS RTU REQUEST
# ============================================================

def make_rtu_request(
    slave_id: int,
    address: int,
    count: int,
) -> bytes:

    request_without_crc = struct.pack(
        ">BBHH",
        slave_id,
        0x03,
        address,
        count,
    )

    crc = crc16_modbus(request_without_crc)

    # Modbus RTU CRC is transmitted LOW BYTE first.
    return request_without_crc + struct.pack("<H", crc)


# ============================================================
# CREATE EXPECTED TCP RESPONSE
# ============================================================

def make_tcp_response(
    transaction_id: int,
    slave_id: int,
    registers: list[int],
) -> bytes:

    data = b"".join(
        struct.pack(">H", register)
        for register in registers
    )

    pdu = struct.pack(
        ">BB",
        0x03,
        len(data),
    ) + data

    mbap = struct.pack(
        ">HHHB",
        transaction_id,
        0x0000,
        len(pdu) + 1,
        slave_id,
    )

    return mbap + pdu


# ============================================================
# CRC DIAGNOSTIC
# ============================================================

def print_crc_diagnostic(cfg):
    """
    Compare:

    1. Supplier reference
    2. CRC calculated by Python
    3. Actual RTU frame that Python generates
    """

    address = cfg["address"]
    count = cfg["count"]

    request_without_crc = struct.pack(
        ">BBHH",
        SLAVE_ID,
        0x03,
        address,
        count,
    )

    crc = crc16_modbus(request_without_crc)

    generated_rtu = request_without_crc + struct.pack(
        "<H",
        crc,
    )

    supplier_rtu = hex_to_bytes(
        cfg["reference_rtu"]
    )

    print()
    print("CRC DIAGNOSTIC")
    print("-" * 82)

    print(
        f"Request without CRC       : "
        f"{to_hex(request_without_crc)}"
    )

    print(
        f"Calculated CRC integer     : "
        f"0x{crc:04X}"
    )

    print(
        f"Calculated CRC bytes       : "
        f"{to_hex(struct.pack('<H', crc))}"
    )

    print(
        f"Python generated RTU frame : "
        f"{to_hex(generated_rtu)}"
    )

    print(
        f"Supplier RTU reference     : "
        f"{to_hex(supplier_rtu)}"
    )

    if generated_rtu == supplier_rtu:
        print(
            "CRC CHECK                  : PASS - "
            "Python frame matches supplier reference"
        )
    else:
        print(
            "CRC CHECK                  : WARNING"
        )

        print(
            "Supplier reference does NOT match "
            "standard Modbus CRC byte ordering."
        )

        print(
            "For standard Modbus RTU, the Python-generated "
            "frame should be used."
        )

    print("-" * 82)


# ============================================================
# PRINT TCP FRAME BREAKDOWN
# ============================================================

def print_tcp_breakdown(tcp_tx: bytes):

    if len(tcp_tx) < 12:
        return

    transaction_id = int.from_bytes(
        tcp_tx[0:2],
        byteorder="big",
    )

    protocol_id = int.from_bytes(
        tcp_tx[2:4],
        byteorder="big",
    )

    length = int.from_bytes(
        tcp_tx[4:6],
        byteorder="big",
    )

    slave_id = tcp_tx[6]
    function = tcp_tx[7]

    address = int.from_bytes(
        tcp_tx[8:10],
        byteorder="big",
    )

    count = int.from_bytes(
        tcp_tx[10:12],
        byteorder="big",
    )

    print()
    print("MODBUS TCP BREAKDOWN")
    print("-" * 82)

    print(f"Transaction ID             : {transaction_id}")
    print(f"Protocol ID                : 0x{protocol_id:04X}")
    print(f"Length                     : {length}")
    print(f"Slave / Unit ID            : {slave_id}")
    print(f"Function                   : 0x{function:02X}")
    print(f"Starting address           : 0x{address:04X} ({address})")
    print(f"Register count             : {count}")

    print("-" * 82)


# ============================================================
# PRINT RESPONSE INFORMATION
# ============================================================

def print_registers(registers):

    print()
    print("REGISTER DATA")
    print("-" * 82)

    for index, value in enumerate(registers):

        print(
            f"Register {index + 1}: "
            f"HEX=0x{value:04X} "
            f"DEC={value}"
        )

    print("-" * 82)


# ============================================================
# TEST ONE CHANNEL
# ============================================================

def print_channel_result(
    client,
    channel_number,
    cfg,
    transaction_id,
):

    address = cfg["address"]
    count = cfg["count"]

    print()
    print("=" * 82)
    print(f"CHANNEL {channel_number}")
    print("=" * 82)

    print(
        f"Timestamp                  : "
        f"{datetime.now().isoformat(timespec='seconds')}"
    )

    # --------------------------------------------------------
    # Generate frames
    # --------------------------------------------------------

    tcp_tx = make_tcp_request(
        transaction_id,
        SLAVE_ID,
        address,
        count,
    )

    rtu_tx = make_rtu_request(
        SLAVE_ID,
        address,
        count,
    )

    print()
    print("TRANSMIT FRAMES")
    print("-" * 82)

    print(
        f"Modbus TCP TX frame        : "
        f"{to_hex(tcp_tx)}"
    )

    print(
        f"Actual RS485 RTU TX frame  : "
        f"{to_hex(rtu_tx)}"
    )

    print(
        f"Supplier RTU reference     : "
        f"{cfg['reference_rtu']}"
    )

    print_tcp_breakdown(tcp_tx)

    # --------------------------------------------------------
    # CRC diagnostic
    # --------------------------------------------------------

    print_crc_diagnostic(cfg)

    # --------------------------------------------------------
    # Send request
    # --------------------------------------------------------

    print()
    print("SENDING MODBUS REQUEST...")
    print("-" * 82)

    try:

        response = client.read_holding_registers(
            address=address,
            count=count,
            slave=SLAVE_ID,
        )

    except Exception as exc:

        print()
        print("COMMUNICATION EXCEPTION")
        print("-" * 82)

        print(f"Exception type             : {type(exc).__name__}")
        print(f"Exception message          : {exc}")

        print()
        print("LIKELY FAILURE LOCATION")
        print("-" * 82)

        print("Python PC")
        print("   │")
        print("   │ Modbus TCP")
        print("   ▼")
        print("Waveshare Ethernet")
        print("   │")
        print("   │ Modbus RTU")
        print("   ▼")
        print("Data Logger")
        print("   │")
        print("   ▼")
        print("Thermocouple")

        print()
        print("No Modbus response was received.")

        return False

    # --------------------------------------------------------
    # Check Modbus error response
    # --------------------------------------------------------

    if response.isError():

        print()
        print("MODBUS ERROR RESPONSE")
        print("-" * 82)

        print(f"Response                   : {response}")

        print()
        print(
            "IMPORTANT: The logger/gateway DID respond, "
            "but returned a Modbus error."
        )

        print("RESULT                     : FAIL")

        return False

    # --------------------------------------------------------
    # Successful response
    # --------------------------------------------------------

    registers = response.registers

    tcp_rx = make_tcp_response(
        transaction_id,
        SLAVE_ID,
        registers,
    )

    print()
    print("RESPONSE RECEIVED")
    print("-" * 82)

    print(
        f"Modbus TCP RX frame        : "
        f"{to_hex(tcp_rx)}"
    )

    print(
        f"Received registers (hex)   : "
        f"{[f'0x{x:04X}' for x in registers]}"
    )

    print(
        f"Received registers (decimal): "
        f"{registers}"
    )

    print_registers(registers)

    print("RESULT                     : PASS")

    return True


# ============================================================
# CONNECTION TEST
# ============================================================

def test_connection(client):

    print()
    print("NETWORK CONNECTION TEST")
    print("-" * 82)

    print(
        f"Connecting to              : "
        f"{GATEWAY_IP}:{GATEWAY_PORT}"
    )

    try:

        connected = client.connect()

    except Exception as exc:

        print(
            f"Connection exception      : "
            f"{type(exc).__name__}: {exc}"
        )

        return False

    if not connected:

        print(
            f"FAIL: Cannot connect to "
            f"{GATEWAY_IP}:{GATEWAY_PORT}"
        )

        return False

    print("PASS: TCP connection established.")

    return True


# ============================================================
# PRINT CONFIGURATION CHECKLIST
# ============================================================

def print_configuration_checklist():

    print()
    print("=" * 82)
    print("WAVESHARE / DATA LOGGER CHECKLIST")
    print("=" * 82)

    print()
    print("Verify these settings before debugging Python:")
    print()

    print("[1] WAVESHARE NETWORK")
    print(f"    IP address              : {GATEWAY_IP}")
    print(f"    TCP port                : {GATEWAY_PORT}")
    print("    TCP server              : ENABLED")

    print()
    print("[2] WAVESHARE PROTOCOL")
    print("    Conversion              : Modbus TCP <--> RTU")

    print()
    print("[3] WAVESHARE RS485-1")
    print("    Baud rate               : MUST MATCH LOGGER")
    print("    Data bits               : MUST MATCH LOGGER")
    print("    Parity                  : MUST MATCH LOGGER")
    print("    Stop bits               : MUST MATCH LOGGER")

    print()
    print("[4] RS485 WIRING")
    print("    Logger A+               -> Waveshare A")
    print("    Logger B-               -> Waveshare B")

    print()
    print("[5] DATA LOGGER")
    print(f"    Modbus Slave ID         : {SLAVE_ID}")
    print("    Function                : 03")
    print("    Logger must support     : Modbus RTU")

    print()
    print("=" * 82)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 82)
    print("THERMOCOUPLE LOGGER")
    print("MODBUS TCP -> WAVESHARE -> RS485 RTU TEST")
    print("=" * 82)

    print(
        f"Gateway                   : "
        f"{GATEWAY_IP}:{GATEWAY_PORT}"
    )

    print(
        f"Logger Slave ID           : "
        f"{SLAVE_ID}"
    )

    print(
        f"Timeout                   : "
        f"{TIMEOUT_S} seconds"
    )

    print(
        f"Retries                   : "
        f"{RETRIES}"
    )

    print_configuration_checklist()

    # --------------------------------------------------------
    # Select channels
    # --------------------------------------------------------

    if TEST_ONLY_CHANNEL is None:

        channels_to_test = CHANNELS.items()

    else:

        if TEST_ONLY_CHANNEL not in CHANNELS:

            print(
                f"ERROR: Channel "
                f"{TEST_ONLY_CHANNEL} does not exist."
            )

            sys.exit(1)

        channels_to_test = [
            (
                TEST_ONLY_CHANNEL,
                CHANNELS[TEST_ONLY_CHANNEL],
            )
        ]

    # --------------------------------------------------------
    # Create Modbus TCP client
    # --------------------------------------------------------

    client = ModbusTcpClient(
        host=GATEWAY_IP,
        port=GATEWAY_PORT,
        timeout=TIMEOUT_S,
        retries=RETRIES,
        framer=FramerType.SOCKET,
    )

    results = []

    try:

        # ----------------------------------------------------
        # Ethernet test
        # ----------------------------------------------------

        if not test_connection(client):

            print()
            print("RESULT: FAIL - TCP connection problem.")

            sys.exit(1)

        print()

        # ----------------------------------------------------
        # Modbus test
        # ----------------------------------------------------

        for transaction_id, (channel_number, cfg) in enumerate(
            channels_to_test,
            start=1,
        ):

            passed = print_channel_result(
                client,
                channel_number,
                cfg,
                transaction_id,
            )

            results.append(passed)

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        print()
        print("=" * 82)
        print("TEST SUMMARY")
        print("=" * 82)

        passed_count = sum(results)
        total_count = len(results)

        print(
            f"Channels passed           : "
            f"{passed_count}/{total_count}"
        )

        if all(results):

            print()
            print("OVERALL RESULT             : PASS")

        else:

            print()
            print("OVERALL RESULT             : FAIL")

            print()
            print("NEXT THINGS TO CHECK:")
            print("1. Waveshare = Modbus TCP <--> RTU")
            print("2. RS485 baud rate")
            print("3. RS485 parity")
            print("4. RS485 stop bits")
            print("5. Logger Slave ID")
            print("6. A/B wiring")
            print("7. Logger is powered and responding")
            print("8. Supplier RTU CRC reference")

        sys.exit(0 if all(results) else 2)

    except KeyboardInterrupt:

        print()
        print("Test interrupted by user.")

        sys.exit(130)

    except Exception as exc:

        print()
        print("=" * 82)
        print("UNEXPECTED ERROR")
        print("=" * 82)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        sys.exit(1)

    finally:

        client.close()

        print()
        print("TCP connection closed.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()