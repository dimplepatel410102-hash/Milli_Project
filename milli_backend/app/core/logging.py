import logging

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    logger = logging.getLogger("milli")
    logger.setLevel(level)
    if not any(getattr(handler, "_milli", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._milli = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
