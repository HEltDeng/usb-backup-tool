from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
from typing import BinaryIO, Callable, Iterator

from .config import Settings
from .models import CopyResult, FileRecord


MARKER = ".usb_backup_v10_job"
MANIFEST = "backup_manifest.json"
PARTIAL_SUFFIX = ".usbbackup.partial"
WRITING_SUFFIX = ".__usbbackup_writing__"


def safe_component(value: str, fallback: str = "USB") -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in value)
    cleaned = cleaned.strip(" ._")[:80]
    return cleaned or fallback


def make_job_dir(root: Path, drive: Path, label: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]
    letter = safe_component(drive.drive.rstrip(":") or "USB")
    base = f"{stamp}_{letter}_{safe_component(label)}"
    candidate = root / base
    index = 1
    while candidate.exists():
        candidate = root / f"{base}_{index}"
        index += 1
    candidate.mkdir(parents=False)
    (candidate / MARKER).write_text("USB Backup V10 managed job\n", encoding="utf-8")
    return candidate


def _manifest_payload(result: CopyResult) -> dict[str, object]:
    return {
        "format": 1,
        "interrupted": result.interrupted,
        "interruption_reason": result.interruption_reason,
        "copied_bytes": result.copied_bytes,
        "complete_files": result.complete_files,
        "partial_files": result.partial_files,
        "files": [item.__dict__ for item in result.records],
    }


def write_manifest(result: CopyResult) -> None:
    target = result.job_dir / MANIFEST
    temporary = target.with_suffix(".json.writing")
    temporary.write_text(json.dumps(_manifest_payload(result), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _walk(root: Path) -> Iterator[tuple[Path, list[os.DirEntry[str]], list[os.DirEntry[str]]]]:
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            dirs: list[os.DirEntry[str]] = []
            files: list[os.DirEntry[str]] = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry)
                    elif entry.is_file(follow_symlinks=False):
                        files.append(entry)
                except OSError:
                    files.append(entry)
        yield current, dirs, files
        pending.extend(Path(entry.path) for entry in reversed(dirs))


def _sync(file: BinaryIO) -> None:
    file.flush()
    os.fsync(file.fileno())


def copy_one_file(
    source: Path,
    destination: Path,
    chunk_size: int,
    flush_bytes: int,
    logger: logging.Logger,
    source_opener: Callable[..., BinaryIO] = open,
    target_opener: Callable[..., BinaryIO] = open,
) -> FileRecord:
    expected = source.stat().st_size
    temporary = destination.with_name(destination.name + WRITING_SUFFIX)
    partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    since_sync = 0
    logger.info("开始复制文件: %s | 大小=%d", source, expected)
    try:
        with source_opener(source, "rb") as src, target_opener(temporary, "wb") as dst:
            while True:
                block = src.read(chunk_size)
                if not block:
                    break
                dst.write(block)
                copied += len(block)
                since_sync += len(block)
                if since_sync >= flush_bytes:
                    _sync(dst)
                    since_sync = 0
                    logger.info("复制进度: %s | 已落盘=%d/%d", source, copied, expected)
            _sync(dst)
        if copied != expected:
            raise OSError(f"文件大小在复制期间变化: expected={expected}, copied={copied}")
        os.replace(temporary, destination)
        try:
            shutil.copystat(source, destination, follow_symlinks=False)
        except OSError:
            logger.warning("无法复制文件时间/属性，内容已完整保存: %s", source)
        logger.info("文件复制成功: %s | 大小=%d", source, copied)
        return FileRecord(str(destination.name), expected, copied, "complete")
    except Exception as exc:
        if temporary.exists():
            try:
                os.replace(temporary, partial)
            except OSError:
                pass
        logger.error("文件复制中断/失败: %s | 已落盘=%d/%d | %s", source, copied, expected, exc)
        return FileRecord(str(destination.name), expected, copied, "partial" if copied else "failed", f"{type(exc).__name__}: {exc}")


def _device_lost(source_root: Path, error_text: str = "") -> bool:
    if not source_root.exists():
        return True
    lowered = error_text.lower()
    return any(token in lowered for token in ("device is not ready", "设备未就绪", "i/o device error", "设备已断开"))


def copy_usb_tree(
    source_root: Path,
    label: str,
    settings: Settings,
    logger: logging.Logger,
    file_copier: Callable[..., FileRecord] = copy_one_file,
) -> CopyResult:
    source_resolved = source_root.resolve()
    backup_resolved = settings.backup_root.resolve()
    if backup_resolved == source_resolved or source_resolved in backup_resolved.parents:
        raise ValueError("备份根目录不能位于被备份 U盘内部，否则会递归复制自身")
    job = make_job_dir(settings.backup_root, source_root, label)
    result = CopyResult(job_dir=job)
    write_manifest(result)
    logger.info("阶段 1 开始持续落盘复制 | U盘=%s | 目标=%s", source_root, job)
    try:
        for current, directories, files in _walk(source_root):
            relative_dir = current.relative_to(source_root)
            target_dir = job / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for directory in directories:
                (target_dir / directory.name).mkdir(parents=True, exist_ok=True)
            for entry in files:
                source = Path(entry.path)
                destination = target_dir / entry.name
                try:
                    record = file_copier(
                        source,
                        destination,
                        settings.copy_chunk_size,
                        settings.flush_bytes,
                        logger,
                    )
                except Exception as exc:
                    record = FileRecord(str(destination.relative_to(job)), 0, 0, "failed", f"{type(exc).__name__}: {exc}")
                record.relative_path = str(destination.relative_to(job)) + (PARTIAL_SUFFIX if record.state == "partial" else "")
                result.records.append(record)
                if record.state != "complete" and _device_lost(source_root, record.error):
                    result.interrupted = True
                    result.interruption_reason = record.error or "源设备已拔出"
                    write_manifest(result)
                    raise StopIteration
                write_manifest(result)
    except StopIteration:
        pass
    except Exception as exc:
        result.interrupted = True
        result.interruption_reason = f"{type(exc).__name__}: {exc}"
        logger.error("遍历 U盘中断，将压缩已落盘内容: %s", result.interruption_reason, exc_info=True)
    finally:
        write_manifest(result)
    logger.info(
        "阶段 1 结束 | 完整文件=%d | 部分文件=%d | 已落盘字节=%d | 中断=%s",
        result.complete_files,
        result.partial_files,
        result.copied_bytes,
        result.interrupted,
    )
    return result
