from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import zipfile

from .config import Settings
from .copy_engine import MARKER
from .errors import ArchiveError
from .models import CopyResult


def create_archive(result: CopyResult, settings: Settings, logger: logging.Logger) -> Path:
    suffix = "_partial" if result.interrupted or result.partial_files else ""
    final = result.job_dir.parent / f"{result.job_dir.name}{suffix}.zip"
    writing = final.with_suffix(".zip.creating")
    logger.info("阶段 2 开始流式压缩 | 源=%s | ZIP=%s", result.job_dir, final)
    try:
        with zipfile.ZipFile(writing, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path in sorted(result.job_dir.rglob("*")):
                relative = path.relative_to(result.job_dir).as_posix()
                if path.is_dir():
                    if not any(path.iterdir()):
                        archive.writestr(relative.rstrip("/") + "/", b"")
                    continue
                size = path.stat().st_size
                logger.info("压缩文件: %s | 大小=%d", relative, size)
                info = zipfile.ZipInfo.from_file(path, relative)
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as src, archive.open(info, "w", force_zip64=True) as dst:
                    while True:
                        block = src.read(settings.archive_chunk_size)
                        if not block:
                            break
                        dst.write(block)
        # Windows requires a writable descriptor for fsync/FlushFileBuffers.
        with writing.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(writing, final)
        with zipfile.ZipFile(final, "r") as check:
            check.infolist()
        logger.info("ZIP 压缩成功: %s | 大小=%d", final, final.stat().st_size)
        return final
    except Exception as exc:
        try:
            writing.unlink(missing_ok=True)
        except OSError:
            pass
        logger.error("ZIP 压缩失败，已落盘目录保留: %s", result.job_dir, exc_info=True)
        raise ArchiveError(str(exc)) from exc


def remove_managed_job(job_dir: Path, backup_root: Path, logger: logging.Logger) -> None:
    resolved_job = job_dir.resolve()
    resolved_root = backup_root.resolve()
    if resolved_job.parent != resolved_root or not (resolved_job / MARKER).is_file():
        raise ArchiveError(f"拒绝删除非托管目录: {job_dir}")
    shutil.rmtree(resolved_job)
    logger.info("ZIP 已验证，删除本地临时目录: %s", job_dir)
