import socket
import time


WAVESHARE_IP = "192.168.0.204"
WAVESHARE_PORT = 502

TIMEOUT = 1.0
LISTEN_SECONDS = 60


def hex_string(data):

    return " ".join(
        f"{b:02X}"
        for b in data
    )


print("=" * 70)
print("WAVESHARE PASSIVE TCP MONITOR")
print("=" * 70)

print()
print(f"Device : {WAVESHARE_IP}:{WAVESHARE_PORT}")
print(f"Listen : {LISTEN_SECONDS} seconds")

sock = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

sock.settimeout(
    TIMEOUT
)

try:

    print()
    print(
        f"Connecting to "
        f"{WAVESHARE_IP}:{WAVESHARE_PORT}..."
    )

    sock.connect(
        (
            WAVESHARE_IP,
            WAVESHARE_PORT
        )
    )

    print("Connected.")

    print()
    print("=" * 70)
    print("PASSIVE LISTEN")
    print("=" * 70)

    print()
    print("NO DATA WILL BE TRANSMITTED.")
    print()

    start = time.monotonic()

    packet_count = 0

    previous_packet = None
    previous_time = None

    while True:

        elapsed = (
            time.monotonic() - start
        )

        if elapsed >= LISTEN_SECONDS:

            break

        try:

            data = sock.recv(
                4096
            )

            if not data:

                print()
                print(
                    "Device closed connection."
                )

                break

            packet_count += 1

            now = time.monotonic()

            if previous_time is None:

                interval = 0

            else:

                interval = (
                    now - previous_time
                )

            print()
            print("-" * 70)

            print(
                f"Packet #{packet_count}"
            )

            print(
                f"Time      : "
                f"{elapsed:.3f} s"
            )

            print(
                f"Interval  : "
                f"{interval:.3f} s"
            )

            print(
                f"Length    : "
                f"{len(data)} bytes"
            )

            print(
                f"RX        : "
                f"{hex_string(data)}"
            )

            if data == previous_packet:

                print(
                    "NOTE      : "
                    "Same packet as previous packet"
                )

            previous_packet = data

            previous_time = now

        except socket.timeout:

            continue

        except KeyboardInterrupt:

            print()
            print(
                "Stopped by user."
            )

            break

        except Exception as e:

            print()
            print(
                f"RX ERROR: {e}"
            )

            break

finally:

    sock.close()

    print()
    print("=" * 70)
    print("MONITOR FINISHED")
    print("=" * 70)

    print()
    print(
        f"Packets received: "
        f"{packet_count}"
    )
