import socket
import struct
from datetime import datetime


GATEWAY_IP = "192.168.0.200"
GATEWAY_PORT = 502

SLAVE_ID = 1
TRANSACTION_ID = 1

ADDRESS = 0x0009
COUNT = 5

TIMEOUT = 10.0  # seconds


def to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def make_modbus_tcp_request():
    """
    Creates:

    00 01 00 00 00 06 01 03 00 09 00 03
    """

    pdu = struct.pack(
        ">BHH",
        0x03,       # Function 03
        ADDRESS,
        COUNT,
    )

    mbap = struct.pack(
        ">HHHB",
        TRANSACTION_ID,
        0x0000,     # Protocol ID
        len(pdu) + 1,
        SLAVE_ID,
    )

    return mbap + pdu


def main():

    print("=" * 80)
    print("RAW MODBUS TCP TEST")
    print("=" * 80)

    request = make_modbus_tcp_request()

    print()
    print("Timestamp :", datetime.now().isoformat(timespec="seconds"))

    print()
    print("Destination:")
    print(f"  IP      : {GATEWAY_IP}")
    print(f"  Port    : {GATEWAY_PORT}")

    print()
    print("TCP TX:")
    print(to_hex(request))

    print()
    print("Expected:")
    print("00 01 00 00 00 06 01 03 00 09 00 03")

    print()
    print("Connecting...")

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    sock.settimeout(TIMEOUT)

    try:

        sock.connect(
            (GATEWAY_IP, GATEWAY_PORT)
        )

        print("TCP CONNECT             : PASS")

        print()
        print("Sending Modbus TCP frame...")

        sock.sendall(request)

        print("TCP SEND                : PASS")

        print()
        print("Waiting for gateway response...")

        response = sock.recv(1024)

        if not response:

            print()
            print("TCP RECEIVE             : EMPTY")
            print()
            print("The Waveshare accepted the TCP")
            print("connection but returned ZERO bytes.")

            return

        print()
        print("TCP RX                  : PASS")
        print()
        print("Raw response:")
        print(to_hex(response))

        print()
        print("Response length:")
        print(len(response), "bytes")

        # --------------------------------------------------
        # Decode MBAP
        # --------------------------------------------------

        if len(response) >= 8:

            transaction_id = int.from_bytes(
                response[0:2],
                "big",
            )

            protocol_id = int.from_bytes(
                response[2:4],
                "big",
            )

            length = int.from_bytes(
                response[4:6],
                "big",
            )

            unit_id = response[6]
            function = response[7]

            print()
            print("MODBUS TCP RESPONSE")
            print("-" * 80)

            print(
                f"Transaction ID : {transaction_id}"
            )

            print(
                f"Protocol ID    : {protocol_id}"
            )

            print(
                f"Length         : {length}"
            )

            print(
                f"Unit ID        : {unit_id}"
            )

            print(
                f"Function       : 0x{function:02X}"
            )

            if function & 0x80:

                exception_code = response[8]

                print(
                    f"Exception Code : "
                    f"0x{exception_code:02X}"
                )

                print()
                print(
                    "IMPORTANT: The gateway/logger "
                    "DID respond with a Modbus exception."
                )

            elif function == 0x03:

                byte_count = response[8]

                print(
                    f"Byte Count     : {byte_count}"
                )

                data = response[9:]

                print(
                    "Register bytes : "
                    f"{to_hex(data)}"
                )

                registers = []

                for i in range(0, len(data), 2):

                    if i + 1 < len(data):

                        value = int.from_bytes(
                            data[i:i + 2],
                            "big",
                        )

                        registers.append(value)

                print(
                    "Registers      : "
                    f"{[f'0x{x:04X}' for x in registers]}"
                )

                print(
                    "Decimal        : "
                    f"{registers}"
                )

                print()
                print("MODBUS RESULT  : PASS")

            else:

                print()
                print(
                    "Unexpected Modbus function."
                )

    except socket.timeout:

        print()
        print("TCP RECEIVE             : TIMEOUT")

        print()
        print(
            "The Waveshare TCP server accepted "
            "the connection but no response arrived "
            f"within {TIMEOUT} seconds."
        )

        print()
        print("This strongly points to:")
        print()
        print("  Python")
        print("     │")
        print("     │ TCP       ✓")
        print("     ▼")
        print("  Waveshare")
        print("     │")
        print("     │ RS485     ???")
        print("     ▼")
        print("  SMARTLOG-04")
        print("     │")
        print("     ▼")
        print("  No response")

    except ConnectionResetError:

        print()
        print(
            "TCP CONNECTION RESET BY WAVESHARE"
        )

    except Exception as exc:

        print()
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )

    finally:

        sock.close()

        print()
        print("Socket closed.")


if __name__ == "__main__":
    main()