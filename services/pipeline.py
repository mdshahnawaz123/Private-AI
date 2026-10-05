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

try:
    import easyocr
    ocr_reader = easyocr.Reader(['en'], gpu=False)
except ImportError:
    ocr_reader = None

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
        return "DECORATIVE"
    if ratio > 5.0 or ratio < 0.2:
        return "DECORATIVE"
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
            'model': 'qwen2.5-vl:7b',
            'stream': False,
            'messages': [{'role': 'user', 'content': prompt, 'images': [b64]}]
        }, timeout=120)
        text = res.json().get('message', {}).get('content', '')
        t = time.time() - t0
        return text, f"Time: {t:.1f}s"
    except Exception as e:
        return None, str(e)


def process_document_pipeline(project_id, save_path, filename):
    session = db.SessionLocal()
    try:
        logger.info(f"Phase 5B: Starting bounded visual pipeline for {filename}")
        
        # 1. Revision Cleanup
        session.query(db.PageRecord).filter_by(project_id=project_id, document_filename=filename).delete()
        session.query(db.ImageRecord).filter_by(project_id=project_id, document_filename=filename).delete()
        session.query(db.StructuredRecord).filter_by(project_id=project_id, doc=filename, source_type="PDF_IMAGE").delete()
        session.commit()
        
        doc = fitz.open(save_path)
        render_dir = save_path + "_images"
        os.makedirs(render_dir, exist_ok=True)
        
        from knowledge.extraction import parse_generic_tables
        
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text").strip()
            
            tabs = []
            try:
                tabs = page.find_tables().tables if page.find_tables() else []
            except:
                pass
                
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
            
            images = get_images_from_page(doc, i)
            pr.image_count = len(images)
            session.commit()
            
            img_idx = 0
            for xref, base_image in images:
                image_bytes = base_image["image"]
                ext = base_image["ext"]
                w = base_image["width"]
                h = base_image["height"]
                
                itype = classify_image(w, h)
                
                img_filename = f"p{i+1}_{img_idx}.{ext}"
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
                
                if itype == "ENGINEERING_TABLE":
                    # 1. Try EasyOCR
                    md_text, msg = run_easyocr(img_path)
                    ext_method = "EASYOCR"
                    
                    if not md_text:
                        # 2. Escalate to Qwen
                        logger.info(f"EasyOCR failed/rejected for {img_filename} ({msg}). Escalating to Qwen2.5-VL 7B...")
                        md_text, msg = run_qwen_vl(img_path, text)
                        ext_method = "QWEN2.5-VL-7B"
                        
                    if md_text:
                        ir.vision_status = "COMPLETED"
                        ir.visual_description = md_text
                        
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
                                    confidence="HIGH",
                                    extraction_method=ext_method,
                                    source_type="PDF_IMAGE",
                                    source_bbox=img_filename
                                )
                                session.add(rec)
                    else:
                        ir.vision_status = "FAILED"
                        ir.processing_error = msg
                        
                session.commit()
                img_idx += 1
                
            pr.page_status = "READY"
            session.commit()
            
    except Exception as e:
        logger.error(f"Pipeline crashed: {e}")
        session.rollback()
    finally:
        session.close()

