"""Bounded full-page OCR for scans and pages with no usable native layer.

Child process isolation bounds CPU OCR hangs; successful results are cached by
source hash and page. OCR is searchable evidence, never verified engineering data.
"""
import hashlib
import json
import os
import subprocess
import sys


def supplement_pages(path, meta, timeout=120):
    import fitz
    with open(path,'rb') as handle:
        digest = hashlib.file_digest(handle,'sha256').hexdigest()
    cache_dir = path + '_page_ocr'
    os.makedirs(cache_dir,exist_ok=True)
    errors = 0
    with fitz.open(path) as document:
        for entry in meta.get('pages',[]):
            previous=str((entry.get('ocr') or {}).get('text') or '')
            if previous:
                entry['vision']=str(entry.get('vision') or '').replace('[UNVERIFIED FULL-PAGE OCR]\n'+previous,'').strip()
            page = document[entry['page']-1]
            # Sparse headers do not establish that the scanned body was read.
            native = str(entry.get('text') or '').strip()
            images = page.get_images(full=True)
            scanned = any(image[2]*image[3]>50000 for image in images) and len(native)<500
            from services.pdf_text_quality import native_text_usable, page_text_rotation
            if entry.get('native_text_quality') != 'DAMAGED' and native_text_usable(native) and not scanned:
                entry['page_ocr_status'] = 'NATIVE_TEXT_AVAILABLE'
                entry.pop('page_ocr_error',None)
                continue
            rotation = page_text_rotation(page)
            cache = os.path.join(cache_dir,f"{digest}-quality-v2-r{rotation}-p{entry['page']}.json")
            legacy_cache = os.path.join(cache_dir,f"{digest}-p{entry['page']}.json")
            if not os.path.isfile(cache) and os.path.isfile(legacy_cache):
                cache = legacy_cache
            try:
                if os.path.isfile(cache):
                    with open(cache,encoding='utf-8') as handle:
                        result = json.load(handle)
                else:
                    image_path = os.path.join(cache_dir,f"p{entry['page']}.png")
                    zoom = min(2.0,2000/max(page.rect.width,page.rect.height))
                    page.get_pixmap(matrix=fitz.Matrix(zoom,zoom).prerotate(rotation),alpha=False).save(image_path)
                    completed = subprocess.run([sys.executable,'-m','services.page_ocr',image_path,cache,str(entry['page'])],
                        timeout=timeout,capture_output=True,text=True)
                    if completed.returncode:
                        raise RuntimeError('Full-page OCR process failed: '+completed.stderr[-700:])
                    with open(cache,encoding='utf-8') as handle:
                        result = json.load(handle)
                # Column-aware reading order (two-column report pages were
                # interleaved line by line). Recomputed from the cached boxes,
                # so existing caches benefit without re-running OCR.
                try:
                    from services.ocr_layout import reading_order_text
                    _ordered = reading_order_text(result.get('boxes'))
                    if _ordered and _ordered.strip():
                        result = dict(result, text=_ordered)
                except Exception:
                    pass
                entry['ocr'] = result
                # Ruled tables: OCR each cell on its own (services/table_cells.py).
                try:
                    import re as _re
                    from services.table_cells import page_tables
                    if page.find_tables().tables:
                        captions = _re.findall(r'(?m)^Table \d+\b[^\n]{0,120}', result.get('text') or '')
                        entry['ocr_tables'] = page_tables(path, digest, entry['page'], rotation, captions)
                except Exception as exc:
                    entry['ocr_tables_error'] = str(exc)[:300]
                entry.pop('page_ocr_error',None)
                entry['interpretation_state']='INTERPRETED' if result.get('text','').strip() else 'AMBIGUOUS'
                entry['verification_state']='REVIEW_REQUIRED'
                if result.get('text','').strip():
                    entry['vision'] = (entry.get('vision','')+'\n[UNVERIFIED FULL-PAGE OCR]\n'+result['text']).strip()
                    entry['page_ocr_status'] = 'EXTRACTED_REVIEW_REQUIRED'
                else:
                    entry['page_ocr_status'] = 'NO_TEXT_REVIEW_REQUIRED'
                    errors += 1
            except (OSError,ValueError,subprocess.SubprocessError,RuntimeError) as exc:
                entry['page_ocr_status'] = 'FAILED_REVIEW_REQUIRED'
                entry['page_ocr_error'] = str(exc)
                errors += 1
    meta['page_ocr_errors'] = errors
    return errors


if __name__ == '__main__':
    from dataclasses import asdict
    from engines.ocr_engine import get_ocr_engine
    image, output, page = sys.argv[1:]
    result = get_ocr_engine().recognize(image,page=int(page))
    payload = {'text':result.full_text,'confidence':result.average_confidence,
               'boxes':[asdict(record) for record in result.results]}
    temporary = output+'.tmp'
    with open(temporary,'w',encoding='utf-8') as handle:
        json.dump(payload,handle,ensure_ascii=False)
    os.replace(temporary,output)
