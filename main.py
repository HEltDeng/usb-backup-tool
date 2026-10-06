from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys

from usb_backup_v10.config import Settings, application_dir
from usb_backup_v10.logging_utils import create_logger
from usb_backup_v10.watcher import USBWatcher


ERROR_ALREADY_EXISTS = 183


def acquire_single_instance():
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\USB_Backup_V10_Singleton")
    if not handle or ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def main() -> int:
    mutex = acquire_single_instance()
    if mutex is None:
        return 0
    settings = Settings.load()
    try:
        logger = create_logger(settings.backup_root)
    except OSError:
        fallback = Path(os.environ.get("LOCALAPPDATA", application_dir())) / "USB_Backup_V10"
        logger = create_logger(fallback)
    logger.info(
        "USB Backup V10 启动 | PID=%d | 备份根目录=%s | COPY_CHUNK=%d | FLUSH_BYTES=%d | 上传启用=%s | Token配置=%s",
        os.getpid(), settings.backup_root, settings.copy_chunk_size, settings.flush_bytes,
        settings.upload_enabled, bool(settings.refresh_token),
    )
    if os.environ.get("USB_BACKUP_SELF_TEST") == "1":
        logger.info("EXE 自检模式通过")
        return 0
    USBWatcher(settings, logger).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
