"""Bounded full-page OCR for scans and pages with no usable native layer.

Child process isolation bounds CPU OCR hangs; successful results are cached by
source hash and page. OCR is searchable evidence, never verified engineering data.
"""
import hashlib
import json
import time
import os
import subprocess
import sys
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')


def _needs_ocr(page, entry):
    from services.pdf_text_quality import native_text_usable
    native = str(entry.get('text') or '').strip()
    scanned = any(image[2]*image[3] > 50000 for image in page.get_images(full=True)) and len(native) < 500
    return not (entry.get('native_text_quality') != 'DAMAGED' and native_text_usable(native) and not scanned)


def _batch_prefetch(document, entries, digest, cache_dir, timeout, progress_cb=None):
    """Efficiency (2026-10-21): OCR every page that needs it in ONE child process,
    so the OCR model loads once per document instead of once per page. Writes the
    same per-page cache files the loop below reads; anything that fails here is
    simply retried by the original per-page path."""
    import fitz
    from services.pdf_text_quality import page_text_rotation
    jobs = []
    for entry in entries:
        page = document[entry['page']-1]
        if not _needs_ocr(page, entry):
            continue
        rotation = page_text_rotation(page)
        cache = os.path.join(cache_dir, f"{digest}-quality-v2-r{rotation}-p{entry['page']}.json")
        legacy = os.path.join(cache_dir, f"{digest}-p{entry['page']}.json")
        if os.path.isfile(cache) or os.path.isfile(legacy):
            continue
        image_path = os.path.join(cache_dir, f"p{entry['page']}.png")
        zoom = min(2.0, 2000/max(page.rect.width, page.rect.height))
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(rotation), alpha=False).save(image_path)
        jobs.append([image_path, cache, entry['page']])
    if len(jobs) < 2:
        return
    listing = os.path.join(cache_dir, 'batch-%s.json' % digest[:12])
    with open(listing, 'w', encoding='utf-8') as handle:
        json.dump(jobs, handle)
    proc = subprocess.Popen([sys.executable, '-m', 'services.page_ocr', '--batch', listing],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + timeout * len(jobs)
    try:
        while proc.poll() is None:
            if time.time() > deadline:
                proc.kill()
                break
            if progress_cb:
                done = sum(1 for _, cache, _ in jobs if os.path.isfile(cache))
                progress_cb(done, len(entries))
            time.sleep(1.0)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()
        try:
            os.remove(listing)
        except OSError:
            pass


def supplement_pages(path, meta, timeout=120, progress_cb=None):
    import fitz
    with open(path,'rb') as handle:
        digest = hashlib.file_digest(handle,'sha256').hexdigest()
    cache_dir = path + '_page_ocr'
    os.makedirs(cache_dir,exist_ok=True)
    errors = 0
    with fitz.open(path) as document:
        entries = meta.get('pages', [])
        try:
            _batch_prefetch(document, entries, digest, cache_dir, timeout, progress_cb)
        except Exception:
            pass  # per-page path below still runs (and reports) any page left uncached
        for entry in entries:
            if progress_cb:
                progress_cb(entry['page'] - 1, len(entries))
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
                    from services.pdf_text_quality import safe_find_tables
                    _ft = safe_find_tables(page)
                    if _ft and _ft.tables:
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
    if progress_cb:
        progress_cb(len(entries), len(entries))
    return errors


def _ocr_one(engine, image, output, page):
    from dataclasses import asdict
    result = engine.recognize(image,page=int(page))
    payload = {'text':result.full_text,'confidence':result.average_confidence,
               'boxes':[asdict(record) for record in result.results]}
    temporary = output+'.tmp'
    with open(temporary,'w',encoding='utf-8') as handle:
        json.dump(payload,handle,ensure_ascii=False)
    os.replace(temporary,output)


if __name__ == '__main__':
    from engines.ocr_engine import get_ocr_engine
    if sys.argv[1] == '--batch':
        with open(sys.argv[2], encoding='utf-8') as handle:
            batch = json.load(handle)
        engine = get_ocr_engine()
        for image, output, page in batch:
            try:
                _ocr_one(engine, image, output, page)
            except Exception as exc:  # leave this page to the per-page fallback
                print('page %s failed: %s' % (page, exc), file=sys.stderr)
    else:
        image, output, page = sys.argv[1:]
        _ocr_one(get_ocr_engine(), image, output, page)
