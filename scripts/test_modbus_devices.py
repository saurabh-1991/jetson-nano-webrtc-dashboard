#!/usr/bin/env python3
"""
Quick Modbus TCP diagnostics for Waveshare + attached RS485 devices.

Purpose:
- Verify TCP reachability (for example 192.168.0.200:502)
- Probe which unit IDs respond
- Read known datalogger channel registers (CH1..CH4 style map)
- Optionally loop so field operators can watch live value changes

Example usage:
    python3 scripts/test_modbus_devices.py --host 192.168.0.200 --ports 502
  python3 scripts/test_modbus_devices.py --host 192.168.0.200 --ports 502 --loop 2
"""

import argparse
import datetime as dt
import socket
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    # pymodbus <= 2.x
    from pymodbus.client.sync import ModbusTcpClient  # type: ignore
except Exception:
    try:
        # pymodbus >= 3.x
        from pymodbus.client import ModbusTcpClient  # type: ignore
    except Exception:
        print("ERROR: pymodbus is not installed in this Python environment.")
        print("Install it with: pip3 install pymodbus")
        sys.exit(2)


# -----------------------------------------------------------------------------
# USER-EDITABLE DEFAULTS
# Change values here when you want script behavior changes without CLI args.
# CLI arguments still override these values.
# -----------------------------------------------------------------------------
DEFAULT_HOST = "192.168.0.200"
DEFAULT_PORTS = "502"
DEFAULT_TIMEOUT = 2.0
DEFAULT_UNITS = "1,2,3,4,5,6,7,8,9,10"
DEFAULT_PROBE_ADDRS = "10,9,1,2,3,4,5,6,7,8"
DEFAULT_PROBE_TYPES = "holding,input"
DEFAULT_ADDRESSES = "10,11,12,13,14,15,16,17,18,19,20,21"
DEFAULT_CHANNEL_BASES = "3,2,1" #10,9
DEFAULT_DATALOGGER_UNIT = None
DEFAULT_LOOP_SECONDS = 0.0


def parse_csv_ints(raw: str) -> List[int]:
    out = []
    for token in str(raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        out.append(int(token, 0))
    return out


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def tcp_reachable(host: str, port: int, timeout: float) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "open"
    except Exception as exc:
        return False, str(exc)


def read_single_register(client, reg_type: str, address: int, unit: int) -> Tuple[bool, Optional[int], str]:
    try:
        if reg_type == "input":
            rr = client.read_input_registers(address=address, count=1, unit=unit)
        else:
            rr = client.read_holding_registers(address=address, count=1, unit=unit)

        if not rr:
            return False, None, "empty_response"

        if rr.isError():
            return False, None, str(rr)

        return True, int(rr.registers[0]), "ok"
    except Exception as exc:
        return False, None, str(exc)


def signed16(value: int) -> int:
    if value >= 0x8000:
        return value - 0x10000
    return value


def status_text(code: Optional[int]) -> str:
    if code is None:
        return "unknown"
    return {
        0: "in_range",
        1: "under_range",
        2: "over_range",
        3: "open",
    }.get(int(code), f"unknown({code})")


def decode_channel_value(raw_value: Optional[int], raw_decimal: Optional[int], default_scale: float = 0.1) -> Optional[float]:
    if raw_value is None:
        return None

    value = float(signed16(int(raw_value)))

    if raw_decimal is not None and 0 <= int(raw_decimal) <= 4:
        scale = 10 ** (-int(raw_decimal))
    else:
        scale = float(default_scale)

    return round(value * scale, 4)


def probe_units(client, units: List[int], probe_addr: int, probe_types: List[str]) -> Dict[str, List[int]]:
    responders = {"holding": [], "input": []}

    for unit in units:
        for reg_type in probe_types:
            ok, value, _msg = read_single_register(client, reg_type, probe_addr, unit)
            if ok:
                responders[reg_type].append(unit)
                print(f"  unit {unit:>2} [{reg_type}] addr {probe_addr}: OK value={value}")

    return responders


def print_datalogger_channels(client, unit: int, reg_type: str, base_addr: int = 10):
    # Smart Log-04 style map using a configurable base address.
    # Some gateways/docs expose 0010 as wire address 10, others as 9 (offset -1).
    channels = {
        "CH1": (base_addr + 0, base_addr + 1, base_addr + 2),
        "CH2": (base_addr + 3, base_addr + 4, base_addr + 5),
        "CH3": (base_addr + 6, base_addr + 7, base_addr + 8),
        "CH4": (base_addr + 9, base_addr + 10, base_addr + 11),
    }

    print(f"\n  Datalogger decode for unit={unit}, reg_type={reg_type}, base_addr={base_addr}")
    for ch_name, (v_addr, d_addr, s_addr) in channels.items():
        ok_v, raw_v, msg_v = read_single_register(client, reg_type, v_addr, unit)
        ok_d, raw_d, msg_d = read_single_register(client, reg_type, d_addr, unit)
        ok_s, raw_s, msg_s = read_single_register(client, reg_type, s_addr, unit)

        value = decode_channel_value(raw_v if ok_v else None, raw_d if ok_d else None)
        stxt = status_text(raw_s if ok_s else None)

        print(
            f"    {ch_name}: "
            f"value_raw={raw_v if ok_v else 'ERR'} "
            f"decimal_raw={raw_d if ok_d else 'ERR'} "
            f"status_raw={raw_s if ok_s else 'ERR'}({stxt}) "
            f"decoded={value if value is not None else 'None'}"
        )

        if not ok_v or not ok_d or not ok_s:
            details = []
            if not ok_v:
                details.append(f"value_err={msg_v}")
            if not ok_d:
                details.append(f"decimal_err={msg_d}")
            if not ok_s:
                details.append(f"status_err={msg_s}")
            print("      details: " + " | ".join(details))


def print_raw_address_scan(client, unit: int, reg_type: str, addresses: List[int]):
    print(f"\n  Raw scan for unit={unit}, reg_type={reg_type}")
    for addr in addresses:
        ok, val, msg = read_single_register(client, reg_type, addr, unit)
        if ok:
            print(f"    addr {addr:>4}: {val}")
        else:
            print(f"    addr {addr:>4}: ERR ({msg})")


def run_once(args) -> int:
    print("\n" + "=" * 72)
    print(f"[{now_iso()}] Modbus diagnostics start")

    ports = parse_csv_ints(args.ports)
    units = parse_csv_ints(args.units)
    scan_addresses = parse_csv_ints(args.addresses)
    probe_addrs = parse_csv_ints(args.probe_addrs)
    channel_bases = parse_csv_ints(args.channel_bases)
    probe_types = [t.strip().lower() for t in args.probe_types.split(",") if t.strip()]

    print(
        "Effective settings: "
        f"host={args.host} ports={ports} timeout={args.timeout}s "
        f"units={units} probe_addrs={probe_addrs} probe_types={probe_types}"
    )

    for port in ports:
        print("\n" + "-" * 72)
        print(f"Target: {args.host}:{port}")

        reachable, reason = tcp_reachable(args.host, port, args.timeout)
        print(f"TCP reachability: {'OPEN' if reachable else 'CLOSED'} ({reason})")
        if not reachable:
            continue

        client = ModbusTcpClient(host=args.host, port=port, timeout=args.timeout)
        connected = client.connect()
        print(f"Modbus client connect: {connected}")
        if not connected:
            client.close()
            continue

        try:
            aggregate = {"holding": [], "input": []}
            for probe_addr in probe_addrs:
                print(f"\n  Unit probe addr={probe_addr} reg_types={probe_types}")
                responders = probe_units(client, units, probe_addr, probe_types)
                print(f"  Responders@{probe_addr}: holding={responders['holding']} input={responders['input']}")
                for reg_type in ("holding", "input"):
                    for unit in responders[reg_type]:
                        if unit not in aggregate[reg_type]:
                            aggregate[reg_type].append(unit)

            print(f"  Aggregate responders: holding={aggregate['holding']} input={aggregate['input']}")

            # Use explicit unit if provided, else first responder fallback.
            chosen_unit = args.datalogger_unit
            if chosen_unit is None:
                chosen_unit = aggregate["holding"][0] if aggregate["holding"] else None
                if chosen_unit is None and aggregate["input"]:
                    chosen_unit = aggregate["input"][0]

            if chosen_unit is not None:
                for reg_type in probe_types:
                    for base_addr in channel_bases:
                        print_datalogger_channels(client, chosen_unit, reg_type, base_addr=base_addr)
                    print_raw_address_scan(client, chosen_unit, reg_type, scan_addresses)
            else:
                print("\n  No responding unit found in probe list; cannot decode channels.")

        finally:
            client.close()

    print(f"[{now_iso()}] Diagnostics end")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Modbus TCP diagnostics for Waveshare + sensors")
    p.add_argument("--host", default=DEFAULT_HOST, help="Waveshare host IP")
    p.add_argument("--ports", default=DEFAULT_PORTS, help="Comma-separated TCP ports to test")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="TCP/Modbus timeout seconds")
    p.add_argument("--units", default=DEFAULT_UNITS, help="Unit IDs to probe")
    p.add_argument(
        "--probe-addrs",
        default=DEFAULT_PROBE_ADDRS,
        help="Probe register addresses to test (10=direct map, 9=offset -1 map)",
    )
    p.add_argument(
        "--probe-types",
        default=DEFAULT_PROBE_TYPES,
        help="Register types to probe (holding,input)",
    )
    p.add_argument(
        "--addresses",
        default=DEFAULT_ADDRESSES,
        help="Address list for raw scan per register type",
    )
    p.add_argument(
        "--channel-bases",
        default=DEFAULT_CHANNEL_BASES,
        help="Channel base addresses to decode for CH1..CH4 (for datasheet offset checks)",
    )
    p.add_argument(
        "--datalogger-unit",
        type=int,
        default=DEFAULT_DATALOGGER_UNIT,
        help="Force specific datalogger unit ID (default: auto from responders)",
    )
    p.add_argument(
        "--loop",
        type=float,
        default=DEFAULT_LOOP_SECONDS,
        help="Repeat interval in seconds (0 = run once)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    if args.loop and args.loop > 0:
        while True:
            run_once(args)
            time.sleep(args.loop)

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
