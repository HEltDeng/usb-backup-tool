from __future__ import annotations

import ctypes
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Callable

import psutil
import pythoncom
import win32api
import win32con
import win32gui
import win32com.client

from .config import Settings
from .service import process_drive, recover_abandoned_jobs, retry_pending_archives


DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004


def drive_type(root: Path) -> int:
    return int(ctypes.windll.kernel32.GetDriveTypeW(str(root)))


def volume_info(root: Path) -> tuple[str, int]:
    label = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(str(root), label, len(label), ctypes.byref(serial), None, None, None, 0)
    return (label.value, int(serial.value)) if ok else ("", 0)


def usb_fixed_roots() -> set[str]:
    """Map physical USB disks to drive letters; required for USB SSD/HDD devices."""
    pythoncom.CoInitialize()
    roots: set[str] = set()
    try:
        service = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", r"root\cimv2")
        for disk in service.ExecQuery("SELECT DeviceID, InterfaceType, PNPDeviceID FROM Win32_DiskDrive"):
            interface = str(getattr(disk, "InterfaceType", "")).upper()
            pnp = str(getattr(disk, "PNPDeviceID", "")).upper()
            if interface != "USB" and not pnp.startswith("USBSTOR\\"):
                continue
            for partition in disk.Associators_("Win32_DiskDriveToDiskPartition"):
                for logical in partition.Associators_("Win32_LogicalDiskToPartition"):
                    roots.add(str(logical.DeviceID).upper() + "\\")
    except Exception:
        return set()
    finally:
        pythoncom.CoUninitialize()
    return roots


def discover_usb_roots() -> list[Path]:
    fixed = usb_fixed_roots()
    found: set[str] = set()
    for partition in psutil.disk_partitions(all=True):
        root = str(partition.mountpoint).rstrip("\\/").upper() + "\\"
        try:
            if drive_type(Path(root)) == DRIVE_REMOVABLE or root in fixed:
                found.add(root)
        except OSError:
            continue
    return [Path(root) for root in sorted(found)]


class USBWatcher:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        processor: Callable[[Path, str, Settings, logging.Logger], object] = process_drive,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.processor = processor
        self.tasks: queue.Queue[tuple[Path, str, tuple[str, int]]] = queue.Queue()
        self.lock = threading.Lock()
        self.pending: set[tuple[str, int]] = set()
        self.present: set[str] = set()
        self.last_started: dict[tuple[str, int], float] = {}
        self._wndproc_ref = self._wndproc

    def _identity(self, root: Path) -> tuple[str, int]:
        _, serial = volume_info(root)
        return ("serial", serial) if serial else ("drive", ord(root.drive[0].upper()))

    def scan(self) -> None:
        roots = discover_usb_roots()
        current = {str(root).upper() for root in roots}
        with self.lock:
            new = current - self.present
            self.present = current
        for root in roots:
            if str(root).upper() in new:
                self.enqueue(root)

    def enqueue(self, root: Path) -> None:
        if not root.exists():
            return
        label, _ = volume_info(root)
        identity = self._identity(root)
        now = time.monotonic()
        with self.lock:
            if identity in self.pending:
                return
            if now - self.last_started.get(identity, 0.0) < self.settings.debounce_seconds:
                return
            self.pending.add(identity)
            self.last_started[identity] = now
        self.tasks.put((root, label, identity))
        self.logger.info("U盘任务进入严格串行队列: %s | identity=%s", root, identity)

    def _worker(self) -> None:
        recover_abandoned_jobs(self.settings, self.logger)
        retry_pending_archives(self.settings, self.logger)
        while True:
            root, label, identity = self.tasks.get()
            try:
                self.processor(root, label, self.settings, self.logger)
            except Exception:
                self.logger.error("任务顶层异常已隔离，监听继续运行", exc_info=True)
            finally:
                with self.lock:
                    self.pending.discard(identity)
                self.tasks.task_done()

    def _poller(self) -> None:
        while True:
            try:
                self.scan()
            except Exception:
                self.logger.error("USB 周期扫描异常", exc_info=True)
            time.sleep(max(0.5, self.settings.scan_interval_seconds))

    def _event_rescan(self) -> None:
        for delay in (0.5, 2.0, 5.0, 8.0):
            time.sleep(delay)
            self.scan()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DEVICECHANGE and wparam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE):
            threading.Thread(target=self._event_rescan, daemon=True).start()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def run(self) -> None:
        threading.Thread(target=self._worker, name="usb-v10-worker", daemon=True).start()
        threading.Thread(target=self._poller, name="usb-v10-poller", daemon=True).start()
        instance = win32api.GetModuleHandle(None)
        class_name = "USBBackupV10HiddenWindow"
        window_class = win32gui.WNDCLASS()
        window_class.lpfnWndProc = self._wndproc_ref
        window_class.lpszClassName = class_name
        window_class.hInstance = instance
        try:
            win32gui.RegisterClass(window_class)
        except win32gui.error:
            pass
        win32gui.CreateWindow(class_name, "USBBackupV10", 0, -32000, -32000, 0, 0, 0, 0, instance, None)
        self.logger.info("WM_DEVICECHANGE + 轮询双通道监听已启动，任务严格串行")
        win32gui.PumpMessages()
