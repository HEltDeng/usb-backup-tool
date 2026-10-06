from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import unittest

from usb_backup_v10.config import Settings
from usb_backup_v10.copy_engine import MARKER, WRITING_SUFFIX
from usb_backup_v10.service import recover_abandoned_jobs, upload_archive


class ClientSuccess:
    def __init__(self, settings, logger):
        pass

    def upload(self, path):
        return None


class ClientFailure:
    def __init__(self, settings, logger):
        pass

    def upload(self, path):
        raise TimeoutError("simulated timeout")


class ServiceTests(unittest.TestCase):
    def test_missing_token_preserves_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "a.zip"
            archive.write_bytes(b"zip")
            settings = Settings(backup_root=Path(temp), upload_enabled=True)
            self.assertFalse(upload_archive(archive, settings, logging.getLogger("test")))
            self.assertTrue(archive.exists())

    def test_network_failure_preserves_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "a.zip"
            archive.write_bytes(b"zip")
            settings = Settings(backup_root=Path(temp), upload_enabled=True, refresh_token="mock-token")
            self.assertFalse(upload_archive(archive, settings, logging.getLogger("test"), ClientFailure))
            self.assertTrue(archive.exists())

    def test_upload_success_removes_only_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.bin"
            archive = Path(temp) / "a.zip"
            source.write_bytes(b"source")
            archive.write_bytes(b"zip")
            settings = Settings(backup_root=Path(temp), upload_enabled=True, refresh_token="mock-token")
            self.assertTrue(upload_archive(archive, settings, logging.getLogger("test"), ClientSuccess))
            self.assertFalse(archive.exists())
            self.assertTrue(source.exists())

    def test_next_start_recovers_crash_leftover_to_partial_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = root / "old_job"
            job.mkdir()
            (job / MARKER).write_text("managed", encoding="utf-8")
            (job / ("large.bin" + WRITING_SUFFIX)).write_bytes(b"rescued bytes")
            settings = Settings(backup_root=root)
            recover_abandoned_jobs(settings, logging.getLogger("test"))
            self.assertFalse(job.exists())
            archives = list(root.glob("*_partial.zip"))
            self.assertEqual(1, len(archives))


if __name__ == "__main__":
    unittest.main()
