"""Optional temporary storage of received images.

Disabled by default (MILLI_STORE_IMAGES=false): images are processed in memory
and discarded after the response. When enabled, files older than
MILLI_STORAGE_MAX_AGE_SECONDS are deleted on each save (0 keeps them).
"""

import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.services.images import ValidatedImage

logger = logging.getLogger("milli.storage")


class ImageStore(Protocol):
    enabled: bool

    def save(self, *, device_id: str, capture_id: str, image: ValidatedImage, received_at: datetime) -> bool: ...

    def find(self, capture_id: str) -> Path | None: ...


class NullImageStore:
    enabled = False

    def save(self, *, device_id: str, capture_id: str, image: ValidatedImage, received_at: datetime) -> bool:
        return False

    def find(self, capture_id: str) -> Path | None:
        return None


class LocalImageStore:
    enabled = True

    def __init__(self, root: Path, max_age_seconds: int) -> None:
        self.root = root
        self.max_age_seconds = max_age_seconds

    def save(self, *, device_id: str, capture_id: str, image: ValidatedImage, received_at: datetime) -> bool:
        # device_id is validated against DEVICE_ID_PATTERN and capture_id is a UUID hex,
        # so neither can escape the storage root.
        directory = self.root / device_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{received_at:%Y%m%dT%H%M%S}_{capture_id}.{image.extension}"
        partial = target.with_suffix(target.suffix + ".part")
        partial.write_bytes(image.data)
        os.replace(partial, target)
        self.prune()
        return True

    def find(self, capture_id: str) -> Path | None:
        """Stored file for a server capture_id (32 hex chars), or None."""
        if not re.fullmatch(r"[0-9a-f]{32}", capture_id) or not self.root.exists():
            return None
        return next((p for p in self.root.glob(f"*/*_{capture_id}.*") if not p.name.endswith(".part")), None)

    def prune(self) -> int:
        if self.max_age_seconds <= 0 or not self.root.exists():
            return 0
        cutoff = time.time() - self.max_age_seconds
        removed = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                logger.warning("could not prune stored capture file=%s", path.name)
        return removed
