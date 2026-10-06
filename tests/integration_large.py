"""Opt-in real 256 MiB streaming copy/ZIP test; never touches a physical USB."""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shutil
import sys
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from usb_backup_v10.archive import create_archive
from usb_backup_v10.config import Settings
from usb_backup_v10.copy_engine import copy_usb_tree


def main() -> int:
    root = Path(__file__).parent / "_runs" / f"large_{uuid.uuid4().hex}"
    source = root / "source"
    backup = root / "backup"
    source.mkdir(parents=True)
    target = source / "large_256MiB.bin"
    digest = hashlib.sha256()
    with target.open("wb") as stream:
        for _ in range(256):
            block = os.urandom(1024 * 1024)
            stream.write(block)
            digest.update(block)
    settings = Settings(backup_root=backup, copy_chunk_size=1024 * 1024, archive_chunk_size=1024 * 1024, flush_bytes=32 * 1024 * 1024)
    logger = logging.getLogger("large-test")
    logger.addHandler(logging.StreamHandler())
    result = copy_usb_tree(source, "LARGE_SIM", settings, logger)
    copied = result.job_dir / target.name
    copied_hash = hashlib.sha256()
    with copied.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            copied_hash.update(block)
    copied_digest = copied_hash.hexdigest()
    if copied_digest != digest.hexdigest():
        raise AssertionError("copied SHA-256 mismatch")
    archive = create_archive(result, settings, logger)
    with zipfile.ZipFile(archive) as zf:
        if zf.getinfo(target.name).file_size != target.stat().st_size:
            raise AssertionError("ZIP member size mismatch")
    print(f"PASS bytes={target.stat().st_size} chunks=256 zip_bytes={archive.stat().st_size}")
    resolved = root.resolve()
    runs = (Path(__file__).parent / "_runs").resolve()
    if resolved.parent != runs:
        raise AssertionError("unsafe cleanup path")
    shutil.rmtree(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
