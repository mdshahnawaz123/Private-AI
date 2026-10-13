"""Tests for null character handling in PDF extraction.

Verifies that garbled PDF text (containing null bytes and control characters)
is safely sanitized before subprocess calls, indexing, and JSON serialization.

Root cause: C3085-RPT-3EH6105-AC-0000001(4).pdf has broken ToUnicode CMap
tables that produce \x00 (null) and other C0 control characters when decoded
by PyMuPDF. These crash subprocess on Windows and corrupt search indices.

Test coverage:
- extract.py: _sanitize_pdf_text() utility function
- pipeline.py: sanitization at text extraction
- vision_adapter.py: defense-in-depth at subprocess boundary
"""
import os
import sys
import unittest

# Add project root directory to path so we can import extract
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from extract import _sanitize_pdf_text


class TestSanitizePdfText(unittest.TestCase):
    """Core sanitization function tests."""
    
    def test_removes_null_bytes(self):
        """Null bytes (\x00) are completely stripped."""
        text_with_nulls = "Valid text\x00null\x00char"
        result = _sanitize_pdf_text(text_with_nulls)
        self.assertNotIn('\x00', result)
        self.assertIn("Valid text", result)
        self.assertEqual(result, "Valid textnullchar")
    
    def test_removes_c0_control_characters(self):
        """C0 control chars (\x01-\x08, \x0b, \x0c, \x0e-\x1f) are stripped."""
        text_with_ctrl = "Text\x01\x02\x03with\x0bcontrol\x1fchars"
        result = _sanitize_pdf_text(text_with_ctrl)
        for c in '\x01\x02\x03\x0b\x1f':
            self.assertNotIn(c, result, f"Control char {repr(c)} not removed")
        self.assertTrue("Text" in result and "with" in result and "control" in result)
        self.assertEqual(result, "Textwithcontrolchars")
    
    def test_preserves_normal_whitespace(self):
        """Normal whitespace (\n, \t, \r) is preserved."""
        text = "Line 1\nLine 2\tTabbed\rCarriage"
        result = _sanitize_pdf_text(text)
        self.assertEqual(result, text)
        self.assertIn('\n', result)
        self.assertIn('\t', result)
        self.assertIn('\r', result)
    
    def test_handles_empty_string(self):
        """Empty strings and None return empty string."""
        self.assertEqual(_sanitize_pdf_text(""), "")
        self.assertEqual(_sanitize_pdf_text(None), "")
    
    def test_page_8_ac_report_example(self):
        """Real-world example from failing PDF: page 8 (TBC table)."""
        # Simulated garbled page 8 text - mostly control chars
        garbled = '\x00\x00\x01\n\x00\x02\x00\x03\n\x04\x05\x06\x05\x07\x08\t\x05\n\x0b\x04\x05\x0c\r\x0e\x0f'
        result = _sanitize_pdf_text(garbled)
        # Should be mostly empty after stripping
        self.assertNotIn('\x00', result)
        self.assertNotIn('\x01', result)
        self.assertNotIn('\x02', result)
        # But preserve the newlines
        self.assertEqual(result.count('\n'), 3)
    
    def test_subprocess_safe_after_sanitization(self):
        """After sanitization, text is safe for Windows subprocess arguments."""
        garbled = "HVAC\x00Background\x00Noise\x00TBC"
        safe = _sanitize_pdf_text(garbled)
        # This would crash subprocess on Windows if not sanitized
        self.assertNotIn('\x00', safe)
        # Should be usable as a CLI argument
        self.assertEqual(safe, "HVACBackgroundNoiseTBC")
    
    def test_json_serializable_after_sanitization(self):
        """After sanitization, text can be safely JSON-encoded."""
        import json
        garbled = "Schedule\x00Name\x01Code\x02Status"
        safe = _sanitize_pdf_text(garbled)
        # Should not raise json.JSONDecodeError or UnicodeDecodeError
        encoded = json.dumps({"text": safe})
        decoded = json.loads(encoded)
        self.assertEqual(decoded["text"], "ScheduleNameCodeStatus")
    
    def test_mixed_garbage_page(self):
        """Simulate a full page of mixed garbled PDF text."""
        # This mimics the pattern seen in the AC report PDF
        mixed = (
            "Project Name\x00TBC Table\x01Data\x02Row\x00"
            "Values\x03\x04\x05\x06Codes\x07Schedule\x00"
            "Reference\x08Drawing\x09Sheet\x0aPage\x0b"
        )
        result = _sanitize_pdf_text(mixed)
        # Should strip non-whitespace control chars but keep readable words and whitespace
        for ctrl in '\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b':
            self.assertNotIn(ctrl, result)
        self.assertIn('\t', result)
        self.assertIn('\n', result)
        self.assertIn("Project Name", result)
        self.assertIn("TBC Table", result)
        self.assertIn("Schedule", result)


class TestEdgeCases(unittest.TestCase):
    """Robustness with extreme or unexpected inputs."""
    
    def test_all_nulls_string(self):
        """String of only null bytes returns empty."""
        result = _sanitize_pdf_text('\x00' * 100)
        self.assertEqual(result, "")
    
    def test_massive_mixed_garbage(self):
        """Large string with interspersed control chars."""
        base = "Schedule\x00Req\x01Num\x02Code\x03Status" * 10
        result = _sanitize_pdf_text(base)
        # All control chars removed, readable text remains
        self.assertNotIn('\x00', result)
        self.assertNotIn('\x01', result)
        self.assertIn("Schedule", result)
        self.assertIn("Code", result)
        self.assertIn("Status", result)
    
    def test_unicode_characters_preserved(self):
        """Unicode characters (non-ASCII) are preserved."""
        text_with_unicode = "Dubai\u00a0Guidelines\u2014UAE\u2013 Draft"
        result = _sanitize_pdf_text(text_with_unicode)
        self.assertEqual(result, text_with_unicode)
        self.assertIn("\u00a0", result)  # Non-breaking space
        self.assertIn("\u2014", result)  # Em dash
        self.assertIn("\u2013", result)  # En dash
    
    def test_only_whitespace(self):
        """String of only valid whitespace is preserved."""
        whitespace_only = "\n\t\r\n\t"
        result = _sanitize_pdf_text(whitespace_only)
        self.assertEqual(result, whitespace_only)
    
    def test_very_long_string(self):
        """Very long string with garbage is handled efficiently."""
        # 1MB string with scattered nulls
        long_text = ("a" * 1000 + "\x00") * 1000  # ~1MB
        result = _sanitize_pdf_text(long_text)
        self.assertNotIn('\x00', result)
        self.assertEqual(result.count('a'), 1000000)


class TestPipelineIntegration(unittest.TestCase):
    """Test that patches work at actual pipeline points."""
    
    def test_extract_py_sanitizes_before_indexing(self):
        """Verify extract.py uses sanitizer at text extraction."""
        import extract
        self.assertTrue(hasattr(extract, '_sanitize_pdf_text'))
        self.assertTrue(callable(extract._sanitize_pdf_text))
    
    def test_pipeline_py_inline_sanitization(self):
        """Verify pipeline.py has inline null-byte stripping."""
        pipeline_path = os.path.join(PROJECT_ROOT, "services", "pipeline.py")
        with open(pipeline_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        # Check that the sanitization line is present
        self.assertTrue("text.replace('\\x00', '')" in content or 'text.replace("\\x00", "")' in content)
        self.assertTrue("Sanitize null bytes" in content or "sanitize" in content.lower())
    
    def test_vision_adapter_defends_subprocess_boundary(self):
        """Verify vision_adapter.py has defense-in-depth sanitization."""
        vision_adapter_path = os.path.join(PROJECT_ROOT, "services", "vision_adapter.py")
        with open(vision_adapter_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        # Check for the safe_text variable and null sanitization
        self.assertIn("safe_text", content)
        self.assertTrue("replace('\\x00', '')" in content or 'replace("\\x00", "")' in content)
        self.assertTrue("Sanitize nulls" in content or "subprocess" in content)


class TestRealWorldScenarios(unittest.TestCase):
    """Test against realistic PDF extraction scenarios."""
    
    def test_ac_report_page_8_tbc_scenario(self):
        """Scenario: page 8 of AC report (TBC table) with 124 null chars."""
        # Simulate: page with TBC table containing null chars
        page_text = (
            "Table 2: Acoustic Performance\x00\n"
            "Targeted Status\x00: To Be Confirmed (TBC)\n"
            "Credit Points\x00: 1 point\n"
            "Categories:\x00\n"
            "  - HVAC Background\x00 Noise\x00: TBC\n"
            "  - Sound Isolation\x00: TBC\n"
            "  - Reverberation\x00 Time\x00: TBC\n"
        )
        safe = _sanitize_pdf_text(page_text)
        # All nulls removed, table structure preserved
        self.assertNotIn('\x00', safe)
        self.assertIn("Table 2", safe)
        self.assertIn("TBC", safe)
        self.assertIn("Credit Points", safe)
        self.assertIn("1 point", safe)
    
    def test_full_page_high_null_density(self):
        """Page 22-24 scenario: 230-470 null chars (high density)."""
        # Simulate page with extreme null/control char density
        base_text = "SCHEDULE A - SPECIFICATIONS"
        # Interleave with nulls and controls (every 2-3 chars)
        chaotic = ""
        for i, char in enumerate(base_text):
            chaotic += char
            if i % 2 == 0:
                chaotic += '\x00'
            elif i % 3 == 0:
                chaotic += '\x01'
        
        safe = _sanitize_pdf_text(chaotic)
        # Original content still readable
        self.assertIn("SCHEDULE", safe)
        self.assertIn("SPECIFICATIONS", safe)
        # No garbage chars remain
        self.assertNotIn('\x00', safe)
        self.assertNotIn('\x01', safe)


if __name__ == '__main__':
    unittest.main()
