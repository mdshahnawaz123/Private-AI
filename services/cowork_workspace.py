"""Project-local Cowork files, read incrementally without a total file-size cap."""
import os
from pathlib import Path

READ_PAGE_CHARS = 12000


def resolve_path(root, relative):
    root = Path(root).resolve()
    raw = str(relative or '.').replace('\\', '/')
    parts = raw.split('/')
    if raw.startswith('/') or any(':' in p or p == '..' for p in parts):
        raise ValueError('Use a relative path inside this project workspace')
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError('Path escapes the project workspace')
    return candidate


def read_file_page(path, offset=0, limit=READ_PAGE_CHARS):
    """Offsets count decoded characters, not bytes; each response is bounded."""
    offset, limit = int(offset), int(limit)
    if offset < 0 or limit < 1:
        raise ValueError('offset must be nonnegative and limit must be positive')
    limit = min(limit, READ_PAGE_CHARS)
    before = os.stat(path)
    with open(path, 'r', encoding='utf-8-sig', errors='strict', newline='') as handle:
        remaining = offset
        while remaining:
            skipped = handle.read(min(remaining, 65536))
            if not skipped:
                break
            remaining -= len(skipped)
        content = handle.read(limit)
        more = bool(handle.read(1))
    if '\x00' in content:
        raise ValueError('Binary file: use document extraction rather than a text read')
    after = os.stat(path)
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError('File changed during reading; restart at offset 0')
    return {'content': content, 'offset': offset, 'next_offset': offset + len(content),
            'eof': not more, 'version': f'{after.st_mtime_ns}:{after.st_size}',
            'encoding': 'utf-8-sig', 'offset_unit': 'characters'}
