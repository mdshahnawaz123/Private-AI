import unittest
from intelligence.answer_guard import publication_issues

class ReleaseUnitGate(unittest.TestCase):
    def test_same_number_with_incompatible_unit_is_rejected(self):
        source=[{'source':'drawing.pdf','page':2}]
        evidence='[SOURCE: drawing.pdf | PAGE 2]\nDimension 6250 mm. Pressure 6 bar. Area 12 sqm.'
        marker=' [SOURCE: drawing.pdf | PAGE 2]'
        for claim in ('Dimension 6250 m','Pressure 6 MPa','Area 12 sqft'):
            self.assertIn('Value/unit pair absent from cited page excerpts',publication_issues(claim+marker,evidence,source))
        for claim in ('Dimension **6,250** mm','Pressure 6 bar','Area 12 m²'):
            self.assertEqual(publication_issues(claim+marker,evidence,source),[])
