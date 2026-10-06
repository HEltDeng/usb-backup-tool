class USBBackupError(Exception):
    """Base error."""


class CopyInterrupted(USBBackupError):
    """The source device disappeared or became unreadable."""


class ArchiveError(USBBackupError):
    """Archive generation failed."""


class UploadError(USBBackupError):
    """Cloud upload failed."""
