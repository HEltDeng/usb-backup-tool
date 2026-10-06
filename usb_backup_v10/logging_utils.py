from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re


class SecretFilter(logging.Filter):
    _pattern = re.compile(
        r"(?i)(authorization|access[_ -]?token|refresh[_ -]?token)(\s*[=:]\s*)([^\s,}\]]+)"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        record.msg = self._pattern.sub(r"\1\2<redacted>", text)
        record.args = ()
        return True


def create_logger(root: Path) -> logging.Logger:
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("usb_backup_v10")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = RotatingFileHandler(
        root / "backup_log.txt", maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    handler.addFilter(SecretFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
