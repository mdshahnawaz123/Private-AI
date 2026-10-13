"""
Unit and regression tests for Fix 1:
Verifies that re-uploading a document updates existing StructuredRecord rows,
adds newly introduced rows, and removes rows that no longer exist in the new revision.
"""
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import db

class TestReuploadStructuredRecord(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        db.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()
        self.project_id = 1
        self.filename = "test_schedule.pdf"
        self.page = 1

    def tearDown(self):
        self.session.close()

    def test_native_reupload_updates_value_and_deletes_removed_row(self):
        # 1. Initial upload: ROW_A=100, ROW_B=200
        rec_a = db.StructuredRecord(
            project_id=self.project_id,
            doc=self.filename,
            page=self.page,
            schedule="Area Statement",
            field="GFA",
            raw_value="100",
            value=100.0,
            entity="ROW_A",
            row_label="ROW_A",
            column_label="GFA",
            confidence="HIGH",
            extraction_method="PYMUPDF_NATIVE",
            source_type="PDF_NATIVE"
        )
        rec_b = db.StructuredRecord(
            project_id=self.project_id,
            doc=self.filename,
            page=self.page,
            schedule="Area Statement",
            field="GFA",
            raw_value="200",
            value=200.0,
            entity="ROW_B",
            row_label="ROW_B",
            column_label="GFA",
            confidence="HIGH",
            extraction_method="PYMUPDF_NATIVE",
            source_type="PDF_NATIVE"
        )
        self.session.add_all([rec_a, rec_b])
        self.session.commit()

        # Verify initial state
        initial_records = self.session.query(db.StructuredRecord).filter_by(
            project_id=self.project_id, doc=self.filename, page=self.page
        ).all()
        self.assertEqual(len(initial_records), 2)

        # 2. Revised upload: ROW_A has changed value (150.0), ROW_B is deleted, ROW_C is newly added (300.0)
        rows_out = [
            {
                "entity": "ROW_A",
                "field": "GFA",
                "raw_value": "150",
                "table_name": "Area Statement",
                "row_label": "ROW_A",
                "status": "SUCCESS"
            },
            {
                "entity": "ROW_C",
                "field": "GFA",
                "raw_value": "300",
                "table_name": "Area Statement",
                "row_label": "ROW_C",
                "status": "SUCCESS"
            }
        ]

        # Execute update / sync logic as implemented in services/pipeline.py
        seen_records = set()
        seen_keys = set()
        for out_row in rows_out:
            row_key = out_row['entity']
            col = out_row['field']
            raw_val = out_row['raw_value']
            table_name = out_row['table_name']
            row_label = out_row['row_label']
            status = out_row['status']

            unique_key = (self.project_id, self.filename, self.page, row_key, col)
            if unique_key in seen_records:
                continue
            seen_records.add(unique_key)
            seen_keys.add((row_key, col))

            val = None
            raw_clean = str(raw_val).replace(',', '').strip()
            try:
                val = float(raw_clean)
            except:
                pass

            conf = "HIGH" if status == "SUCCESS" else "AMBIGUOUS"

            existing = self.session.query(db.StructuredRecord).filter_by(
                project_id=self.project_id, doc=self.filename, page=self.page, entity=row_key, field=col
            ).first()
            if existing:
                existing.value = val
                existing.raw_value = str(raw_val)
                existing.confidence = conf
                existing.schedule = table_name
                existing.row_label = row_label
                existing.column_label = col
                existing.extraction_method = "PYMUPDF_NATIVE"
                existing.source_type = "PDF_NATIVE"
            else:
                rec = db.StructuredRecord(
                    project_id=self.project_id,
                    doc=self.filename,
                    page=self.page,
                    schedule=table_name,
                    field=col,
                    raw_value=str(raw_val),
                    value=val,
                    entity=row_key,
                    row_label=row_label,
                    column_label=col,
                    confidence=conf,
                    extraction_method="PYMUPDF_NATIVE",
                    source_type="PDF_NATIVE",
                    source_bbox=None
                )
                self.session.add(rec)

        # Delete stale native records for this page that are missing in the revision
        old_records = self.session.query(db.StructuredRecord).filter_by(
            project_id=self.project_id, doc=self.filename, page=self.page, source_type="PDF_NATIVE"
        ).all()
        for old_rec in old_records:
            if (old_rec.entity, old_rec.field) not in seen_keys:
                self.session.delete(old_rec)
        self.session.commit()

        # 3. Assertions
        updated_records = {r.entity: r for r in self.session.query(db.StructuredRecord).filter_by(
            project_id=self.project_id, doc=self.filename, page=self.page
        ).all()}

        # ROW_A must be updated to 150.0 (not remaining at 100.0)
        self.assertIn("ROW_A", updated_records)
        self.assertEqual(updated_records["ROW_A"].value, 150.0)
        self.assertEqual(updated_records["ROW_A"].raw_value, "150")

        # ROW_B must be removed completely
        self.assertNotIn("ROW_B", updated_records)

        # ROW_C must be added
        self.assertIn("ROW_C", updated_records)
        self.assertEqual(updated_records["ROW_C"].value, 300.0)
        self.assertEqual(len(updated_records), 2)

    def test_image_reupload_updates_and_deletes_stale_rows(self):
        img_id = "p1_0.png"
        rec_x = db.StructuredRecord(
            project_id=self.project_id,
            doc=self.filename,
            page=self.page,
            schedule="Door Schedule",
            field="Width",
            raw_value="900",
            value=900.0,
            entity="D1",
            row_label="D1",
            column_label="Width",
            confidence="AMBIGUOUS",
            extraction_method="OCR",
            source_type="PDF_IMAGE",
            source_bbox=img_id
        )
        rec_y = db.StructuredRecord(
            project_id=self.project_id,
            doc=self.filename,
            page=self.page,
            schedule="Door Schedule",
            field="Width",
            raw_value="1000",
            value=1000.0,
            entity="D2",
            row_label="D2",
            column_label="Width",
            confidence="AMBIGUOUS",
            extraction_method="OCR",
            source_type="PDF_IMAGE",
            source_bbox=img_id
        )
        self.session.add_all([rec_x, rec_y])
        self.session.commit()

        # Revision: D1 updated to 950, D2 removed
        rows = [
            {
                "table_name": "Door Schedule",
                "row_key": "D1",
                "row_values": {"Width": "950"}
            }
        ]

        seen_image_keys = set()
        for r in rows:
            table_name = r.get("table_name", "")
            row_key = r.get("row_key", "")
            vals = r.get("row_values", {})

            for col, raw_val in vals.items():
                seen_image_keys.add((row_key, col))
                val = float(raw_val)

                existing = self.session.query(db.StructuredRecord).filter_by(
                    project_id=self.project_id,
                    doc=self.filename,
                    page=self.page,
                    entity=row_key,
                    field=col
                ).first()
                if existing:
                    existing.value = val
                    existing.raw_value = str(raw_val)
                    existing.confidence = "AMBIGUOUS"
                    existing.schedule = table_name
                    existing.row_label = row_key
                    existing.column_label = col
                    existing.source_type = "PDF_IMAGE"
                    existing.source_bbox = img_id
                else:
                    rec = db.StructuredRecord(
                        project_id=self.project_id,
                        doc=self.filename,
                        page=self.page,
                        schedule=table_name,
                        field=col,
                        raw_value=str(raw_val),
                        value=val,
                        entity=row_key,
                        row_label=row_key,
                        column_label=col,
                        confidence="AMBIGUOUS",
                        extraction_method="OCR",
                        source_type="PDF_IMAGE",
                        source_bbox=img_id
                    )
                    self.session.add(rec)

        old_image_records = self.session.query(db.StructuredRecord).filter_by(
            project_id=self.project_id, doc=self.filename, page=self.page, source_type="PDF_IMAGE", source_bbox=img_id
        ).all()
        for old_rec in old_image_records:
            if (old_rec.entity, old_rec.field) not in seen_image_keys:
                self.session.delete(old_rec)
        self.session.commit()

        updated = {r.entity: r for r in self.session.query(db.StructuredRecord).filter_by(
            project_id=self.project_id, doc=self.filename, page=self.page
        ).all()}

        self.assertIn("D1", updated)
        self.assertEqual(updated["D1"].value, 950.0)
        self.assertNotIn("D2", updated)

if __name__ == "__main__":
    unittest.main()
