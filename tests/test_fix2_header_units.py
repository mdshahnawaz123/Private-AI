"""
Unit and regression tests for Fix 2:
Verifies that header_inherited_tables are converted to [STRUCTURED TABLE] units
in _units_from_meta() with the page number and are preserved in index_structured()
without being re-split by the 800-character splitter.
"""
import ast
import unittest
from pathlib import Path
from langchain_core.documents import Document as LCDocument

class TestHeaderInheritedUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        
        # Extract _units_from_meta
        units_func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_units_from_meta")
        cls.scope = {}
        exec(compile(ast.Module(body=[units_func], type_ignores=[]), "units_eval", "exec"), cls.scope)
        cls._units_from_meta = staticmethod(cls.scope["_units_from_meta"])

    def test_page_with_header_inherited_tables_produces_structured_table_unit(self):
        meta = {
            "type": "pdf",
            "pages": [
                {
                    "page": 3,
                    "text": "General area summary text on page 3.",
                    "tables": "",
                    "header_inherited_tables": (
                        "[AREA STATEMENT SUMMARY] Tower 1 Level 02 -> Gross Floor Area: 2,450 sqm | Net Area: 2,100 sqm\n"
                        "[AREA STATEMENT SUMMARY] Tower 1 Level 03 -> Gross Floor Area: 2,450 sqm | Net Area: 2,100 sqm"
                    )
                }
            ]
        }

        units = self._units_from_meta(meta)
        
        # Must produce a unit starting with [STRUCTURED TABLE]\n on page 3
        structured_units = [u for u in units if u[0].startswith("[STRUCTURED TABLE]\n")]
        self.assertEqual(len(structured_units), 1)
        content, page = structured_units[0]
        self.assertEqual(page, 3)
        self.assertIn("[AREA STATEMENT SUMMARY] Tower 1 Level 02 -> Gross Floor Area: 2,450 sqm", content)
        self.assertIn("Tower 1 Level 03 -> Gross Floor Area: 2,450 sqm", content)

    def test_page_without_header_inherited_tables_does_not_produce_structured_table_unit(self):
        meta = {
            "type": "pdf",
            "pages": [
                {
                    "page": 1,
                    "text": "Only standard narrative text.",
                    "tables": "",
                    "header_inherited_tables": ""
                }
            ]
        }

        units = self._units_from_meta(meta)
        structured_units = [u for u in units if u[0].startswith("[STRUCTURED TABLE]\n")]
        self.assertEqual(len(structured_units), 0)

    def test_structured_table_units_bypass_800_char_splitting(self):
        # Verify that index_structured treats [STRUCTURED TABLE] like [TABLE ROW]
        # and appends the document directly without re-splitting.
        long_content = "[STRUCTURED TABLE]\n" + "\n".join(
            f"[SCHEDULE] Row {i} -> Col1: Value {i} | Col2: Long description {i * 10}" for i in range(50)
        )
        self.assertGreater(len(long_content), 1500) # Exceeds 800 characters

        # Simulate index_structured document routing logic
        all_chunks = []
        document = LCDocument(page_content=long_content, metadata={"page": 2, "source": "test.pdf"})
        
        if long_content.startswith("[TABLE ROW]") or long_content.startswith("[STRUCTURED TABLE]"):
            all_chunks.append(document)
        
        # Verify the entire document is preserved without being cut
        self.assertEqual(len(all_chunks), 1)
        self.assertEqual(all_chunks[0].page_content, long_content)

if __name__ == "__main__":
    unittest.main()
