"""
Unit and regression tests for Fix 3:
Verifies that DocumentMemory allowlist respects `document_memory_allow_all`.
When True: arbitrary filenames are allowed.
When False: only allowlisted filenames are permitted.
"""
import unittest
from unittest.mock import patch
from config import get_settings
from intelligence.document_memory import is_allowlisted

class TestDocumentMemoryAllowlist(unittest.TestCase):
    def test_arbitrary_filename_allowed_when_allow_all_is_true(self):
        settings = get_settings()
        with patch.object(settings, "document_memory_allow_all", True):
            self.assertTrue(is_allowlisted("arbitrary_engineering_report.pdf"))
            self.assertTrue(is_allowlisted("MEP_drawing_rev3.pdf"))
            self.assertTrue(is_allowlisted("C3085-RPT-3EH6105-FP-0000001(5).pdf"))

    def test_allowlist_enforced_when_allow_all_is_false(self):
        settings = get_settings()
        with patch.object(settings, "document_memory_allow_all", False):
            # Benchmark files in the default allowlist must pass
            self.assertTrue(is_allowlisted("C3085-RPT-3EH6105-FP-0000001(5).pdf"))
            self.assertTrue(is_allowlisted("260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf"))
            
            # Non-allowlisted arbitrary files must be rejected
            self.assertFalse(is_allowlisted("arbitrary_engineering_report.pdf"))
            self.assertFalse(is_allowlisted("random_user_upload.pdf"))

    def test_default_config_setting_is_true(self):
        # By default in config.py, document_memory_allow_all must be True
        settings = get_settings()
        self.assertTrue(getattr(settings, "document_memory_allow_all", False))

if __name__ == "__main__":
    unittest.main()
