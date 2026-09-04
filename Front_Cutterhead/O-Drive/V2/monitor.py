"""Second-terminal ODrive monitor.

This program does NOT open PCAN. main.py remains the only process that owns
PCAN_USBBUS1 and sends telemetry here through localhost UDP.
"""

from __future__ import annotations

import json
import os
import socket
import time

from config import (
    TELEMETRY_HOST,
    TELEMETRY_PORT,
    TELEMETRY_STALE_AFTER,
)


def clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def format_axis(name: str, axis_data: dict | None) -> str:
    if axis_data is None:
        return f"{name}\n  Position : no response\n  Speed    : no response"

    position = float(axis_data["position_turns"])
    rps = float(axis_data["velocity_rps"])
    rpm = rps * 60.0

    return (
        f"{name}\n"
        f"  Position : {position:10.3f} turns\n"
        f"  Speed    : {rps:10.3f} RPS\n"
        f"  Speed    : {rpm:10.1f} RPM"
    )


def display(payload: dict, received_at: float) -> None:
    age = time.perf_counter() - received_at
    status = "LIVE" if age <= TELEMETRY_STALE_AFTER else f"STALE ({age:.1f} s)"

    target_rps = float(payload.get("target_rps", 0.0))
    command_rps = float(payload.get("command_rps", 0.0))
    state = "IDLE" if payload.get("axes_idle", True) else "CLOSED LOOP"

    clear_terminal()
    print(f"ODrive telemetry monitor [{status}]")
    print("Press Ctrl+C to exit.\n")
    print(f"Controller state : {state}")
    print(f"Target           : {target_rps:8.3f} RPS  ({target_rps * 60:8.1f} RPM)")
    print(f"Ramped command   : {command_rps:8.3f} RPS  ({command_rps * 60:8.1f} RPM)\n")
    print(format_axis("Axis 0", payload.get("axis0")))
    print()
    print(format_axis("Axis 1", payload.get("axis1")))


def main() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind((TELEMETRY_HOST, TELEMETRY_PORT))
    receiver.settimeout(1.0)

    print(
        f"Waiting for main.py telemetry on "
        f"{TELEMETRY_HOST}:{TELEMETRY_PORT}..."
    )

    last_payload: dict | None = None
    last_received_at = 0.0

    try:
        while True:
            try:
                data, _address = receiver.recvfrom(65535)
                last_payload = json.loads(data.decode("utf-8"))
                last_received_at = time.perf_counter()
                display(last_payload, last_received_at)
            except socket.timeout:
                if last_payload is None:
                    continue
                display(last_payload, last_received_at)

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"\nInvalid telemetry packet: {error}")
    finally:
        receiver.close()


if __name__ == "__main__":
    main()
