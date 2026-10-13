"""
Unit tests for intelligence/visualization_schema.py.
Verifies:
- Valid chart specifications (pie, donut, bar, line, stacked_bar)
- Invalid chart types, labels, numeric types, and missing data
- Edge cases: negative pie slices, mismatched series lengths, NaNs
- Markdown codeblock extraction
- Evidence reference schema validation
"""
import unittest
from intelligence.visualization_schema import (
    validate_chart_spec,
    validate_evidence_reference,
    extract_chart_specs_from_text,
    VALID_CHART_TYPES,
)


class TestVisualizationSchema(unittest.TestCase):
    def test_valid_pie_chart(self):
        spec = {
            "chart_type": "pie",
            "title": "Area Breakdown",
            "units": "sqm",
            "data": [
                {"name": "Residential", "value": 4500},
                {"name": "Commercial", "value": 1500},
                {"name": "Circulation", "value": 800},
            ],
            "percentage": True,
        }
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(sanitized["chart_type"], "pie")
        self.assertEqual(len(sanitized["data"]), 3)
        self.assertTrue(sanitized["percentage"])

    def test_valid_donut_chart(self):
        spec = {
            "chart_type": "donut",
            "title": "Energy Consumption",
            "data": [
                {"name": "HVAC", "value": 120.5},
                {"name": "Lighting", "value": 45.2},
            ],
        }
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertTrue(ok)
        self.assertEqual(sanitized["chart_type"], "donut")

    def test_valid_bar_chart(self):
        spec = {
            "chart_type": "bar",
            "title": "Concrete Volumes by Level",
            "categories": ["L1", "L2", "L3", "L4"],
            "series": [
                {"name": "Volume (m3)", "data": [450, 520, 510, 490]}
            ],
            "units": "m³",
        }
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertTrue(ok)
        self.assertEqual(sanitized["chart_type"], "bar")
        self.assertEqual(len(sanitized["categories"]), 4)

    def test_valid_line_chart(self):
        spec = {
            "chart_type": "line",
            "title": "Deflection History",
            "categories": ["Day 1", "Day 7", "Day 14", "Day 28"],
            "series": [
                {"name": "Beam A", "data": [0.5, 1.8, 3.2, 4.0]},
                {"name": "Beam B", "data": [0.3, 1.2, 2.5, 3.1]},
            ],
        }
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertTrue(ok)
        self.assertEqual(len(sanitized["series"]), 2)

    def test_valid_stacked_bar_chart(self):
        spec = {
            "chart_type": "stacked_bar",
            "title": "Floor Area by Usage",
            "categories": ["Tower A", "Tower B"],
            "series": [
                {"name": "Retail", "data": [2000, 1500], "stack": "total"},
                {"name": "Office", "data": [6000, 8000], "stack": "total"},
            ],
        }
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertTrue(ok)
        self.assertEqual(sanitized["chart_type"], "stacked_bar")
        self.assertEqual(sanitized["series"][0]["stack"], "total")

    def test_invalid_chart_type(self):
        spec = {"chart_type": "radar", "title": "Test", "data": []}
        ok, sanitized, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("Unsupported chart_type", err)

    def test_invalid_empty_categories_in_bar(self):
        spec = {
            "chart_type": "bar",
            "title": "Test",
            "categories": [],
            "series": [{"name": "S1", "data": [10]}],
        }
        ok, _, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("requires a non-empty 'categories' list", err)

    def test_mismatched_series_and_categories_length(self):
        spec = {
            "chart_type": "bar",
            "title": "Test",
            "categories": ["Cat 1", "Cat 2"],
            "series": [{"name": "S1", "data": [10, 20, 30]}],  # 3 items vs 2 categories
        }
        ok, _, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("does not match categories length", err)

    def test_non_numeric_values_rejected(self):
        spec = {
            "chart_type": "bar",
            "title": "Test",
            "categories": ["Cat 1"],
            "series": [{"name": "S1", "data": ["twenty"]}],
        }
        ok, _, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("non-numeric", err)

    def test_negative_pie_values_rejected(self):
        spec = {
            "chart_type": "pie",
            "title": "Test",
            "data": [{"name": "Part A", "value": -50}],
        }
        ok, _, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("negative value", err)

    def test_zero_total_pie_values_rejected(self):
        spec = {
            "chart_type": "pie",
            "title": "Test",
            "data": [{"name": "Part A", "value": 0}, {"name": "Part B", "value": 0}],
        }
        ok, _, err = validate_chart_spec(spec)
        self.assertFalse(ok)
        self.assertIn("greater than 0", err)

    def test_extract_chart_specs_from_markdown(self):
        md_text = """
Here is the breakdown of areas based on Sheet A-101:

```chart
{
  "chart_type": "pie",
  "title": "Gross Area Distribution",
  "data": [
    {"name": "Offices", "value": 12000},
    {"name": "Retail", "value": 3500}
  ]
}
```

And here is an invalid one that must be ignored:
```chart
{
  "chart_type": "unsupported_type",
  "data": []
}
```
"""
        extracted = extract_chart_specs_from_text(md_text)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["chart_type"], "pie")
        self.assertEqual(extracted[0]["title"], "Gross Area Distribution")

    def test_evidence_reference_validation(self):
        # Valid reference
        ok, ref, err = validate_evidence_reference({
            "filename": "Structural_Calc.pdf",
            "page": 5,
            "bounding_box": [50.0, 100.0, 300.0, 150.0],
            "snippet": "Concrete compressive strength f'c = 40 MPa",
        })
        self.assertTrue(ok)
        self.assertEqual(ref["page"], 5)
        self.assertEqual(ref["match_type"], "exact")

        # Invalid page
        ok, _, err = validate_evidence_reference({
            "filename": "Structural_Calc.pdf",
            "page": -1,
        })
        self.assertFalse(ok)
        self.assertIn("Page number must be a positive integer", err)

        # Invalid bounding box coordinate ordering
        ok, _, err = validate_evidence_reference({
            "filename": "doc.pdf",
            "page": 1,
            "bounding_box": [200.0, 100.0, 50.0, 150.0],  # x0 > x1
        })
        self.assertFalse(ok)
        self.assertIn("ordering", err)


if __name__ == "__main__":
    unittest.main()
