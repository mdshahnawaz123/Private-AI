"""
Unit and regression tests for Phase 1 edge cases:
1. Dropped pages on revised upload (e.g., page 3 dropped) -> stale records on page 3 deleted.
2. Table page returning zero rows on revision -> stale records deleted, not kept.
3. Image filename changed on revision -> stale image records on that page deleted.
"""
import os
import fitz
import unittest
import uuid
from pathlib import Path
import db
from services.pipeline import process_document_pipeline


class TestReuploadEdgeCases(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.proj_name = f"edge_case_proj_{uuid.uuid4().hex[:8]}"
        with db.SessionLocal() as s:
            proj = db.Project(name=self.proj_name)
            s.add(proj)
            s.commit()
            self.pid = proj.id

        self.test_dir = Path("data/docs") / self.proj_name
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        with db.SessionLocal() as s:
            s.query(db.StructuredRecord).filter_by(project_id=self.pid).delete()
            s.query(db.ImageRecord).filter_by(project_id=self.pid).delete()
            s.query(db.PageRecord).filter_by(project_id=self.pid).delete()
            s.query(db.Project).filter_by(id=self.pid).delete()
            s.commit()

        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_dropped_page_purges_stale_records(self):
        # 1. Create a 3-page PDF with table records on all 3 pages
        doc_path = self.test_dir / "dropped_page_test.pdf"
        doc = fitz.open()
        for i in range(3):
            p = doc.new_page()
            p.insert_text((50, 50), f"Page {i+1} content")
        doc.save(str(doc_path))
        doc.close()

        # Seed records for pages 1, 2, and 3
        with db.SessionLocal() as s:
            for p_num in [1, 2, 3]:
                s.add(db.PageRecord(
                    project_id=self.pid,
                    document_filename="dropped_page_test.pdf",
                    page_number=p_num,
                    page_status="READY"
                ))
                s.add(db.ImageRecord(
                    project_id=self.pid,
                    document_filename="dropped_page_test.pdf",
                    page_number=p_num,
                    image_id=f"p{p_num}_0.png",
                    image_index=0
                ))
                s.add(db.StructuredRecord(
                    project_id=self.pid,
                    doc="dropped_page_test.pdf",
                    page=p_num,
                    entity=f"ELEMENT P{p_num}",
                    field="Area",
                    value=100.0 * p_num,
                    source_type="PDF_NATIVE"
                ))
            s.commit()

        # Verify page 3 has records
        with db.SessionLocal() as s:
            self.assertEqual(s.query(db.PageRecord).filter_by(project_id=self.pid, document_filename="dropped_page_test.pdf", page_number=3).count(), 1)
            self.assertEqual(s.query(db.ImageRecord).filter_by(project_id=self.pid, document_filename="dropped_page_test.pdf", page_number=3).count(), 1)
            self.assertEqual(s.query(db.StructuredRecord).filter_by(project_id=self.pid, doc="dropped_page_test.pdf", page=3).count(), 1)

        # 2. Re-upload revised document with only 2 pages (page 3 removed)
        doc2 = fitz.open()
        for i in range(2):
            p = doc2.new_page()
            p.insert_text((50, 50), f"Revised Page {i+1} content")
        doc2.save(str(doc_path))
        doc2.close()

        # Run pipeline
        process_document_pipeline(self.pid, str(doc_path), "dropped_page_test.pdf")

        # 3. Verify all page 3 records were purged
        with db.SessionLocal() as s:
            p3_pages = s.query(db.PageRecord).filter_by(project_id=self.pid, document_filename="dropped_page_test.pdf", page_number=3).count()
            p3_images = s.query(db.ImageRecord).filter_by(project_id=self.pid, document_filename="dropped_page_test.pdf", page_number=3).count()
            p3_records = s.query(db.StructuredRecord).filter_by(project_id=self.pid, doc="dropped_page_test.pdf", page=3).count()

            self.assertEqual(p3_pages, 0, "PageRecord for dropped page 3 must be deleted")
            self.assertEqual(p3_images, 0, "ImageRecord for dropped page 3 must be deleted")
            self.assertEqual(p3_records, 0, "StructuredRecord for dropped page 3 must be deleted")

    def test_zero_row_table_page_purges_old_rows(self):
        # 1. Create a 1-page PDF
        doc_path = self.test_dir / "zero_table_test.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 50), "Plain text page without any tables")
        doc.save(str(doc_path))
        doc.close()

        # Seed old native structured records from previous revision
        with db.SessionLocal() as s:
            s.add(db.StructuredRecord(
                project_id=self.pid,
                doc="zero_table_test.pdf",
                page=1,
                entity="OLD TOWER LEVEL 01",
                field="Floor GFA",
                value=500.0,
                source_type="PDF_NATIVE"
            ))
            s.commit()

        # Verify old record exists
        with db.SessionLocal() as s:
            self.assertEqual(s.query(db.StructuredRecord).filter_by(project_id=self.pid, doc="zero_table_test.pdf", page=1).count(), 1)

        # Run pipeline on revised document with no tables
        process_document_pipeline(self.pid, str(doc_path), "zero_table_test.pdf")

        # Verify old records were deleted, not kept
        with db.SessionLocal() as s:
            records = s.query(db.StructuredRecord).filter_by(project_id=self.pid, doc="zero_table_test.pdf", page=1).all()
            self.assertEqual(len(records), 0, "Zero-row table page must purge stale native records")

    def test_image_filename_change_purges_old_image_records(self):
        # 1. Create a 1-page PDF with an image
        doc_path = self.test_dir / "image_rename_test.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 50), "Image page")
        doc.save(str(doc_path))
        doc.close()

        # Seed old ImageRecord with an old image filename and old visual StructuredRecord
        with db.SessionLocal() as s:
            s.add(db.ImageRecord(
                project_id=self.pid,
                document_filename="image_rename_test.pdf",
                page_number=1,
                image_id="old_rendering_v1.png",
                image_index=0
            ))
            s.add(db.StructuredRecord(
                project_id=self.pid,
                doc="image_rename_test.pdf",
                page=1,
                entity="OLD VISUAL ELEMENT",
                field="Ratio",
                value=1.12,
                source_type="PDF_IMAGE",
                source_bbox="old_rendering_v1.png"
            ))
            s.commit()

        # Run pipeline on revised document (which produces no images or different images)
        process_document_pipeline(self.pid, str(doc_path), "image_rename_test.pdf")

        # Verify old image record and old visual structured record were deleted
        with db.SessionLocal() as s:
            old_img = s.query(db.ImageRecord).filter_by(
                project_id=self.pid, document_filename="image_rename_test.pdf", image_id="old_rendering_v1.png"
            ).first()
            old_rec = s.query(db.StructuredRecord).filter_by(
                project_id=self.pid, doc="image_rename_test.pdf", entity="OLD VISUAL ELEMENT"
            ).first()

            self.assertIsNone(old_img, "Old ImageRecord with changed filename must be purged")
            self.assertIsNone(old_rec, "Old visual StructuredRecord from changed image must be purged")


if __name__ == "__main__":
    unittest.main()
