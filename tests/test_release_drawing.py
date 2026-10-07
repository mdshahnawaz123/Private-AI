import unittest
from engines.drawing_engine import DrawingIntelligenceEngine

class DrawingInterpretation(unittest.TestCase):
    def setUp(self):self.engine=DrawingIntelligenceEngine()
    def test_unknown_diameter_radius_units_are_not_assumed(self):
        dimensions=self.engine.extract_dimensions('Ø200 R500')
        self.assertTrue(dimensions)
        self.assertTrue(all(d.unit=='' and d.interpretation_state=='AMBIGUOUS' for d in dimensions))
        self.assertTrue(all(d.verification_state=='REVIEW_REQUIRED' for d in dimensions))
    def test_only_explicit_grid_annotations_and_levels(self):
        elements=self.engine.detect_elements('Grid annotation: A-1. Level 02. Load 50. Pressure 6 bar. Rev B.')
        grids=[e.properties['grid_reference'] for e in elements if e.element_type=='grid']
        self.assertEqual(grids,['A-1'])
        self.assertEqual([e.properties['level_number'] for e in elements if e.element_type=='level'],['02'])
    def test_dimension_values_and_tag_boundaries(self):
        dimensions=self.engine.extract_dimensions('Dimension 6,250 mm. Equipment PR500 D200. Elevation -1.2 m.')
        self.assertEqual([(d.value,d.unit) for d in dimensions],[(6250,'mm'),(-1.2,'m')])
