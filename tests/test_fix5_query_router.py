"""
Unit and regression tests for Fix 5:
Verifies that /ask_stream and /api/query_document share one query routing
service (QueryRouter) and produce identical verified answers while keeping
their respective streaming (SSE) and JSON response contracts unchanged.
"""
import ast
import json
import unittest
from pathlib import Path
import db
from services.query_router import QueryRouter, RouteResult
from intelligence.document_query import query_document

class TestQueryRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.admin = db.get_user_by_username("system") or db.create_user("system", "pw", role="admin")
        
        with db.SessionLocal() as s:
            proj = s.query(db.Project).filter_by(name="Fix5_Project").first()
            if not proj:
                proj = db.Project(name="Fix5_Project")
                s.add(proj)
                s.commit()
            cls.pid = proj.id

            # Add a StructuredRecord for Tower 7 Level 02 GFA
            s.query(db.StructuredRecord).filter_by(project_id=cls.pid).delete()
            s.add(db.StructuredRecord(
                project_id=cls.pid,
                doc="schedule.pdf",
                page=6,
                tower="7",
                level="02",
                entity="TOWER 7 LEVEL 02",
                field="Floor GFA (sqm)",
                raw_value="2054",
                value=2054.0,
                unit="sqm",
                confidence="HIGH",
                source_type="PDF_TEXT"
            ))
            s.commit()

        # Record document metadata so db.list_documents finds it
        db.record_document("Fix5_Project", "schedule.pdf", "data/docs/Fix5_Project/schedule.pdf", 6, user=cls.admin)
        with db.SessionLocal() as s:
            d = s.query(db.Document).filter_by(project_id=cls.pid, filename="schedule.pdf").first()
            if d:
                d.status = "ready"
                d.chunks = 5
            s.commit()

    @classmethod
    def tearDownClass(cls):
        with db.SessionLocal() as s:
            s.query(db.StructuredRecord).filter_by(project_id=cls.pid).delete()
            s.commit()

    def test_query_router_structured_route(self):
        result = QueryRouter.route_query(
            project="Fix5_Project",
            question="Tower 7 Level 02 GFA",
            user=self.admin
        )
        self.assertEqual(result.route, "structured")
        self.assertEqual(result.status, "SUCCESS")
        self.assertTrue(result.is_deterministic)
        self.assertIn("2,054", result.answer)
        self.assertTrue(any(p.get("value") == 2054.0 for p in result.provenance))

    def test_query_router_rag_fallback_route(self):
        result = QueryRouter.route_query(
            project="Fix5_Project",
            question="What is the general fire safety strategy?",
            user=self.admin,
            retrieve_context_func=lambda proj, q, k, u, fs: ([{"source": "spec.pdf", "page": 1}], "Fire strategy excerpt")
        )
        self.assertEqual(result.route, "rag")
        self.assertFalse(result.is_deterministic)
        self.assertEqual(result.context, "Fire strategy excerpt")

    def test_query_document_and_query_router_produce_same_verified_answer(self):
        # 1. Direct QueryRouter call
        router_res = QueryRouter.route_query(
            project="Fix5_Project",
            question="Tower 7 Level 02 GFA",
            user=self.admin
        )

        # 2. Call via intelligence.document_query.query_document
        def mock_retrieve(proj, q, k=8, user=None):
            return [], ""

        def mock_qwen(prompt):
            return "Should not be called for structured query", 0.0

        doc_resp, timings = query_document(
            question="Tower 7 Level 02 GFA",
            project_id="Fix5_Project",
            retrieve_context_func=mock_retrieve,
            call_qwen_func=mock_qwen,
            user_context={"user": self.admin}
        )

        # Verify exact same verified answers and status
        self.assertEqual(router_res.status, doc_resp["status"])
        self.assertEqual(router_res.answer, doc_resp["answer"])
        self.assertEqual(router_res.route, doc_resp["route"])

    def test_ask_stream_in_main_imports_and_uses_query_router(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        
        # Check that ask_stream body imports and calls QueryRouter.route_query
        ask_func = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "ask_stream")
        found_import = False
        found_call = False
        for node in ast.walk(ask_func):
            if isinstance(node, ast.ImportFrom) and node.module == "services.query_router":
                found_import = True
            if isinstance(node, ast.Attribute) and node.attr == "route_query":
                found_call = True
        self.assertTrue(found_import, "ask_stream must import QueryRouter from services.query_router")
        self.assertTrue(found_call, "ask_stream must invoke QueryRouter.route_query")

    def test_borderline_ambiguous_query_returns_all_candidates(self):
        # Insert 2 conflicting records for Tower 7 Level 03 GFA across 2 revisions
        with db.SessionLocal() as s:
            s.add(db.StructuredRecord(
                project_id=self.pid,
                doc="schedule_rev_a.pdf",
                page=2,
                revision="Rev A",
                tower="7",
                level="03",
                entity="TOWER 7 LEVEL 03",
                field="Floor GFA (sqm)",
                raw_value="1850",
                value=1850.0,
                unit="sqm",
                confidence="HIGH",
                source_type="PDF_TEXT"
            ))
            s.add(db.StructuredRecord(
                project_id=self.pid,
                doc="schedule_rev_b.pdf",
                page=4,
                revision="Rev B",
                tower="7",
                level="03",
                entity="TOWER 7 LEVEL 03",
                field="Floor GFA (sqm)",
                raw_value="1920",
                value=1920.0,
                unit="sqm",
                confidence="HIGH",
                source_type="PDF_TEXT"
            ))
            s.commit()

        # Record documents so permission check sees them
        db.record_document("Fix5_Project", "schedule_rev_a.pdf", "data/docs/Fix5_Project/schedule_rev_a.pdf", 2, user=self.admin)
        db.record_document("Fix5_Project", "schedule_rev_b.pdf", "data/docs/Fix5_Project/schedule_rev_b.pdf", 4, user=self.admin)
        with db.SessionLocal() as s:
            for fn in ["schedule_rev_a.pdf", "schedule_rev_b.pdf"]:
                d = s.query(db.Document).filter_by(project_id=self.pid, filename=fn).first()
                if d:
                    d.status = "ready"
                    d.chunks = 2
            s.commit()

        result = QueryRouter.route_query(
            project="Fix5_Project",
            question="Tower 7 Level 03 GFA",
            user=self.admin
        )

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertTrue(result.is_deterministic)
        # Verify UI returns ALL candidates, not just the first one
        self.assertIn("1,850", result.answer)
        self.assertIn("1,920", result.answer)
        self.assertIn("schedule_rev_a.pdf", result.answer)
        self.assertIn("schedule_rev_b.pdf", result.answer)
        self.assertEqual(len(result.sources), 2)
        self.assertTrue(any(s.get("source") == "schedule_rev_a.pdf" for s in result.sources))
        self.assertTrue(any(s.get("source") == "schedule_rev_b.pdf" for s in result.sources))

if __name__ == "__main__":
    unittest.main()
