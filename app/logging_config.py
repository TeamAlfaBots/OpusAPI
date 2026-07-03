"""Structured logging configuration."""
import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy third-party loggers a bit
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
