import unittest
from intelligence.document_focus import named_document

class NamedDocumentTests(unittest.TestCase):
    def test_unique_explicit_name_and_ambiguity(self):
        docs=[{'filename':'a.pdf','path':'allowed/a.pdf'},{'filename':'b.pdf','path':'allowed/b.pdf'}]
        self.assertEqual(named_document('page 60 of A.PDF?',docs),docs[0])
        self.assertIsNone(named_document('compare a.pdf and b.pdf',docs))
        self.assertIsNone(named_document('page 60 of private.pdf',docs))
        self.assertIsNone(named_document('page 60 of extra-a.pdf',docs))

    def test_unique_document_code_focuses_matching_document(self):
        docs=[{'filename':'260610_C3045_2VA_PROJECT_DATA_SHEET.pdf','path':'allowed/datasheet.pdf'},
              {'filename':'C3085_FIRE_REPORT.pdf','path':'allowed/fire.pdf'}]
        self.assertEqual(named_document('What plot number is listed in the C3045 project data sheet?',docs),docs[0])

    def test_ambiguous_document_code_does_not_silently_choose_a_source(self):
        docs=[{'filename':'C3045_DATA_SHEET.pdf','path':'allowed/datasheet.pdf'},
              {'filename':'C3045_REVISION_REGISTER.pdf','path':'allowed/register.pdf'}]
        self.assertIsNone(named_document('What is listed for C3045?',docs))

    def test_document_description_resolves_one_file_among_same_code(self):
        docs=[{'filename':'260610_C3045_PROJECT_DATA_SHEET.pdf','path':'allowed/datasheet.pdf'},
              {'filename':'C3045_REVISION_REGISTER.pdf','path':'allowed/register.pdf'}]
        self.assertEqual(named_document('What plot number is listed in the C3045 project data sheet?',docs),docs[0])

    def test_multiple_document_codes_are_not_collapsed_to_one_focus(self):
        docs=[{'filename':'C3045_PROJECT_DATA_SHEET.pdf','path':'allowed/a.pdf'},
              {'filename':'C3085_FIRE_REPORT.pdf','path':'allowed/b.pdf'}]
        self.assertIsNone(named_document('Compare C3045 and C3085',docs))
