"""In-memory device registration. Records are lost when the process stops."""

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RegisteredDevice:
    device_id: str
    registered_at: datetime
    last_seen_at: datetime


class DeviceRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, RegisteredDevice] = {}

    def register(self, device_id: str, now: datetime) -> tuple[RegisteredDevice, bool]:
        """Register the device. Returns the record and whether this call created it."""
        with self._lock:
            existing = self._devices.get(device_id)
            if existing is None:
                record = RegisteredDevice(
                    device_id=device_id,
                    registered_at=now,
                    last_seen_at=now,
                )
                self._devices[device_id] = record
                return record, True
            record = RegisteredDevice(
                device_id=device_id,
                registered_at=existing.registered_at,
                last_seen_at=now,
            )
            self._devices[device_id] = record
            return record, False

    def is_registered(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._devices
