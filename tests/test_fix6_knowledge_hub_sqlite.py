import os
import unittest
import uuid
import db
from knowledge.hub import KnowledgeHub
from knowledge.entities import EntityType
from knowledge.extraction import EntityExtractor


class TestKnowledgeHubSQLite(unittest.TestCase):
    def setUp(self):
        # Create a test project in SQLite so foreign key constraints are satisfied
        self.project_name = f"test_proj_{uuid.uuid4().hex[:8]}"
        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.commit()
            self.project_id = proj.id

    def tearDown(self):
        # Clean up database records
        with db.SessionLocal() as s:
            s.query(db.GraphEdge).filter_by(project_id=self.project_id).delete()
            s.query(db.Evidence).filter_by(project_id=self.project_id).delete()
            s.query(db.Requirement).filter_by(project_id=self.project_id).delete()
            s.query(db.Project).filter_by(id=self.project_id).delete()
            s.commit()

    def test_add_requirement_persists_to_sqlite(self):
        hub = KnowledgeHub(load_db=False)
        req_eid = hub.add_requirement(
            project_id=str(self.project_id),
            req_id="REQ-101",
            title="minimum width",
            value=1200.0,
            unit="mm",
            operator=">=",
            discipline="Architectural",
            source_doc="spec.pdf",
            source_page=3,
            source_clause="4.2.1",
            confidence="high",
            notes="Exit door minimum width",
        )
        self.assertTrue(req_eid.startswith("req-"))

        # Verify record exists in SQLite db.Requirement table
        with db.SessionLocal() as s:
            row = s.query(db.Requirement).filter_by(project_id=self.project_id, req_id="REQ-101").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.title, "minimum width")
            self.assertEqual(row.value, "1200.0")
            self.assertEqual(row.unit, "mm")
            self.assertEqual(row.source_doc, "spec.pdf")
            self.assertEqual(row.source_page, 3)

    def test_add_evidence_persists_to_sqlite(self):
        hub = KnowledgeHub(load_db=False)
        ev_id = "EV-201"
        saved_id = hub.add_evidence(
            project_id=str(self.project_id),
            evidence_type="text",
            content="Door width measured at 1250 mm on site.",
            source_doc="survey.pdf",
            source_page=5,
            confidence=0.95,
            evidence_id=ev_id,
        )
        self.assertEqual(saved_id, ev_id)

        # Verify record exists in SQLite db.Evidence table
        with db.SessionLocal() as s:
            row = s.query(db.Evidence).filter_by(project_id=self.project_id, evidence_id=ev_id).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.evidence_type, "text")
            self.assertIn("1250 mm", row.content)
            self.assertEqual(row.source_page, 5)
            self.assertAlmostEqual(row.confidence, 0.95)

    def test_add_relationship_persists_to_sqlite(self):
        hub = KnowledgeHub(load_db=False)
        ev_id = hub.add_evidence(
            project_id=str(self.project_id),
            evidence_type="text",
            content="Corridor clear width is 1500 mm",
            source_doc="plan.pdf",
            source_page=2,
            confidence=0.9,
            evidence_id="EV-301",
        )
        req_id = hub.add_requirement(
            project_id=str(self.project_id),
            req_id="REQ-301",
            title="corridor width",
            value=1400.0,
            unit="mm",
            source_doc="code.pdf",
            source_page=12,
        )

        rel_ok = hub.add_relationship(ev_id, "supports", req_id, confidence=0.85)
        self.assertTrue(rel_ok)

        # Verify record exists in SQLite db.GraphEdge table
        with db.SessionLocal() as s:
            edge = s.query(db.GraphEdge).filter_by(
                project_id=self.project_id,
                src_id=ev_id,
                dst_id=req_id,
                relation="supports"
            ).first()
            self.assertIsNotNone(edge)
            self.assertEqual(edge.src_id, ev_id)
            self.assertEqual(edge.dst_id, req_id)
            meta = edge.metadata_json or {}
            self.assertAlmostEqual(meta.get("confidence", 0.0), 0.85)

    def test_load_from_sqlite_rehydrates_hub(self):
        # Insert rows directly or via hub A
        hub_a = KnowledgeHub(load_db=False)
        hub_a.add_requirement(
            project_id=str(self.project_id),
            req_id="REQ-401",
            title="ceiling height",
            value=2600.0,
            unit="mm",
            source_doc="arch_code.pdf",
            source_page=7,
        )
        hub_a.add_evidence(
            project_id=str(self.project_id),
            evidence_type="text",
            content="Ceiling height is 2700 mm",
            source_doc="section.pdf",
            source_page=1,
            evidence_id="EV-401",
        )
        hub_a.add_relationship("EV-401", "supports", "req-REQ-401", confidence=0.9)

        # Instantiate fresh hub B and load from SQLite
        hub_b = KnowledgeHub(load_db=False)
        hub_b.load_from_sqlite(project_id=self.project_id)

        req_entity = hub_b.get_entity("req-REQ-401")
        self.assertIsNotNone(req_entity)
        self.assertEqual(req_entity.value, 2600.0)
        self.assertEqual(req_entity.unit, "mm")

        ev_entity = hub_b.get_entity("EV-401")
        self.assertIsNotNone(ev_entity)
        self.assertIn("2700 mm", ev_entity.content)

        edges = hub_b.get_relationships("EV-401", relation="supports")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["target_id"], "req-REQ-401")

    def test_remove_project_purges_sqlite_and_memory(self):
        hub = KnowledgeHub(load_db=False)
        req_id = hub.add_requirement(
            project_id=str(self.project_id),
            req_id="REQ-501",
            title="fire rating",
            value=60.0,
            unit="min",
        )
        ev_id = hub.add_evidence(
            project_id=str(self.project_id),
            evidence_type="text",
            content="Wall fire rating 60 min",
            source_doc="fire.pdf",
            evidence_id="EV-501",
        )
        hub.add_relationship(ev_id, "supports", req_id)

        # Remove project from hub
        hub.remove_project(str(self.project_id))

        # Check in-memory entities are gone
        self.assertIsNone(hub.get_entity(req_id))
        self.assertIsNone(hub.get_entity(ev_id))

        # Check SQLite rows are purged
        with db.SessionLocal() as s:
            self.assertEqual(s.query(db.Requirement).filter_by(project_id=self.project_id).count(), 0)
            self.assertEqual(s.query(db.Evidence).filter_by(project_id=self.project_id).count(), 0)
            self.assertEqual(s.query(db.GraphEdge).filter_by(project_id=self.project_id).count(), 0)

    def test_entity_extractor_populates_sqlite_tables(self):
        meta = {
            "type": "pdf",
            "filename": "building_code_sample.pdf",
            "pages": [
                {
                    "page": 1,
                    "text": "General Building Provisions. Chapter 1 introduces the administrative rules."
                },
                {
                    "page": 2,
                    "text": "Section 1005: Minimum corridor width of 1200 mm shall be provided for egress routes."
                }
            ]
        }

        counts = EntityExtractor.extract_and_index(self.project_id, "building_code_sample.pdf", meta)
        self.assertGreater(counts.get("evidence", 0), 0)
        self.assertGreater(counts.get("requirements", 0), 0)
        self.assertGreater(counts.get("relationships", 0), 0)

        # Verify SQLite has requirements, evidence, and graph edges
        with db.SessionLocal() as s:
            reqs = s.query(db.Requirement).filter_by(project_id=self.project_id).all()
            self.assertGreater(len(reqs), 0)
            self.assertTrue(any("width" in r.title.lower() for r in reqs))

            evs = s.query(db.Evidence).filter_by(project_id=self.project_id).all()
            self.assertGreater(len(evs), 0)
            self.assertTrue(any("building_code_sample.pdf" in e.source_doc for e in evs))

            edges = s.query(db.GraphEdge).filter_by(project_id=self.project_id).all()
            self.assertGreater(len(edges), 0)
            self.assertTrue(any(e.relation == "supports" for e in edges))

    def test_entity_extractor_reindex_purges_stale_records(self):
        # Index initial revision with 2 pages and 2 requirements
        meta_v1 = {
            "type": "pdf",
            "filename": "code_spec.pdf",
            "pages": [
                {"page": 1, "text": "Minimum corridor width of 1200 mm."},
                {"page": 2, "text": "Minimum ceiling height of 2600 mm."},
            ]
        }
        counts_v1 = EntityExtractor.extract_and_index(self.project_id, "code_spec.pdf", meta_v1)
        self.assertEqual(counts_v1["requirements"], 2)

        with db.SessionLocal() as s:
            self.assertEqual(s.query(db.Requirement).filter_by(project_id=self.project_id, source_doc="code_spec.pdf").count(), 2)

        # Re-index revision with only 1 requirement (ceiling height dropped)
        meta_v2 = {
            "type": "pdf",
            "filename": "code_spec.pdf",
            "pages": [
                {"page": 1, "text": "Minimum corridor width of 1500 mm."},
            ]
        }
        counts_v2 = EntityExtractor.extract_and_index(self.project_id, "code_spec.pdf", meta_v2)
        self.assertEqual(counts_v2["requirements"], 1)

        # Confirm old requirements were purged and not accumulated
        with db.SessionLocal() as s:
            reqs = s.query(db.Requirement).filter_by(project_id=self.project_id, source_doc="code_spec.pdf").all()
            self.assertEqual(len(reqs), 1)
            self.assertEqual(reqs[0].value, "1500.0")

    def test_filename_collision_hash_uniqueness(self):
        # Two files with names that sanitize to identical prefixes: "a b.pdf" and "a_b.pdf"
        meta_1 = {
            "type": "pdf",
            "filename": "a b.pdf",
            "pages": [{"page": 1, "text": "Minimum clear width of 900 mm."}]
        }
        meta_2 = {
            "type": "pdf",
            "filename": "a_b.pdf",
            "pages": [{"page": 1, "text": "Minimum clear width of 1000 mm."}]
        }

        EntityExtractor.extract_and_index(self.project_id, "a b.pdf", meta_1)
        EntityExtractor.extract_and_index(self.project_id, "a_b.pdf", meta_2)

        with db.SessionLocal() as s:
            req1 = s.query(db.Requirement).filter_by(project_id=self.project_id, source_doc="a b.pdf").first()
            req2 = s.query(db.Requirement).filter_by(project_id=self.project_id, source_doc="a_b.pdf").first()
            self.assertIsNotNone(req1)
            self.assertIsNotNone(req2)
            self.assertNotEqual(req1.req_id, req2.req_id)
            # Both IDs contain distinct hashes
            self.assertTrue(len(req1.req_id) > 10)
            self.assertTrue(len(req2.req_id) > 10)

    def test_batch_transaction_commits_atomically(self):
        hub = KnowledgeHub(load_db=False)
        hub.begin_batch()
        r_id = hub.add_requirement(
            project_id=str(self.project_id),
            req_id="BATCH-01",
            title="travel distance",
            value=45.0,
            unit="m",
        )
        e_id = hub.add_evidence(
            project_id=str(self.project_id),
            evidence_type="text",
            content="Max travel distance is 45m",
            source_doc="egress.pdf",
            evidence_id="EV-BATCH-01",
        )
        hub.add_relationship(e_id, "supports", r_id)
        hub.commit_batch()

        with db.SessionLocal() as s:
            self.assertIsNotNone(s.query(db.Requirement).filter_by(project_id=self.project_id, req_id="BATCH-01").first())
            self.assertIsNotNone(s.query(db.Evidence).filter_by(project_id=self.project_id, evidence_id="EV-BATCH-01").first())
            self.assertIsNotNone(s.query(db.GraphEdge).filter_by(project_id=self.project_id, src_id=e_id, dst_id=r_id).first())


if __name__ == "__main__":
    unittest.main()
