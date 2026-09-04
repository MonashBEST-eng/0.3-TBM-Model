from __future__ import annotations

import json
import socket
from typing import Any

from config import TELEMETRY_HOST, TELEMETRY_PORT


class TelemetryPublisher:
    """Publishes controller telemetry to monitor.py over localhost UDP."""

    def __init__(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._address = (TELEMETRY_HOST, TELEMETRY_PORT)

    def publish(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._socket.sendto(data, self._address)

    def close(self) -> None:
        self._socket.close()
