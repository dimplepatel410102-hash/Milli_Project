"""In-memory device registry. Phase 1 only: contents are lost when the server restarts."""

import threading
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    firmware_version: str
    hardware_model: str
    camera_model: str | None
    on_device_face_detection: bool
    registered_at: datetime
    last_capture_at: datetime | None = None


class InMemoryDeviceRegistry:
    persistent = False

    def __init__(self) -> None:
        self._records: dict[str, DeviceRecord] = {}
        self._lock = threading.Lock()

    def register(self, record: DeviceRecord) -> tuple[DeviceRecord, bool]:
        """Store the record; returns (record, created)."""
        with self._lock:
            previous = self._records.get(record.device_id)
            if previous is not None:
                record = replace(record, last_capture_at=previous.last_capture_at)
            self._records[record.device_id] = record
            return record, previous is None

    def get(self, device_id: str) -> DeviceRecord | None:
        with self._lock:
            return self._records.get(device_id)

    def mark_capture(self, device_id: str, when: datetime) -> None:
        with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                self._records[device_id] = replace(record, last_capture_at=when)
