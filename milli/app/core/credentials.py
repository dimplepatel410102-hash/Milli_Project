"""Configurable per-device API keys.

Credentials come from the environment. This module never logs a key.
"""

import hashlib
import hmac
import re

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MIN_API_KEY_LENGTH = 16
MAX_API_KEY_LENGTH = 256

# Obvious sample values from documentation. They must not authenticate.
PLACEHOLDER_API_KEYS = frozenset(
    {
        "replace-with-a-long-random-key",
        "put-a-long-random-key-here",
        "put-another-long-random-key-here",
        "changeme",
        "change-me",
        "password",
        "secret",
        "your-api-key",
        "your_api_key",
    }
)


class CredentialConfigError(ValueError):
    """MILLI_DEVICE_CREDENTIALS could not be parsed."""


def parse_device_credentials(raw: str | None) -> dict[str, str]:
    """Parse ``device_id:api_key`` pairs separated by commas.

    The API key is everything after the first colon, so a key may contain
    colons. Keys cannot contain spaces or commas. The returned mapping is
    device id to API key.
    """
    if raw is None or not raw.strip():
        return {}

    credentials: dict[str, str] = {}
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        if ":" not in item:
            raise CredentialConfigError(
                "MILLI_DEVICE_CREDENTIALS contains an entry without a colon. "
                "Use device_id:api_key pairs separated by commas."
            )
        device_id, api_key = item.split(":", 1)
        device_id = device_id.strip()
        api_key = api_key.strip()
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise CredentialConfigError(
                f"MILLI_DEVICE_CREDENTIALS has an invalid device id: {device_id!r}. "
                "Use 1-64 characters: letters, digits, '.', '_' or '-'."
            )
        if (
            not api_key
            or any(character.isspace() for character in api_key)
            or "," in api_key
            or len(api_key) > MAX_API_KEY_LENGTH
        ):
            raise CredentialConfigError(
                f"MILLI_DEVICE_CREDENTIALS has an invalid API key for device {device_id}. "
                "Keys must be 1-256 characters and cannot contain spaces or commas."
            )
        if device_id in credentials:
            raise CredentialConfigError(
                f"MILLI_DEVICE_CREDENTIALS lists device {device_id} more than once."
            )
        credentials[device_id] = api_key
    return credentials


def key_is_usable(api_key: str) -> bool:
    """Return whether a configured key is allowed to authenticate.

    Short keys and documented placeholders are rejected so copying
    ``.env.example`` unchanged cannot authorize a device.
    """
    if len(api_key) < MIN_API_KEY_LENGTH:
        return False
    return api_key.strip().lower() not in PLACEHOLDER_API_KEYS


def keys_match(provided: str, expected: str) -> bool:
    """Compare API keys without an early length leak."""
    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(provided_digest, expected_digest)


def authentication_failure_reason(device_id: str, credentials: dict[str, str]) -> str:
    """Return a log-safe reason. The reason never includes the API key."""
    expected = credentials.get(device_id)
    if expected is None:
        return "unknown_device"
    if not key_is_usable(expected):
        return "unusable_configured_key"
    return "key_mismatch"


def credentials_match(device_id: str, api_key: str, credentials: dict[str, str]) -> bool:
    expected = credentials.get(device_id)
    if expected is None or not key_is_usable(expected):
        # Still hash the provided key so unknown devices do similar work.
        keys_match(api_key, "milli-dummy-key-not-configured")
        return False
    return keys_match(api_key, expected)
