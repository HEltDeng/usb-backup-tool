from __future__ import annotations

import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from usb_backup_v10.archive import create_archive, remove_managed_job
from usb_backup_v10.config import Settings
from usb_backup_v10.copy_engine import PARTIAL_SUFFIX, copy_one_file, copy_usb_tree
from usb_backup_v10.errors import ArchiveError
from usb_backup_v10.models import FileRecord


RUNS = Path(__file__).parent / "_runs"
RUNS.mkdir(exist_ok=True)


def logger() -> logging.Logger:
    value = logging.getLogger("v10-tests")
    value.handlers.clear()
    value.addHandler(logging.NullHandler())
    return value


class BoundedReader(io.BytesIO):
    def __init__(self, data: bytes, fail_after_reads: int | None = None) -> None:
        super().__init__(data)
        self.requests: list[int] = []
        self.fail_after_reads = fail_after_reads

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        if self.fail_after_reads is not None and len(self.requests) > self.fail_after_reads:
            raise OSError("设备未就绪")
        return super().read(size)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.backup = self.root / "backup"
        self.source.mkdir()
        self.settings = Settings(
            backup_root=self.backup,
            copy_chunk_size=64 * 1024,
            archive_chunk_size=64 * 1024,
            flush_bytes=128 * 1024,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_small_nested_and_empty_directory_backup(self) -> None:
        (self.source / "a" / "empty").mkdir(parents=True)
        (self.source / "a" / "file.txt").write_bytes(b"hello")
        result = copy_usb_tree(self.source, "SIM", self.settings, logger())
        self.assertFalse(result.interrupted)
        self.assertEqual(1, result.complete_files)
        archive = create_archive(result, self.settings, logger())
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(b"hello", zf.read("a/file.txt"))
            self.assertIn("a/empty/", zf.namelist())

    def test_large_multichunk_copy_never_requests_unbounded_read(self) -> None:
        data = bytes(range(256)) * 4096
        source_file = self.source / "large.bin"
        source_file.write_bytes(data)
        reader = BoundedReader(data)

        def source_opener(*_args, **_kwargs):
            return reader

        destination = self.backup / "large.bin"
        record = copy_one_file(
            source_file, destination, self.settings.copy_chunk_size,
            self.settings.flush_bytes, logger(), source_opener=source_opener,
        )
        self.assertEqual("complete", record.state)
        self.assertGreater(len(reader.requests), 10)
        self.assertTrue(all(size == self.settings.copy_chunk_size for size in reader.requests))
        self.assertEqual(data, destination.read_bytes())

    def test_device_removal_preserves_partial_bytes_and_partial_zip(self) -> None:
        total = 20 * 1024 * 1024
        rescued = 5 * 1024 * 1024
        source_file = self.source / "twenty_gb_model.bin"
        source_file.write_bytes(b"x" * total)

        def interrupted_copier(source, destination, chunk_size, flush_bytes, log):
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
            with partial.open("wb") as stream:
                remaining = rescued
                block = b"x" * chunk_size
                while remaining:
                    piece = block[: min(len(block), remaining)]
                    stream.write(piece)
                    stream.flush()
                    remaining -= len(piece)
            return FileRecord(destination.name + PARTIAL_SUFFIX, total, rescued, "partial", "OSError: 设备未就绪")

        result = copy_usb_tree(self.source, "拔盘模拟", self.settings, logger(), file_copier=interrupted_copier)
        self.assertTrue(result.interrupted)
        partial_files = list(result.job_dir.rglob("*" + PARTIAL_SUFFIX))
        self.assertEqual(1, len(partial_files))
        self.assertEqual(rescued, partial_files[0].stat().st_size)
        archive = create_archive(result, self.settings, logger())
        self.assertTrue(archive.name.endswith("_partial.zip"))
        with zipfile.ZipFile(archive) as zf:
            member = next(name for name in zf.namelist() if name.endswith(PARTIAL_SUFFIX))
            self.assertEqual(rescued, zf.getinfo(member).file_size)
        remove_managed_job(result.job_dir, self.backup, logger())
        self.assertFalse(result.job_dir.exists())
        self.assertTrue(archive.exists())

    def test_write_failure_does_not_create_final_file(self) -> None:
        source_file = self.source / "file.bin"
        source_file.write_bytes(b"x" * 1024)

        class FailingWriter(io.BytesIO):
            def write(self, data: bytes) -> int:
                raise OSError("No space left on device")

        destination = self.backup / "file.bin"
        destination.parent.mkdir()
        record = copy_one_file(
            source_file, destination, 128, 128, logger(),
            target_opener=lambda *_args, **_kwargs: FailingWriter(),
        )
        self.assertEqual("failed", record.state)
        self.assertFalse(destination.exists())

    def test_archive_failure_keeps_recovery_directory(self) -> None:
        (self.source / "file.bin").write_bytes(b"important")
        result = copy_usb_tree(self.source, "SIM", self.settings, logger())
        with mock.patch("usb_backup_v10.archive.zipfile.ZipFile", side_effect=OSError("disk full")):
            with self.assertRaises(ArchiveError):
                create_archive(result, self.settings, logger())
        self.assertTrue(result.job_dir.exists())
        self.assertEqual(b"important", (result.job_dir / "file.bin").read_bytes())

    def test_cleanup_refuses_unmanaged_directory(self) -> None:
        unmanaged = self.backup / "user-data"
        unmanaged.mkdir(parents=True)
        (unmanaged / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(ArchiveError):
            remove_managed_job(unmanaged, self.backup, logger())
        self.assertTrue((unmanaged / "keep.txt").exists())

    def test_rejects_backup_root_inside_source(self) -> None:
        unsafe = Settings(backup_root=self.source / "backup-inside-source")
        with self.assertRaisesRegex(ValueError, "不能位于"):
            copy_usb_tree(self.source, "SIM", unsafe, logger())


if __name__ == "__main__":
    unittest.main()
