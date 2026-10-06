from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Any


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    backup_root: Path = Path(r"D:\USB_Backup")
    copy_chunk_size: int = 1024 * 1024
    archive_chunk_size: int = 1024 * 1024
    flush_bytes: int = 32 * 1024 * 1024
    scan_interval_seconds: float = 2.0
    debounce_seconds: float = 30.0
    part_size: int = 5 * 1024 * 1024
    max_retries: int = 3
    timeout_seconds: float = 30.0
    remote_root: str = "/USB_Backup"
    dry_run: bool = False
    upload_enabled: bool = False
    refresh_token: str = field(default="", repr=False)
    api_base: str = "https://api.aliyundrive.com"
    auth_base: str = "https://auth.aliyundrive.com"

    @classmethod
    def load(cls) -> "Settings":
        local: dict[str, Any] = {}
        config_path = application_dir() / "config.local.json"
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    local = loaded
            except (OSError, json.JSONDecodeError):
                local = {}

        def get(env: str, local_key: str, default: Any) -> Any:
            return os.environ.get(env, local.get(local_key, default))

        return cls(
            backup_root=Path(get("USB_BACKUP_ROOT", "backup_root", r"D:\USB_Backup")),
            copy_chunk_size=_int(get("USB_BACKUP_COPY_CHUNK", "copy_chunk_size", 1024 * 1024), 1024 * 1024, 64 * 1024),
            archive_chunk_size=_int(get("USB_BACKUP_ARCHIVE_CHUNK", "archive_chunk_size", 1024 * 1024), 1024 * 1024, 64 * 1024),
            flush_bytes=_int(get("USB_BACKUP_FLUSH_BYTES", "flush_bytes", 32 * 1024 * 1024), 32 * 1024 * 1024, 1024 * 1024),
            scan_interval_seconds=float(get("USB_BACKUP_SCAN_INTERVAL", "scan_interval_seconds", 2.0)),
            debounce_seconds=float(get("USB_BACKUP_DEBOUNCE", "debounce_seconds", 30.0)),
            part_size=_int(get("ALIDRIVE_PART_SIZE", "part_size", 5 * 1024 * 1024), 5 * 1024 * 1024, 1024 * 1024),
            max_retries=_int(get("ALIDRIVE_MAX_RETRIES", "max_retries", 3), 3, 1),
            timeout_seconds=float(get("ALIDRIVE_TIMEOUT_SECONDS", "timeout_seconds", 30.0)),
            remote_root=str(get("ALIDRIVE_REMOTE_ROOT", "remote_root", "/USB_Backup")),
            dry_run=_bool(get("USB_BACKUP_DRY_RUN", "dry_run", False)),
            upload_enabled=_bool(get("ALIDRIVE_UPLOAD_ENABLED", "upload_enabled", False)),
            refresh_token=str(get("ALIDRIVE_REFRESH_TOKEN", "refresh_token", "")).strip(),
            api_base=str(get("ALIDRIVE_API_BASE", "api_base", "https://api.aliyundrive.com")).rstrip("/"),
            auth_base=str(get("ALIDRIVE_AUTH_BASE", "auth_base", "https://auth.aliyundrive.com")).rstrip("/"),
        )
