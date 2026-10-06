from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileRecord:
    relative_path: str
    expected_bytes: int
    copied_bytes: int
    state: str
    error: str = ""


@dataclass
class CopyResult:
    job_dir: Path
    records: list[FileRecord] = field(default_factory=list)
    interrupted: bool = False
    interruption_reason: str = ""

    @property
    def copied_bytes(self) -> int:
        return sum(item.copied_bytes for item in self.records)

    @property
    def complete_files(self) -> int:
        return sum(item.state == "complete" for item in self.records)

    @property
    def partial_files(self) -> int:
        return sum(item.state == "partial" for item in self.records)


@dataclass
class TaskResult:
    local_backup_created: bool
    partial: bool
    archive_path: Path | None
    uploaded: bool
    upload_pending: bool
    message: str
