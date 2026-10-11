import unittest
from intelligence.answer_guard import publication_issues

class ReleaseUnitGate(unittest.TestCase):
    def test_electrical_flow_thermal_and_prefix_conflicts_are_not_laundered(self):
        sources=[{'source':'spec.pdf','page':1}]
        marker=' [SOURCE: spec.pdf | PAGE 1]'
        for original,wrong in [('24 V','24 A'),('12 kW','12 W'),('6 L/s','6 m3/h'),
                               ('35 °C','35 °F'),('7 MW','7 mW'),('9 MPa','9 mPa')]:
            evidence='[SOURCE: spec.pdf | PAGE 1]\nValue '+original
            with self.subTest(original=original):
                self.assertEqual(publication_issues(original+marker,evidence,sources),[])
                self.assertTrue(publication_issues(wrong+marker,evidence,sources))

    def test_same_number_with_incompatible_unit_is_rejected(self):
        source=[{'source':'drawing.pdf','page':2}]
        evidence='[SOURCE: drawing.pdf | PAGE 2]\nDimension 6250 mm. Pressure 6 bar. Area 12 sqm.'
        marker=' [SOURCE: drawing.pdf | PAGE 2]'
        for claim in ('Dimension 6250 m','Pressure 6 MPa','Area 12 sqft'):
            self.assertIn('Value/unit pair absent from cited page excerpts',publication_issues(claim+marker,evidence,source))
        for claim in ('Dimension **6,250** mm','Pressure 6 bar','Area 12 m²'):
            self.assertEqual(publication_issues(claim+marker,evidence,source),[])
