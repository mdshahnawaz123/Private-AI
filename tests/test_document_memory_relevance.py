"""Regression tests for document-memory query/property relevance."""
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from intelligence.document_memory import memory_lookup


class _Query:
    def __init__(self, model, memory_row, document):
        self.model = model
        self.memory_row = memory_row
        self.document = document
        self.excluded = False

    def filter_by(self, **kwargs):
        if self.model is _DB.DocumentMemory and kwargs.get("doc") not in (None, self.memory_row.doc):
            self.excluded = True
        return self

    def filter(self, *_args, **_kwargs):
        if (self.model is _DB.DocumentMemory and _args and isinstance(_args[0], tuple)
                and _args[0][0] == "doc" and _args[0][1] != self.memory_row.doc):
            self.excluded = True
        return self

    def all(self):
        if self.excluded:
            return []
        return [self.memory_row] if self.model is _DB.DocumentMemory else [self.document]

    def first(self):
        return self.document if self.model is _DB.Document else None


class _Session:
    def __init__(self, memory_row, document):
        self.memory_row = memory_row
        self.document = document

    def query(self, model):
        return _Query(model, self.memory_row, self.document)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        pass


class _Column:
    def __init__(self, name):
        self.name = name

    def is_(self, _value):
        return self

    def __eq__(self, value):
        return self.name, value


class _DB:
    class DocumentMemory:
        superseded_at = _Column("superseded_at")
        doc = _Column("doc")
    Document = object()
    row = None
    document = None

    @classmethod
    def SessionLocal(cls):
        return _Session(cls.row, cls.document)


class DocumentMemoryRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tests")
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "memory-source.pdf"
        path.write_bytes(b"synthetic PDF identity")
        quote = "There shall be no limit on the number of mezzanines in a room."
        Path(str(path) + ".index.json").write_text(json.dumps({
            "pages": [{"page": 15, "text": quote, "tables": ""}],
            "processing_complete": True,
        }), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _DB.document = types.SimpleNamespace(id=1, project_id=7, status="ready", path=str(path))
        _DB.row = types.SimpleNamespace(
            id=42, project_id=7, document_id=1, doc="C3085-fire-report.pdf", revision="",
            source_sha256=digest, page=15, section="Fire safety", table="", entity="",
            topic_tags=[], property="Mezzanine number limit", claim=quote, value="No limit",
            unit="", parent_context="", evidence_quote=quote, superseded_at=None,
            evidence_state="VERIFIED",
        )
        self.db_module = types.SimpleNamespace(DocumentMemory=_DB.DocumentMemory, Document=_DB.Document,
                                              SessionLocal=_DB.SessionLocal)

    def _lookup(self, query, focus=None):
        with patch.dict("sys.modules", {"db": self.db_module}), \
             patch("intelligence.document_investigation.needs_coverage", return_value=False):
            return memory_lookup(7, query, {"C3085-fire-report.pdf"}, focus)

    def test_plot_number_question_does_not_match_mezzanine_number_limit(self):
        self.assertIsNone(self._lookup("What plot number is listed?"))

    def test_generic_number_token_alone_is_not_a_property_match(self):
        self.assertIsNone(self._lookup("What is the number?"))

    def test_matching_topic_and_requested_number_property_remains_answerable(self):
        _DB.row.property = "Mezzanine number limit"
        self.assertIsNotNone(self._lookup("What is the mezzanine number limit?"))

    def test_explicit_focus_excludes_memory_from_another_document(self):
        self.assertIsNone(self._lookup("What is the mezzanine number limit?", "C3045-data-sheet.pdf"))


if __name__ == "__main__":
    unittest.main()
