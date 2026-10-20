"""Logging configuration with rotating file handlers."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configure application-wide logging.

    Creates a rotating file handler and a stderr handler.
    Secrets are filtered from log output.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return logging.getLogger("photoport")

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "photoport.log"

    root_logger = logging.getLogger("photoport")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler: 10 MB per file, keep 5 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_SecretFilter())
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_SecretFilter())
    root_logger.addHandler(console_handler)

    _CONFIGURED = True
    return root_logger


class _SecretFilter(logging.Filter):
    """Filter that redacts potential OAuth tokens and secrets from log messages."""

    _SENSITIVE_PATTERNS = ("Bearer ", "ya29.", "access_token", "refresh_token", "client_secret")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.msg)
        for pattern in self._SENSITIVE_PATTERNS:
            if pattern in msg:
                record.msg = "[REDACTED — sensitive content filtered]"
                record.args = None
                break
        return True
