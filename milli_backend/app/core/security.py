"""Per-device API key authentication.

Only SHA-256 digests of device API keys are kept in configuration. Keys are
long random tokens (see app.tools.device_key), so a fast hash is sufficient;
no plaintext key ever needs to live on the server.
"""

import hashlib
import hmac
import re
import secrets

DEVICE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
MAX_API_KEY_LENGTH = 256

_DEVICE_ID_RE = re.compile(DEVICE_ID_PATTERN)
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# Compared against when the device ID is unknown so both paths do the same work.
_UNKNOWN_DEVICE_DIGEST = "0" * 64


def is_valid_device_id(value: str | None) -> bool:
    return bool(value) and _DEVICE_ID_RE.fullmatch(value) is not None


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def parse_device_credentials(raw: str) -> dict[str, str]:
    """Parse "device_id:sha256hex,device_id:sha256hex" into a dict.

    Error messages never include the digest values.
    """
    credentials: dict[str, str] = {}
    for position, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        device_id, separator, digest = item.partition(":")
        device_id = device_id.strip()
        digest = digest.strip().lower()
        if not separator or not is_valid_device_id(device_id):
            raise ValueError(
                f"MILLI_DEVICE_CREDENTIALS entry #{position} must look like "
                "'device_id:sha256_hex' with a device ID of letters, digits, '-' or '_'"
            )
        if not _SHA256_HEX_RE.fullmatch(digest):
            raise ValueError(
                f"MILLI_DEVICE_CREDENTIALS entry for '{device_id}' must be a SHA-256 hex digest "
                "of the API key (generate one with: python -m app.tools.device_key new <device_id>)"
            )
        if device_id in credentials:
            raise ValueError(f"MILLI_DEVICE_CREDENTIALS lists device '{device_id}' more than once")
        credentials[device_id] = digest
    return credentials


class DeviceCredentialStore:
    def __init__(self, digests: dict[str, str]) -> None:
        self._digests = dict(digests)

    def __len__(self) -> int:
        return len(self._digests)

    def verify(self, device_id: str, api_key: str) -> bool:
        presented = hash_api_key(api_key)
        expected = self._digests.get(device_id, _UNKNOWN_DEVICE_DIGEST)
        matches = hmac.compare_digest(presented, expected)
        return matches and device_id in self._digests
