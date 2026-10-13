"""
Unit and regression tests for Fix 4:
Verifies that schedule questions query db.ScheduleRow and db.StructuredRecord
generally in retrieve_context(), while preserving existing TOS/TOPR and legend
(e.g., LX-PT) behaviors.
"""
import ast
import unittest
from pathlib import Path
import db

class TestScheduleRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        
        # Extract retrieve_context
        rc_func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "retrieve_context")
        class MockVS:
            def similarity_search(self, *a, **k):
                return []

        cls.scope = {
            "db": db,
            "get_vectorstore": lambda proj: MockVS() if proj != "building_codes" else None,
            "KB_COLLECTION": "building_codes",
            "logger": type("Logger", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "revision_notice": lambda p, u: None,
        }
        exec(compile(ast.Module(body=[rc_func], type_ignores=[]), "retrieve_context_eval", "exec"), cls.scope)
        cls.retrieve_context = staticmethod(cls.scope["retrieve_context"])

        # Create test project and rows in db
        db.init_db()
        with db.SessionLocal() as s:
            proj = s.query(db.Project).filter_by(name="Fix4_Test_Project").first()
            if not proj:
                proj = db.Project(name="Fix4_Test_Project")
                s.add(proj)
                s.commit()
            cls.proj_id = proj.id

            # Clean previous test entries
            s.query(db.Quantity).filter_by(project_id=cls.proj_id).delete()
            s.query(db.ScheduleRow).filter_by(project_id=cls.proj_id).delete()
            s.query(db.StructuredRecord).filter_by(project_id=cls.proj_id).delete()

            # 1. Quantity for TOS
            s.add(db.Quantity(
                project_id=cls.proj_id,
                building="Tower 1",
                metric="TOS",
                value="+15.200",
                unit="m",
                source_doc="structural_drawings.pdf",
                source_page=2,
            ))

            # 2. ScheduleRow for Legend LX-PT
            s.add(db.ScheduleRow(
                project_id=cls.proj_id,
                doc="legend.pdf",
                page=1,
                table_name="STRUCTURAL LEGEND",
                row_key="LX-PT",
                row_values={"Code": "LX-PT", "Description": "Post-Tensioned Slab"}
            ))

            # 3. ScheduleRow for general element mark C-1
            s.add(db.ScheduleRow(
                project_id=cls.proj_id,
                doc="column_sched.pdf",
                page=4,
                table_name="COLUMN SCHEDULE",
                row_key="C-1",
                row_values={"Mark": "C-1", "Concrete Grade": "C50", "Size": "600x600"}
            ))

            # 4. StructuredRecord for Tower & Level (Tower 7 Level 02 GFA)
            s.add(db.StructuredRecord(
                project_id=cls.proj_id,
                doc="area_schedule.pdf",
                page=6,
                schedule="AREA STATEMENT",
                tower="7",
                level="02",
                entity="TOWER 7 LEVEL 02",
                field="Floor GFA (sqm)",
                raw_value="2054",
                value=2054.0,
                unit="sqm",
                confidence="HIGH"
            ))

            # 5. KnowledgeHub Requirement
            s.add(db.Requirement(
                project_id=cls.proj_id,
                req_id="REQ-CORR-01",
                title="Corridor Width",
                description="Minimum clear corridor width for primary egress",
                value="1200",
                unit="mm",
                source_doc="architectural_code.pdf",
                source_page=14,
                source_clause="Section 1005.1",
                status="published"
            ))

            s.commit()

    @classmethod
    def tearDownClass(cls):
        with db.SessionLocal() as s:
            s.query(db.Quantity).filter_by(project_id=cls.proj_id).delete()
            s.query(db.ScheduleRow).filter_by(project_id=cls.proj_id).delete()
            s.query(db.StructuredRecord).filter_by(project_id=cls.proj_id).delete()
            s.query(db.Requirement).filter_by(project_id=cls.proj_id).delete()
            s.commit()

    def test_tos_query_retrieves_quantity_structured_data(self):
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What is the TOS level for tower 1?", 8)
        self.assertIn("STRUCTURED DATA", ctx)
        self.assertIn("QUANTITY: TOS", ctx)
        self.assertIn("+15.200 m", ctx)
        self.assertTrue(any(s.get("source") == "structural_drawings.pdf" for s in srcs))

    def test_legend_query_retrieves_schedule_row(self):
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What does code LX-PT specify?", 8)
        self.assertIn("STRUCTURED DATA", ctx)
        self.assertIn("STRUCTURAL LEGEND", ctx)
        self.assertIn("LX-PT", ctx)
        self.assertIn("Post-Tensioned Slab", ctx)

    def test_mark_code_query_retrieves_schedule_row_generally(self):
        # Column mark C-1 was not matched by old TOS/TOPR regex
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What is the concrete grade for column C-1?", 8)
        self.assertIn("STRUCTURED DATA", ctx)
        self.assertIn("COLUMN SCHEDULE", ctx)
        self.assertIn("C-1", ctx)
        self.assertIn("C50", ctx)

    def test_tower_and_level_query_retrieves_structured_record_generally(self):
        # StructuredRecord was not previously queried in retrieve_context
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What is the Floor GFA for Tower 7 Level 02?", 8)
        self.assertIn("STRUCTURED DATA", ctx)
        self.assertIn("TOWER 7 LEVEL 02", ctx)
        self.assertIn("Floor GFA (sqm): 2054", ctx)

    def test_non_schedule_query_does_not_inject_spurious_structured_data(self):
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What are the fire exit travel distance limits?", 8)
        self.assertNotIn("STRUCTURED DATA", ctx)

    def test_exclusion_list_page_and_figure_creates_no_structured_lookups(self):
        # "page 5" and "figure 3" must be caught by exclusion list and NOT trigger DB lookups
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What is on page 5 and figure 3?", 8)
        self.assertNotIn("STRUCTURED DATA", ctx)
        self.assertEqual(len(srcs), 0)

    def test_five_real_engineering_queries_produce_no_false_positive_structured_injection(self):
        # 5 real non-benchmark engineering queries to confirm no noise rows are injected
        real_queries = [
            "What is the fire resistance rating for 2 hour exit stairwell enclosures?",
            "How many accessible parking spaces are required for a 500 space lot?",
            "What is the minimum clear ceiling height in habitable rooms?",
            "Check if the slope of the access ramp exceeds 1:12",
            "What are the travel distance limits to the nearest exit discharge?",
        ]
        for q in real_queries:
            with self.subTest(query=q):
                srcs, ctx = self.retrieve_context("Fix4_Test_Project", q, 8)
                self.assertNotIn("STRUCTURED DATA", ctx, f"False positive structured injection for query: {q}")

    def test_knowledge_hub_requirement_retrieval(self):
        # Query matching KnowledgeHub requirement title/clause
        srcs, ctx = self.retrieve_context("Fix4_Test_Project", "What is the requirement for corridor width?", 8)
        self.assertIn("STRUCTURED DATA", ctx)
        self.assertIn("KNOWLEDGE REQUIREMENT: REQ-CORR-01", ctx)
        self.assertIn("1200 mm", ctx)
        self.assertTrue(any(s.get("source") == "architectural_code.pdf" and s.get("page") == 14 for s in srcs))


if __name__ == "__main__":
    unittest.main()
