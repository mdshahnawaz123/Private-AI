import unittest
from intelligence.document_focus import named_document

class NamedDocumentTests(unittest.TestCase):
    def test_unique_explicit_name_and_ambiguity(self):
        docs=[{'filename':'a.pdf','path':'allowed/a.pdf'},{'filename':'b.pdf','path':'allowed/b.pdf'}]
        self.assertEqual(named_document('page 60 of A.PDF?',docs),docs[0])
        self.assertIsNone(named_document('compare a.pdf and b.pdf',docs))
        self.assertIsNone(named_document('page 60 of private.pdf',docs))
        self.assertIsNone(named_document('page 60 of extra-a.pdf',docs))
