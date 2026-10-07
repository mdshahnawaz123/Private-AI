import unittest
from intelligence.answer_guard import publication_issues

class IdentifierGuardTests(unittest.TestCase):
    def test_tag_is_not_verified_by_numeric_suffix_alone(self):
        source=[{'source':'maintenance.pdf','page':60}]
        evidence='[SOURCE: maintenance.pdf | PAGE 60]\nEquipment identifier SYNTH-060.'
        marker=' [SOURCE: maintenance.pdf | PAGE 60]'
        self.assertIn('Identifier absent from cited page excerpts',publication_issues('Identifier SYN-060'+marker,evidence,source))
        self.assertEqual(publication_issues('Identifier SYNTH-060'+marker,evidence,source),[])
        self.assertTrue(publication_issues('Identifier SYNTH-060',evidence,source))
        self.assertIn('Identifier absent from cited page excerpts',publication_issues('Identifier SYNTH060'+marker,evidence,source))
