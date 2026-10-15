import os
import fitz
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import db
from loguru import logger
import re
import httpx
import base64

ocr_reader = None  # OCR is initialized lazily/offline by services.vision_adapter.

def get_images_from_page(doc, page_num):
    page = doc[page_num]
    images = []
    # Native images
    for img in page.get_images(full=True):
        xref = img[0]
        base_image = doc.extract_image(xref)
        images.append((xref, base_image))
    return images

def classify_image(w, h):
    area = w * h
    ratio = w / h if h else 1
    if area < 20000:
        return "UNKNOWN"  # Small engineering tags/legends can still be evidence.
    if ratio > 5.0 or ratio < 0.2:
        return "UNKNOWN"  # Aspect ratio cannot establish decorative content.
    if area > 100000 and 0.5 < ratio < 2.0:
        return "ENGINEERING_TABLE"
    return "UNKNOWN"

def run_easyocr(img_path):
    if not ocr_reader:
        return None, "EasyOCR not installed"

    t0 = time.time()
    try:
        results = ocr_reader.readtext(img_path)
    except Exception as e:
        return None, str(e)

    # Simple heuristic to see if it's a clean table
    if not results:
        return None, "No text found"

    # Group by Y-coordinate
    rows = []
    current_row = []
    current_y = None

    # Sort by Y top-left
    results.sort(key=lambda x: x[0][0][1])

    for bbox, text, conf in results:
        y = bbox[0][1]
        if current_y is None:
            current_y = y

        if abs(y - current_y) < 15: # 15px threshold
            current_row.append((bbox[0][0], text)) # x-coord, text
        else:
            current_row.sort(key=lambda x: x[0])
            rows.append([t for _, t in current_row])
            current_row = [(bbox[0][0], text)]
            current_y = y

    if current_row:
        current_row.sort(key=lambda x: x[0])
        rows.append([t for _, t in current_row])

    # Check if we have a consistent grid
    if len(rows) < 2:
        return None, "Not enough rows for table"

    # If standard deviation of column counts is high, it's not a clean table
    col_counts = [len(r) for r in rows]
    avg_cols = sum(col_counts) / len(col_counts)
    if avg_cols < 2:
        return None, "Not enough columns"

    diffs = [abs(c - avg_cols) for c in col_counts]
    if sum(diffs) / len(diffs) > 1.0: # Too much variance
        return None, "Ambiguous row/column mapping"

    # Build markdown table string
    md = ""
    for r in rows:
        md += "| " + " | ".join(r) + " |\n"
        if md.count("\n") == 1:
            md += "|---" * len(r) + "|\n"

    t = time.time() - t0
    return md, f"Time: {t:.1f}s"

def run_qwen_vl(img_path, page_text=""):
    t0 = time.time()
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    prompt = f"Extract all engineering tables and numerical values from this image. Output strictly as a Markdown table. Page context: {page_text[:500]}"
    try:
        res = httpx.post('http://localhost:11434/api/chat', json={
            'model': 'qwen2.5vl:7b',
            'stream': False,
            'messages': [{'role': 'user', 'content': prompt, 'images': [b64]}]
        }, timeout=120)
        text = res.json().get('message', {}).get('content', '')
        t = time.time() - t0
        return text, f"Time: {t:.1f}s"
    except Exception as e:
        return None, str(e)


def process_document_pipeline(project_id, save_path, filename, resume=False, expected_sha256=None, retry_failed=False):
    session = db.SessionLocal()
    try:
        logger.info(f"Phase 5B: Starting bounded visual pipeline for {filename}")

        completed_pages = set()
        if resume:
            import hashlib
            with open(save_path,'rb') as source:
                actual_sha256 = hashlib.file_digest(source,'sha256').hexdigest()
            if not expected_sha256 or actual_sha256 != expected_sha256:
                raise ValueError('Resume requires a matching previously verified source hash')
            completed_pages = {p.page_number for p in session.query(db.PageRecord).filter_by(
                project_id=project_id,document_filename=filename).all()
                if p.processing_completed is not None and p.page_status in ('READY','REVIEW_REQUIRED')}
            if retry_failed:
                # A completed page scan is not a completed required image extraction.
                failed_pages = {image.page_number for image in session.query(db.ImageRecord).filter(
                    db.ImageRecord.project_id == project_id,
                    db.ImageRecord.document_filename == filename,
                    db.ImageRecord.vision_status.in_(['FAILED', 'PENDING'])).all()}
                completed_pages.difference_update(failed_pages)
        # Completed pages belong to the verified same source; restart only unfinished pages.
        pages_query=session.query(db.PageRecord).filter_by(project_id=project_id,document_filename=filename)
        images_query=session.query(db.ImageRecord).filter_by(project_id=project_id,document_filename=filename)
        records_query=session.query(db.StructuredRecord).filter(db.StructuredRecord.project_id==project_id,
            db.StructuredRecord.doc==filename,db.StructuredRecord.source_type.in_(['PDF_IMAGE','PDF_NATIVE']))
        if completed_pages:
            pages_query=pages_query.filter(~db.PageRecord.page_number.in_(completed_pages))
            images_query=images_query.filter(~db.ImageRecord.page_number.in_(completed_pages))
            records_query=records_query.filter(~db.StructuredRecord.page.in_(completed_pages))
        pages_query.delete(synchronize_session=False)
        images_query.delete(synchronize_session=False)
        records_query.delete(synchronize_session=False)
        session.commit()

        doc = fitz.open(save_path)
        # Purge dropped pages from prior revisions (e.g., page 3 dropped)
        session.query(db.PageRecord).filter(
            db.PageRecord.project_id == project_id,
            db.PageRecord.document_filename == filename,
            db.PageRecord.page_number > len(doc)
        ).delete(synchronize_session=False)
        session.query(db.ImageRecord).filter(
            db.ImageRecord.project_id == project_id,
            db.ImageRecord.document_filename == filename,
            db.ImageRecord.page_number > len(doc)
        ).delete(synchronize_session=False)
        session.query(db.StructuredRecord).filter(
            db.StructuredRecord.project_id == project_id,
            db.StructuredRecord.doc == filename,
            db.StructuredRecord.page > len(doc)
        ).delete(synchronize_session=False)
        session.commit()

        pipeline_warnings = bool(completed_pages and session.query(db.PageRecord).filter(
            db.PageRecord.project_id==project_id,db.PageRecord.document_filename==filename,
            db.PageRecord.page_status.in_(['REVIEW_REQUIRED','FAILED','PARTIAL'])).count())
        render_dir = save_path + "_images"
        os.makedirs(render_dir, exist_ok=True)

        from knowledge.extraction import parse_generic_tables

        # Same embedded image (same PDF xref) is often repeated on every page --
        # logos, title-block artwork. Describe it once and reuse the result
        # (this report: 114 image instances, only 50 distinct; 66 were two
        # repeated header images re-sent to the vision model page after page).
        xref_results = {}
        for i in range(len(doc)):
            if i+1 in completed_pages:
                continue
            page = doc[i]
            from services.pdf_text_quality import native_text_usable
            raw_text = page.get_text("text").strip()
            damaged_native = bool(raw_text) and not native_text_usable(raw_text, min_chars=1)
            text = "" if damaged_native else raw_text
            # Sanitize null bytes from garbled PDF text (prevents subprocess crash)
            text = text.replace('\x00', '')

            tabs = []
            try:
                tabs = page.find_tables().tables if page.find_tables() else []
            except:
                pass

            if damaged_native:
                tabs = []

            pr = db.PageRecord(
                project_id=project_id,
                document_filename=filename,
                page_number=i + 1,
                page_status="EXTRACTING",
                text_extracted=1 if text else 0,
                native_table_count=len(tabs),
                image_count=0,
                processing_started=datetime.utcnow()
            )
            session.add(pr)
            session.commit()

                                                # --- Phase 7: NATIVE TABLE EXTRACTION ---
            if tabs:
                try:
                    import re
                    rows_out = []

                    for t in tabs:
                        t_rows = t.extract()
                        if not t_rows: continue

                        grid = []
                        for r in t_rows:
                            clean_r = [("" if c is None else str(c)).replace("\n", " ").strip() for c in r]
                            grid.append(clean_r)

                        header_idx = -1
                        for i_idx, r in enumerate(grid):
                            # Header row usually has multiple distinct text labels
                            text_cols = sum(1 for x in r if x and not re.match(r'^[-?\d,\.%]+$', x.replace('(', '').replace(')', '').strip()))
                            if text_cols >= 4:
                                header_idx = i_idx
                                break

                        if header_idx == -1:
                            # Fallback for tables like GF Podium
                            for i_idx, r in enumerate(grid):
                                if "LEVEL" in r or "Floor GFA (sqm)" in r:
                                    header_idx = i_idx
                                    break

                        if header_idx == -1:
                            continue

                        header = grid[header_idx]

                        current_entity_prefix = ""
                        for i_idx in range(header_idx):
                            for cell in grid[i_idx]:
                                if "TOWER" in cell.upper() or "PODIUM" in cell.upper() or "BASEMENT" in cell.upper() or "PARKING" in cell.upper():
                                    current_entity_prefix = cell.upper()
                                    break
                            if current_entity_prefix: break

                        if not current_entity_prefix:
                            for i_idx in range(header_idx + 1, min(len(grid), header_idx + 3)):
                                for cell in grid[i_idx]:
                                    if "TOWER" in cell.upper() or "PARKING" in cell.upper():
                                        current_entity_prefix = cell.upper()
                                        break
                                if current_entity_prefix: break

                        level_col = -1
                        for c, h in enumerate(header):
                            if "LEVEL" in h.upper() or "AREA" in h.upper():
                                level_col = c
                                break

                        for r in grid[header_idx + 1:]:
                            # Dynamically update entity prefix if we hit a new tower row (e.g. "TOWER 5")
                            for cell in r:
                                if "TOWER" in cell.upper():
                                    current_entity_prefix = cell.upper()

                            row_label = ""
                            if level_col != -1 and level_col < len(r) and r[level_col]:
                                row_label = r[level_col]
                            else:
                                for x in r:
                                    if x and not re.match(r'^[-?\d,\.%]+$', x.replace('(', '').replace(')', '').strip()):
                                        row_label = x
                                        break

                            if not row_label or row_label.startswith("TOTAL UNITS") or row_label == "STANDARD BAYS":
                                continue

                            ent = f"{current_entity_prefix} {row_label}".strip()

                            for c in range(len(r)):
                                if r[c] == row_label: continue

                                if c < len(header) and header[c] and r[c]:
                                    val = r[c]
                                    col = header[c]
                                    if val == "-" or not val: continue

                                    if re.match(r'^-?\d[\d,\.]*%$|^-?\d[\d,\.]*$', val.replace('-', '').strip()):
                                        rows_out.append({
                                            "table_name": current_entity_prefix,
                                            "entity": ent,
                                            "row_label": row_label,
                                            "field": col,
                                            "raw_value": val,
                                            "status": "SUCCESS"
                                        })
                                    else:
                                        rows_out.append({
                                            "table_name": current_entity_prefix,
                                            "entity": ent,
                                            "row_label": row_label,
                                            "field": col,
                                            "raw_value": val,
                                            "status": "AMBIGUOUS"
                                        })

                    seen_records = set()
                    seen_keys = set()
                    for out_row in rows_out:
                        row_key = out_row['entity']
                        col = out_row['field']
                        raw_val = out_row['raw_value']
                        table_name = out_row['table_name']
                        row_label = out_row['row_label']
                        status = out_row['status']

                        unique_key = (project_id, filename, i + 1, row_key, col)
                        if unique_key in seen_records: continue
                        seen_records.add(unique_key)
                        seen_keys.add((row_key, col))

                        val = None
                        raw_clean = str(raw_val).replace(',', '').strip()
                        try:
                            val = float(raw_clean)
                        except:
                            pass

                        # Mark confidence as HIGH or UNRESOLVED based on deterministic status
                        conf = "HIGH" if status == "SUCCESS" else "AMBIGUOUS"

                        existing = session.query(db.StructuredRecord).filter_by(
                            project_id=project_id, doc=filename, page=i + 1, entity=row_key, field=col
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
                                project_id=project_id,
                                doc=filename,
                                page=i + 1,
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
                            session.add(rec)

                    # Delete stale native records for this page that are missing in the revision
                    old_records = session.query(db.StructuredRecord).filter_by(
                        project_id=project_id, doc=filename, page=i + 1, source_type="PDF_NATIVE"
                    ).all()
                    for old_rec in old_records:
                        if (old_rec.entity, old_rec.field) not in seen_keys:
                            session.delete(old_rec)
                    session.commit()
                except Exception as e:
                    logger.error(f"Native extraction crashed: {e}")
                    raise RuntimeError('Native structured extraction incomplete') from e
            else:
                # Edge case 2: If the revised page has zero native tables (extraction returns zero rows or no tables),
                # purge any old native records for this page
                session.query(db.StructuredRecord).filter_by(
                    project_id=project_id, doc=filename, page=i + 1, source_type="PDF_NATIVE"
                ).delete()
                session.commit()

            images = get_images_from_page(doc, i)
            pr.image_count = len(images)
            session.commit()

            page_seen_img_ids = set()
            page_seen_visual_keys = set()

            img_idx = 0
            for xref, base_image in images:
                image_bytes = base_image["image"]
                ext = base_image["ext"]
                w = base_image["width"]
                h = base_image["height"]

                itype = classify_image(w, h)

                img_filename = f"p{i+1}_{img_idx}.{ext}"
                page_seen_img_ids.add(img_filename)
                img_path = os.path.join(render_dir, img_filename)
                with open(img_path, "wb") as f:
                    f.write(image_bytes)

                ir = db.ImageRecord(
                    project_id=project_id,
                    document_filename=filename,
                    page_number=i + 1,
                    image_id=img_filename,
                    image_index=img_idx,
                    image_path=img_path,
                    width=w,
                    height=h,
                    image_type=itype,
                    vision_status="PENDING",
                    created_at=datetime.utcnow()
                )
                session.add(ir)
                session.commit()
                if itype == "DECORATIVE":
                    ir.vision_status = "SKIPPED"
                    ir.structured_extraction_status = "NOT_REQUIRED"
                    session.commit()
                elif itype == "UNKNOWN":
                    ir.vision_status = "REVIEW_REQUIRED"
                    ir.structured_extraction_status = "REVIEW_REQUIRED"
                    pipeline_warnings = True
                    session.commit()

                if itype in ("ENGINEERING_TABLE", "UNKNOWN"):
                    from services.vision_adapter import extract_visual_table

                    # Ruled table inside the image -> cell-by-cell OCR grid
                    # (services/image_tables.py); otherwise the usual OCR/vision.
                    _grid = None
                    try:
                        from services.image_tables import table_from_image
                        _grid = table_from_image(img_path)
                    except Exception as _te:
                        logger.warning(f"Image table detection failed for {img_filename}: {_te}")
                    if _grid:
                        res = {"success": True, "engine": "IMAGE_TABLE_CELL_OCR",
                               "raw_text": "\n".join("| " + " | ".join(r) + " |" for r in _grid)}
                    elif xref in xref_results:
                        res = dict(xref_results[xref])
                    else:
                        res = extract_visual_table(img_path, text,drawing=True)
                        if res.get("raw_text"):
                            xref_results[xref] = dict(res)
                    ext_method = res.get("engine", "FAILED")
                    md_text = res.get("raw_text")

                    if md_text:
                        ir.vision_status = "COMPLETED"
                        ir.visual_description = md_text
                        # Model/OCR confidence is not independent source verification.
                        ir.structured_extraction_status = "REVIEW_REQUIRED"
                        if ir.structured_extraction_status == "REVIEW_REQUIRED":
                            pipeline_warnings = True

                        # Parse Markdown to StructuredRecord
                        rows = parse_generic_tables(md_text, filename, i + 1, "", source_type="PDF_IMAGE")
                        for r in rows:
                            table_name = r.get("table_name", "")
                            row_key = r.get("row_key", "")
                            vals = r.get("row_values", {})

                            for col, raw_val in vals.items():
                                if not raw_val or str(raw_val).strip() == "-": continue
                                val = None
                                raw_clean = str(raw_val).replace(',', '').strip()
                                try:
                                    val = float(raw_clean)
                                except:
                                    pass

                                page_seen_visual_keys.add((row_key, col))

                                # Duplicate check
                                existing = session.query(db.StructuredRecord).filter_by(
                                    project_id=project_id,
                                    doc=filename,
                                    page=i + 1,
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
                                    existing.extraction_method = ext_method
                                    existing.source_type = "PDF_IMAGE"
                                    existing.source_bbox = img_filename
                                else:
                                    rec = db.StructuredRecord(
                                        project_id=project_id,
                                        doc=filename,
                                        page=i + 1,
                                        schedule=table_name,
                                        field=col,
                                        raw_value=str(raw_val),
                                        value=val,
                                        entity=row_key,
                                        row_label=row_key,
                                        column_label=col,
                                        confidence="AMBIGUOUS",
                                        extraction_method=ext_method,
                                        source_type="PDF_IMAGE",
                                        source_bbox=img_filename
                                    )
                                    session.add(rec)
                    else:
                        ir.vision_status = "FAILED"
                        ir.structured_extraction_status = "FAILED"
                        ir.processing_error = res.get("error") or "Visual extraction failed"
                        pipeline_warnings = True

                session.commit()
                img_idx += 1

            # Purge stale ImageRecords for this page whose image_id was not produced in this revision
            old_page_images = session.query(db.ImageRecord).filter_by(
                project_id=project_id, document_filename=filename, page_number=i + 1
            ).all()
            for old_img in old_page_images:
                if old_img.image_id not in page_seen_img_ids:
                    session.delete(old_img)

            # Purge stale visual StructuredRecords for this page missing in this revision (regardless of image rename/bbox)
            old_image_records = session.query(db.StructuredRecord).filter_by(
                project_id=project_id, doc=filename, page=i + 1, source_type="PDF_IMAGE"
            ).all()
            for old_rec in old_image_records:
                if (old_rec.entity, old_rec.field) not in page_seen_visual_keys:
                    session.delete(old_rec)
            session.commit()

            page_images = session.query(db.ImageRecord).filter_by(
                project_id=project_id, document_filename=filename, page_number=i+1).all()
            page_warnings = any(r.vision_status in ("FAILED", "REVIEW_REQUIRED", "PENDING")
                                or r.structured_extraction_status == "REVIEW_REQUIRED" for r in page_images)
            pr.page_status = "REVIEW_REQUIRED" if page_warnings else "READY"
            pr.vision_status = "PARTIAL" if page_warnings else ("COMPLETED" if page_images else "NOT_REQUIRED")
            pr.structured_record_count = session.query(db.StructuredRecord).filter_by(
                project_id=project_id, doc=filename, page=i+1).count()
            pr.processing_completed = datetime.utcnow()
            session.commit()

        # --- PHASE 7 COMPLETENESS ---
        total_images = session.query(db.ImageRecord).filter_by(project_id=project_id, document_filename=filename).count()
        vision_success = session.query(db.ImageRecord).filter_by(project_id=project_id, document_filename=filename, vision_status="COMPLETED").count()
        vision_failed = session.query(db.ImageRecord).filter_by(project_id=project_id, document_filename=filename, vision_status="FAILED").count()
        unresolved = session.query(db.ImageRecord).filter(
            db.ImageRecord.project_id == project_id,
            db.ImageRecord.document_filename == filename,
            db.ImageRecord.vision_status.in_(["PENDING", "FAILED", "REVIEW_REQUIRED"])).count()

        doc_rec = session.query(db.Document).filter_by(project_id=project_id, filename=filename).first()
        page_records=session.query(db.PageRecord).filter_by(project_id=project_id,document_filename=filename).all()
        if (len(page_records)!=len(doc) or any(p.processing_completed is None or p.page_status=='FAILED' for p in page_records)
                or any(r.vision_status=='PENDING' for r in session.query(db.ImageRecord).filter_by(project_id=project_id,document_filename=filename).all())):
            raise RuntimeError('Required page/visual extraction incomplete')
        doc.close()
        if pipeline_warnings or vision_failed > 0 or unresolved > 0:
            return "WARNINGS"
        else:
            return "READY"

    except Exception as e:
        logger.error(f"Pipeline crashed: {e}")
        session.rollback()
        session.query(db.PageRecord).filter_by(
            project_id=project_id, document_filename=filename, page_status="EXTRACTING"
        ).update({"page_status": "FAILED", "processing_error": str(e),
                  "processing_completed": datetime.utcnow()})
        session.commit()
        raise RuntimeError('Visual/structured pipeline incomplete') from e
    finally:
        if 'doc' in locals() and not doc.is_closed:
            doc.close()
        session.close()

