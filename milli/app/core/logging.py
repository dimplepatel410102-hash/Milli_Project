"""Logging helpers that keep API keys out of log records."""

import logging

_LOGGER_NAME = "milli"


class SecretRedactionFilter(logging.Filter):
    """Replace configured API keys if they ever reach a log line."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if len(secret) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for secret in self._secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, "[redacted]")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def configure_logging(level: str, secrets: list[str]) -> None:
    """Send Milli logs to stderr and redact configured API keys."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setLevel(level.upper())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(SecretRedactionFilter(secrets))
    logger.addHandler(handler)
    # Propagate so test capture and process supervisors can see the same records.
    # The handler filter redacts the record before it is propagated.
    logger.propagate = True


def safe_error_text(exc: BaseException) -> str:
    """Short printable exception text for logs. Drops non-text payloads."""
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if not text or any(ord(character) < 32 or ord(character) > 126 for character in text):
        return type(exc).__name__
    if len(text) > 180:
        text = text[:180] + "..."
    return f"{type(exc).__name__}: {text}"
