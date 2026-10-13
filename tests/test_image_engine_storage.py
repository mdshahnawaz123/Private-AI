import io
import os
import shutil
import tempfile
import unittest
import uuid
from PIL import Image

import db
from services.image_engine.image_storage import ImageStorage, StorageSecurityError


class TestImageStorage(unittest.TestCase):
    def setUp(self):
        # Create isolated temp data directory
        self.temp_dir = tempfile.mkdtemp()
        self.storage = ImageStorage(data_dir=self.temp_dir)

        # Create a test project and job in SQLite
        self.project_name = f"test_proj_{uuid.uuid4().hex[:8]}"
        self.job_id = f"test_job_{uuid.uuid4().hex[:8]}"

        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.commit()
            self.project_id = proj.id

        db.create_image_job(
            job_id=self.job_id,
            project_id=self.project_id,
            user_id=1,
            workflow_id="architecture_concept",
            input_params={"prompt": "modern villa"},
        )

    def tearDown(self):
        # Clean up database records
        with db.SessionLocal() as s:
            s.query(db.ImageOutput).filter_by(job_id=self.job_id).delete()
            s.query(db.ImageJob).filter_by(id=self.job_id).delete()
            s.query(db.Project).filter_by(id=self.project_id).delete()
            s.commit()

        # Clean up filesystem
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_png(self, width: int = 128, height: int = 128) -> bytes:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_sanitize_filename(self):
        sanitized = self.storage._sanitize_filename("../../etc/passwd.png")
        self.assertNotIn("..", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("\\", sanitized)
        self.assertTrue(sanitized.endswith(".png"))

    def test_get_job_dir_valid(self):
        job_dir = self.storage.get_job_dir(self.project_name, self.job_id)
        self.assertTrue(job_dir.exists())
        self.assertTrue(str(job_dir).startswith(self.temp_dir))
        self.assertIn(self.project_name, str(job_dir))
        self.assertIn(self.job_id, str(job_dir))

    def test_get_job_dir_path_traversal_rejected(self):
        with self.assertRaises(StorageSecurityError):
            self.storage.get_job_dir("../escaped_project", self.job_id)

        with self.assertRaises(StorageSecurityError):
            self.storage.get_job_dir(self.project_name, "../../escaped_job")

    def test_save_input_image_success(self):
        png_bytes = self._create_sample_png(200, 200)
        saved_path = self.storage.save_input_image(
            project=self.project_name,
            job_id=self.job_id,
            image_bytes=png_bytes,
            original_filename="user_sketch.png",
        )
        self.assertTrue(saved_path.exists())
        self.assertTrue(saved_path.name.startswith("input_"))
        self.assertEqual(saved_path.read_bytes(), png_bytes)

    def test_save_input_image_rejects_empty_or_corrupt(self):
        with self.assertRaises(ValueError):
            self.storage.save_input_image(self.project_name, self.job_id, b"")

        with self.assertRaises(ValueError):
            self.storage.save_input_image(self.project_name, self.job_id, b"this is not an image file")

    def test_save_output_image_creates_files_and_db_record(self):
        png_bytes = self._create_sample_png(512, 512)
        job_out = self.storage.save_output_image(
            project=self.project_name,
            job_id=self.job_id,
            image_bytes=png_bytes,
            filename="render_001.png",
            seed=42,
            metadata={"prompt": "modern villa"},
        )
        self.assertIsNotNone(job_out.output_id)
        self.assertEqual(job_out.filename, "render_001.png")
        self.assertEqual(job_out.width, 512)
        self.assertEqual(job_out.height, 512)
        self.assertEqual(job_out.seed, 42)

        # Check physical output file exists
        file_abs = os.path.join(self.temp_dir, job_out.file_path)
        self.assertTrue(os.path.exists(file_abs))

        # Check thumbnail file exists
        thumb_abs = os.path.join(self.temp_dir, os.path.dirname(job_out.file_path), "thumb_render_001.png")
        self.assertTrue(os.path.exists(thumb_abs))
        with Image.open(thumb_abs) as thumb_img:
            self.assertLessEqual(thumb_img.width, 256)
            self.assertLessEqual(thumb_img.height, 256)

        # Check sidecar metadata JSON exists
        sidecar_abs = file_abs + ".meta.json"
        self.assertTrue(os.path.exists(sidecar_abs))

        # Check database record was inserted
        db_record = db.get_image_output(job_out.output_id)
        self.assertIsNotNone(db_record)
        self.assertEqual(db_record["filename"], "render_001.png")
        self.assertEqual(db_record["width"], 512)
        self.assertEqual(db_record["seed"], 42)

    def test_get_output_paths_success_and_security(self):
        png_bytes = self._create_sample_png(300, 300)
        job_out = self.storage.save_output_image(
            project=self.project_name,
            job_id=self.job_id,
            image_bytes=png_bytes,
            filename="concept.png",
            seed=100,
        )

        # Success path
        file_path, thumb_path = self.storage.get_output_paths(self.project_name, job_out.output_id)
        self.assertTrue(file_path.exists())
        self.assertIsNotNone(thumb_path)
        self.assertTrue(thumb_path.exists())

        # Cross-project access denied
        with self.assertRaises(StorageSecurityError):
            self.storage.get_output_paths("different_project", job_out.output_id)

        # Nonexistent output raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.storage.get_output_paths(self.project_name, "nonexistent-out-id")


if __name__ == "__main__":
    unittest.main()
