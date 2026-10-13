"""
Project-isolated storage manager for the Expo Design AI Local Image Engine.

Handles saving generated images, generating thumbnails, storing metadata sidecars,
and strictly enforcing containment to prevent cross-project leakage and path traversal.
"""

import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from loguru import logger
from PIL import Image

import db
from services.image_engine.schemas import JobOutput
from services.ingestion import contained_upload_path


class StorageSecurityError(ValueError):
    """Raised when a path traversal or cross-project isolation violation is detected."""
    pass


class ImageStorage:
    """
    Manages filesystem storage for generated images, input reference sketches,
    and metadata sidecars within authorized project directories.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = os.path.abspath(data_dir or db.DATA_DIR)
        self.projects_dir = os.path.join(self.data_dir, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent directory traversal or unsafe shell characters."""
        base = os.path.basename(filename)
        # Keep alphanumeric, dashes, underscores, dots
        clean = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
        return clean or f"image_{uuid.uuid4().hex[:8]}.png"

    def get_job_dir(self, project: str, job_id: str) -> Path:
        """
        Derive the contained destination directory for an image job.
        Enforces path containment within the authorized project directory.
        """
        # Validate project name and path containment
        try:
            # Check containment within projects dir
            proj_dir = contained_upload_path(self.projects_dir, project, "generated_images", job_id)
        except (ValueError, TypeError) as exc:
            raise StorageSecurityError(f"Invalid project or job directory path: {exc}") from exc

        job_path = Path(proj_dir)
        job_path.mkdir(parents=True, exist_ok=True)
        return job_path

    def save_input_image(
        self, project: str, job_id: str, image_bytes: bytes, original_filename: str = "sketch.png"
    ) -> Path:
        """
        Save an uploaded input reference sketch or render snapshot into the job directory.
        Validates genuine image content using Pillow.
        """
        if not image_bytes:
            raise ValueError("Input image bytes cannot be empty")

        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            pil_img.verify()
        except Exception as exc:
            raise ValueError(f"Uploaded file is not a valid image: {exc}") from exc

        clean_name = self._sanitize_filename(original_filename)
        dest_filename = f"input_{clean_name}"
        job_dir = self.get_job_dir(project, job_id)
        dest_path = job_dir / dest_filename

        # Write atomically
        temp_path = dest_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
        temp_path.replace(dest_path)

        logger.info(f"Saved input reference image: {dest_path.name} in project {project!r}")
        return dest_path

    def save_output_image(
        self,
        project: str,
        job_id: str,
        image_bytes: bytes,
        filename: str,
        seed: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> JobOutput:
        """
        Persist a generated output image from ComfyUI into project storage.
        Generates a 256x256 thumbnail, stores a JSON sidecar, and inserts a db.ImageOutput row.
        """
        if not image_bytes:
            raise ValueError("Output image bytes cannot be empty")

        # Validate image format and extract dimensions
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            width, height = pil_img.size
            img_format = pil_img.format or "PNG"
        except Exception as exc:
            raise ValueError(f"Corrupted or invalid output image data: {exc}") from exc

        job_dir = self.get_job_dir(project, job_id)
        clean_name = self._sanitize_filename(filename)
        if not clean_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            clean_name += f".{img_format.lower()}"

        dest_path = job_dir / clean_name

        # 1. Write original image atomically
        temp_path = dest_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
        temp_path.replace(dest_path)

        # 2. Generate and save thumbnail (max 256x256)
        thumb_filename = f"thumb_{clean_name}"
        thumb_path = job_dir / thumb_filename
        try:
            thumb_img = pil_img.copy()
            thumb_img.thumbnail((256, 256), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb_img.save(thumb_buf, format="PNG", optimize=True)
            thumb_temp = thumb_path.with_suffix(".tmp")
            with open(thumb_temp, "wb") as f:
                f.write(thumb_buf.getvalue())
            thumb_temp.replace(thumb_path)
            thumb_rel = str(thumb_path.relative_to(self.data_dir)).replace("\\", "/")
        except Exception as t_err:
            logger.warning(f"Failed to generate thumbnail for {clean_name}: {t_err}")
            thumb_rel = None

        # 3. Save sidecar metadata JSON
        meta_payload = metadata or {}
        sidecar_path = job_dir / f"{clean_name}.meta.json"
        try:
            sidecar_temp = sidecar_path.with_suffix(".tmp")
            with open(sidecar_temp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "project": project,
                        "job_id": job_id,
                        "filename": clean_name,
                        "width": width,
                        "height": height,
                        "seed": seed,
                        "metadata": meta_payload,
                    },
                    f,
                    indent=2,
                )
            sidecar_temp.replace(sidecar_path)
        except Exception as s_err:
            logger.warning(f"Failed to save metadata sidecar for {clean_name}: {s_err}")

        # 4. Save to Database
        output_id = f"out-{uuid.uuid4().hex[:12]}"
        file_rel = str(dest_path.relative_to(self.data_dir)).replace("\\", "/")

        db.add_image_output(
            output_id=output_id,
            job_id=job_id,
            filename=clean_name,
            file_path=file_rel,
            thumbnail_path=thumb_rel,
            width=width,
            height=height,
            seed=seed,
            metadata=meta_payload,
        )

        return JobOutput(
            output_id=output_id,
            filename=clean_name,
            file_path=file_rel,
            thumbnail_url=f"/api/image-engine/outputs/{output_id}/thumb",
            download_url=f"/api/image-engine/outputs/{output_id}/file",
            width=width,
            height=height,
            seed=seed,
            metadata=meta_payload,
        )

    def get_output_paths(self, project: str, output_id: str) -> Tuple[Path, Optional[Path]]:
        """
        Resolve the verified absolute file path and thumbnail path for an output ID.
        Strictly verifies that the output belongs to the specified project.
        """
        record = db.get_image_output(output_id)
        if not record:
            raise FileNotFoundError(f"Image output {output_id!r} not found in database")

        job = db.get_image_job(record["job_id"])
        if not job:
            raise FileNotFoundError(f"Parent job for output {output_id!r} not found")

        # Verify project ownership via database project_id lookup
        with db.SessionLocal() as s:
            proj_row = s.query(db.Project).filter_by(id=job["project_id"]).first()
            if not proj_row or proj_row.name != project:
                raise StorageSecurityError(
                    f"Access denied: Output {output_id!r} belongs to a different project"
                )

        file_abs = Path(self.data_dir) / record["file_path"]
        thumb_abs = (Path(self.data_dir) / record["thumbnail_path"]) if record.get("thumbnail_path") else None

        # Containment verification
        try:
            file_abs.resolve().relative_to(Path(self.projects_dir).resolve())
        except ValueError:
            raise StorageSecurityError("File path escaped project containment directory")

        if not file_abs.exists():
            raise FileNotFoundError(f"Physical file missing on disk: {file_abs}")

        return file_abs, thumb_abs
