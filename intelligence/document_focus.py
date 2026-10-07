"""Resolve explicitly named sources only from the permission-filtered list."""
import re

def named_document(query,documents):
    matches=[d for d in documents if d.get('filename') and re.search(
        r'(?<![\w.-])'+re.escape(d['filename'])+r'(?![\w.-])',query,re.I)]
    return matches[0] if len(matches)==1 else None
