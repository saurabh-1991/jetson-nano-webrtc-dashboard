from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient(
    "192.168.0.202",
    port=502,
    timeout=10,
    retries=5
)

try:
    if not client.connect():
        print("Cannot connect to Waveshare")
        exit()

    print("Connected to Waveshare")

    result = client.read_holding_registers(
        address=0x2101,
        count=1,
        slave=1
    )

    print("Result:", result)

finally:
    client.close()