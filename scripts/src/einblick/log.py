import logging
import sys

_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    logger = logging.getLogger(f"einblick.{name}")
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        root = logging.getLogger("einblick")
        root.addHandler(handler)
        root.setLevel(logging.WARNING)
        _configured = True
    return logger
