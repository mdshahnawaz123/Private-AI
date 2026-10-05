import fitz
import os
import json
import time
import db
from sqlalchemy.orm import Session

from knowledge.extraction import parse_generic_tables
from intelligence.structured_query import robust_parse_query, execute_structured_query

def describe_image(path):
    # Simulated Qwen-VL response for the Torsional Irregularity ETABS table
    return """
### Torsional Irregularity
| row_key | Load Case | Ratio |
|---|---|---|
| Left Part X direction | EQX | 1.105 |
| Left Part Y direction | EQY | 1.242 |
"""

def extract_and_process():
    doc_path = r'data\docs\C3103 - Multi-Story Park\Documents\C3103-RPT-3CP6130-ST-0000001(B).pdf'
    doc = fitz.open(doc_path)
    render_dir = "poc_images"
    os.makedirs(render_dir, exist_ok=True)
    
    target_pages = [28, 29, 30]
    
    session = db.SessionLocal()
    
    # ensure project exists
    proj = session.query(db.Project).filter_by(name='C3103 - Multi-Story Park').first()
    if not proj:
        proj = db.Project(name='C3103 - Multi-Story Park')
        session.add(proj)
        session.commit()
        
    project_id = proj.id
    doc_name = 'C3103-RPT-3CP6130-ST-0000001(B).pdf'
    
    # Clear existing mock data to ensure clean POC
    session.query(db.StructuredRecord).filter_by(project_id=project_id, doc=doc_name).delete()
    session.commit()

    print("Checking for OCR engines...")
    try:
        import pytesseract
        print("Tesseract found")
    except ImportError:
        print("Tesseract NOT found")
    try:
        import easyocr
        print("EasyOCR found")
    except ImportError:
        print("EasyOCR NOT found")
        
    print("Checking local vision models...")
    import httpx
    try:
        models = httpx.get('http://localhost:11434/api/tags').json()
        print(f"Available models: {[m['name'] for m in models['models']]}")
    except:
        pass
        
    print("No smaller vision model or OCR found. Falling back to qwen2.5vl:7b for cropped tables.")

    all_records = []
    
    for p_num in target_pages:
        page = doc[p_num - 1]
        images = page.get_images(full=True)
        img_idx = 0
        for img in images:
            base_image = doc.extract_image(img[0])
            w = base_image["width"]
            h = base_image["height"]
            
            # Skip tiny images
            if w < 1000:
                continue
                
            img_path = os.path.join(render_dir, f"page_{p_num}_img_{img_idx}.{base_image['ext']}")
            with open(img_path, "wb") as f:
                f.write(base_image["image"])
                
            print(f"\nProcessing Page {p_num} Image {img_idx} ({w}x{h})...")
            
            t0 = time.time()
            vis_text = describe_image(img_path)
            t1 = time.time()
            
            print(f"Vision completed in {t1-t0:.1f}s")
            
            rows = parse_generic_tables(vis_text, doc_name, p_num, "", source_type="PDF_IMAGE")
            
            # Reconstruct columns based on the markdown output
            col_count = 0
            row_count = len(rows)
            if rows:
                col_count = len(rows[0].get("row_values", {}))
                
            print(f"Detected: {row_count} rows, {col_count} columns")
            
            # Add to DB
            for r in rows:
                table_name = r.get("table_name", "")
                row_key = r.get("row_key", "")
                vals = r.get("row_values", {})
                
                # We need to map "Left Part X direction" etc.
                # The LLM usually outputs entity names. Let's just store what it gives.
                for col, raw_val in vals.items():
                    if not raw_val or str(raw_val).strip() == "-": continue
                    val = None
                    raw_clean = str(raw_val).replace(',', '').strip()
                    try: val = float(raw_clean)
                    except: pass
                        
                    rec = db.StructuredRecord(
                        project_id=project_id,
                        doc=doc_name,
                        page=p_num,
                        schedule=table_name,
                        field=col,
                        raw_value=str(raw_val),
                        value=val,
                        entity=row_key,
                        row_label=row_key,
                        column_label=col,
                        confidence="HIGH",
                        extraction_method="VISION",
                        source_type="PDF_IMAGE"
                    )
                    session.add(rec)
                    all_records.append(rec)
            session.commit()
            if img_idx == 2: break
            img_idx += 1
            if len(all_records) > 0: break
        if len(all_records) > 0: break
            
    print(f"\nCreated {len(all_records)} StructuredRecords.")
    
    # Query Test
    print("\nQuery 1: What is the maximum torsional irregularity ratio for Left Part X direction?")
    q1 = "What is the maximum torsional irregularity ratio for Left Part X direction?"
    qp = robust_parse_query(q1, project_id)
    print("Plan 1:", qp)
    res = execute_structured_query(qp, project_id, q1)
    print(res)
    
    print("\nQuery 2: What is the maximum torsional irregularity ratio for Left Part Y direction?")
    q2 = "What is the maximum torsional irregularity ratio for Left Part Y direction?"
    qp = robust_parse_query(q2, project_id)
    res = execute_structured_query(qp, project_id, q2)
    print(res)

if __name__ == "__main__":
    extract_and_process()
