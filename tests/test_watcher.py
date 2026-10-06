from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from usb_backup_v10.config import Settings
from usb_backup_v10.watcher import DRIVE_FIXED, DRIVE_REMOVABLE, USBWatcher, discover_usb_roots


class WatcherTests(unittest.TestCase):
    def test_removable_and_usb_fixed_are_detected_but_internal_fixed_is_not(self) -> None:
        partitions = [
            SimpleNamespace(mountpoint="E:\\"),
            SimpleNamespace(mountpoint="F:\\"),
            SimpleNamespace(mountpoint="C:\\"),
        ]
        kinds = {"E:\\": DRIVE_REMOVABLE, "F:\\": DRIVE_FIXED, "C:\\": DRIVE_FIXED}
        with mock.patch("usb_backup_v10.watcher.psutil.disk_partitions", return_value=partitions), \
             mock.patch("usb_backup_v10.watcher.usb_fixed_roots", return_value={"F:\\"}), \
             mock.patch("usb_backup_v10.watcher.drive_type", side_effect=lambda path: kinds[str(path).upper()]):
            self.assertEqual([Path("E:\\"), Path("F:\\")], discover_usb_roots())

    def test_periodic_scan_triggers_once_then_again_after_physical_reinsert(self) -> None:
        watcher = USBWatcher(Settings(), logging.getLogger("watcher-test"), processor=lambda *_: None)
        with mock.patch("usb_backup_v10.watcher.discover_usb_roots", side_effect=[[Path("G:\\")], [Path("G:\\")], [], [Path("G:\\")]]), \
             mock.patch.object(watcher, "enqueue") as enqueue:
            watcher.scan()
            watcher.scan()
            watcher.scan()
            watcher.scan()
        self.assertEqual(2, enqueue.call_count)


if __name__ == "__main__":
    unittest.main()
