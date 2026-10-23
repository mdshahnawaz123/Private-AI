"""Private PDF extraction and source-verified, same-owner/project reuse."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

VERSION = 3


def _sha(path):
    with open(path, 'rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def reusable_result(upload_id, path, digest):
    """No global content cache: candidates must belong to this user AND project."""
    import db
    with db.SessionLocal() as session:
        current = session.get(db.UserUpload, upload_id)
        if current is None:
            raise ValueError('Attachment no longer exists')
        rows = session.query(db.UserUpload).filter(
            db.UserUpload.user_id == current.user_id, db.UserUpload.project_id == current.project_id,
            db.UserUpload.filename == current.filename, db.UserUpload.size == current.size,
            db.UserUpload.status == 'ready', db.UserUpload.id != upload_id).order_by(db.UserUpload.id.desc()).limit(16).all()
        candidates = [(r.id, r.path) for r in rows]
    for identity, source in candidates:
        try:
            meta = json.loads(Path(source + '.index.json').read_text(encoding='utf-8'))
            if (meta.get('private_extraction_version') != VERSION or meta.get('source_sha256') != digest
                    or meta.get('processing_complete') is not True or meta.get('truncated')
                    or meta.get('ocr_complete') is False):
                continue
            if _sha(source) != digest:
                continue
            text = Path(source + '.extracted.txt').read_text(encoding='utf-8')
            if not text.strip() or hashlib.sha256(text.encode()).hexdigest() != meta.get('extracted_text_sha256'):
                continue
            meta['reused_from_upload_id'] = identity
            return text, meta
        except (OSError, ValueError, TypeError):
            continue
    return None


def _join(meta):
    return '\n\n'.join(f"[PAGE {p['page']}]\n{p.get('text','')}\n{p.get('tables','')}\n{p.get('vision','')}"
                       for p in meta.get('pages', []) if any(str(p.get(k) or '').strip() for k in ('text','tables','vision')))


def _publish(path, text, meta, digest, timings, started):
    import extract
    if not text.strip():
        raise ValueError('No readable content extracted from this PDF')
    if _sha(path) != digest:
        raise ValueError('Attachment changed during processing')
    meta.update(source_sha256=digest, private_extraction_version=VERSION, processing_complete=True,
                extracted_text_sha256=hashlib.sha256(text.encode()).hexdigest())
    timings['total_seconds'] = time.perf_counter() - started
    meta['processing_metrics'] = timings
    temporary = path + '.extracted.txt.tmp-' + uuid.uuid4().hex
    try:
        with open(temporary, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path + '.extracted.txt')
        if not extract.save_json(path + '.index.json', meta):
            raise RuntimeError('Could not publish attachment extraction metadata')
    finally:
        if os.path.exists(temporary): os.remove(temporary)


def _mostly_native(meta):
    """True when most pages already have a usable text layer, so the document
    can be answered from immediately and OCR can follow in the background."""
    try:
        from services.pdf_text_quality import native_text_usable
        pages = meta.get('pages', [])
        usable = sum(1 for p in pages if native_text_usable(str(p.get('text') or '').strip()))
        return bool(pages) and usable >= max(1, len(pages) // 2)
    except Exception:
        return False


def process(upload_id, path, progress=None):
    """Two-phase processing (2026-10-21), like Claude's own PDF handling:
    1) read the text layer and mark the attachment READY in seconds;
    2) OCR image-heavy pages afterwards and republish the enriched text.
    Answers read the sidecar files per question, so phase 2 is picked up
    automatically. A mostly-scanned PDF still waits for OCR (nothing to read)."""
    import extract
    import db
    from config import get_settings
    from services.page_ocr import supplement_pages
    started = time.perf_counter()
    report = progress or (lambda stage, done, total: None)
    report('checking unchanged document', 0, 0)
    page_limit = get_settings().max_pages
    digest = _sha(path)
    reused = reusable_result(upload_id, path, digest)
    if reused:
        text, meta = reused
        if page_limit and max(meta.get('total_pages') or 0, len(meta.get('pages', []))) > page_limit:
            raise ValueError('PDF exceeds the configured page limit; extraction is incomplete')
        _publish(path, text, meta, digest, {'cache_hit': True}, started)
        db.update_user_upload_status(upload_id, 'ready')
        return meta['processing_metrics']
    native_started = time.perf_counter()
    text, meta = extract.extract_pdf(path, deep=False, max_pages=page_limit,
        progress_cb=lambda done, total: report('reading pages', done, total))
    if meta.get('truncated') or (page_limit and max(meta.get('total_pages') or 0, len(meta.get('pages', []))) > page_limit):
        raise ValueError('PDF exceeds the configured page limit; extraction is incomplete')
    timings = {'cache_hit': False, 'native_seconds': time.perf_counter() - native_started}
    early = _mostly_native(meta)
    if early:
        meta['ocr_complete'] = False
        report('saving extracted pages', len(meta.get('pages', [])), len(meta.get('pages', [])))
        _publish(path, _join(meta) or text, meta, digest, dict(timings, phase='text-layer'), started)
        db.update_user_upload_status(upload_id, 'ready')
        timings['ready_seconds'] = time.perf_counter() - started
        try:
            import loguru
            loguru.logger.info('Private PDF ready from text layer in {:.1f}s; OCR continues in background', timings['ready_seconds'])
        except Exception:
            pass
    if early:
        # Background OCR on its own thread so the upload queue is free for the next
        # file right away; one OCR at a time (module-level lock) protects the CPU.
        import threading
        def _bg():
            with _OCR_LOCK:
                try:
                    _ocr_phase(path, meta, digest, timings, started, True, report, upload_id)
                except Exception as exc:
                    try:
                        import loguru
                        loguru.logger.warning('Background OCR failed for {}: {}', path, exc)
                    except Exception:
                        pass
        threading.Thread(target=_bg, name='bg-ocr', daemon=True).start()
        return timings
    with _OCR_LOCK:
        return _ocr_phase(path, meta, digest, timings, started, False, report, upload_id)


import threading as _threading
_OCR_LOCK = _threading.Lock()


def _ocr_phase(path, meta, digest, timings, started, early, report, upload_id):
    import db
    from services.page_ocr import supplement_pages
    ocr_started = time.perf_counter()
    try:
        supplement_pages(path, meta, progress_cb=None if early else
                         (lambda done, total: report('reading scanned pages', done, total)))
        failed = any(p.get('page_ocr_status') == 'FAILED_REVIEW_REQUIRED' for p in meta.get('pages', []))
    except Exception:
        if not early:
            raise
        failed = True
    timings['ocr_seconds'] = time.perf_counter() - ocr_started
    if failed and not early:
        raise RuntimeError('A required OCR page failed; attachment is not ready')
    meta['ocr_complete'] = not failed
    if not early:
        report('saving extracted pages', len(meta.get('pages', [])), len(meta.get('pages', [])))
    _publish(path, _join(meta), meta, digest, timings, started)
    if not early:
        db.update_user_upload_status(upload_id, 'ready')
    return timings
