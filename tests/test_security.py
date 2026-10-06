from __future__ import annotations

import logging
import unittest

from usb_backup_v10.config import Settings
from usb_backup_v10.logging_utils import SecretFilter


class SecurityTests(unittest.TestCase):
    def test_settings_repr_hides_token(self) -> None:
        settings = Settings(refresh_token="very-secret-value")
        self.assertNotIn("very-secret-value", repr(settings))

    def test_log_filter_redacts_token(self) -> None:
        record = logging.LogRecord("x", logging.INFO, "", 1, "refresh_token=very-secret-value", (), None)
        SecretFilter().filter(record)
        self.assertNotIn("very-secret-value", record.getMessage())


if __name__ == "__main__":
    unittest.main()
