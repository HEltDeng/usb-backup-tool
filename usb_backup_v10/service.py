from __future__ import annotations

import logging
from pathlib import Path

from .aliyun import AliDriveClient
from .archive import create_archive, remove_managed_job
from .config import Settings
from .copy_engine import MARKER, MANIFEST, PARTIAL_SUFFIX, WRITING_SUFFIX, copy_usb_tree, write_manifest
from .errors import ArchiveError, UploadError
from .models import CopyResult, FileRecord, TaskResult


def upload_archive(archive: Path, settings: Settings, logger: logging.Logger, client_factory=AliDriveClient) -> bool:
    if settings.dry_run:
        logger.info("DRY_RUN：跳过上传和 ZIP 删除: %s", archive)
        return False
    if not settings.upload_enabled:
        logger.info("云上传未启用，本地 ZIP 已保留: %s", archive)
        return False
    if not settings.refresh_token:
        logger.error("云上传已启用但未配置 Token，本地 ZIP 已保留")
        return False
    try:
        client_factory(settings, logger).upload(archive)
        archive.unlink()
        logger.info("上传成功后删除本地 ZIP: %s", archive)
        return True
    except Exception as exc:
        logger.error("上传失败，本地 ZIP 已保留: %s | %s", archive, exc, exc_info=True)
        return False


def process_drive(drive: Path, label: str, settings: Settings, logger: logging.Logger) -> TaskResult:
    logger.info("========== 新任务开始 | U盘=%s | 卷标=%s ==========", drive, label or "无")
    copy_result = copy_usb_tree(drive, label, settings, logger)
    try:
        archive = create_archive(copy_result, settings, logger)
    except ArchiveError as exc:
        return TaskResult(True, True, None, False, False, f"压缩失败，目录已保留: {exc}")
    remove_managed_job(copy_result.job_dir, settings.backup_root, logger)
    uploaded = upload_archive(archive, settings, logger)
    result = TaskResult(True, copy_result.interrupted or bool(copy_result.partial_files), archive if not uploaded else None, uploaded, not uploaded, "完成")
    logger.info(
        "========== 任务结束 | local=True | partial=%s | uploaded=%s | upload_pending=%s ==========",
        result.partial,
        result.uploaded,
        result.upload_pending,
    )
    return result


def retry_pending_archives(settings: Settings, logger: logging.Logger) -> None:
    if not settings.upload_enabled or not settings.refresh_token or settings.dry_run:
        return
    for archive in sorted(settings.backup_root.glob("*.zip")):
        logger.info("发现待上传 ZIP，开始重试: %s", archive)
        if not upload_archive(archive, settings, logger):
            break


def recover_abandoned_jobs(settings: Settings, logger: logging.Logger) -> None:
    """Turn crash/power-loss leftovers into explicit partial ZIPs on next start."""
    if not settings.backup_root.exists():
        return
    for job in sorted(path for path in settings.backup_root.iterdir() if path.is_dir() and (path / MARKER).is_file()):
        logger.warning("发现上次异常退出遗留目录，开始抢救压缩: %s", job)
        records: list[FileRecord] = []
        for writing in list(job.rglob("*" + WRITING_SUFFIX)):
            partial = writing.with_name(writing.name[: -len(WRITING_SUFFIX)] + PARTIAL_SUFFIX)
            try:
                writing.replace(partial)
            except OSError:
                logger.error("遗留写入文件无法改为部分文件: %s", writing, exc_info=True)
        for path in job.rglob("*"):
            if not path.is_file() or path.name in {MARKER, MANIFEST}:
                continue
            size = path.stat().st_size
            state = "partial" if path.name.endswith(PARTIAL_SUFFIX) else "complete"
            records.append(FileRecord(str(path.relative_to(job)), size, size, state))
        result = CopyResult(job, records, interrupted=True, interruption_reason="程序上次异常退出或电脑断电")
        write_manifest(result)
        try:
            archive = create_archive(result, settings, logger)
            remove_managed_job(job, settings.backup_root, logger)
            upload_archive(archive, settings, logger)
        except Exception:
            logger.error("遗留任务恢复失败，原始恢复目录保留: %s", job, exc_info=True)
