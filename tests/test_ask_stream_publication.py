"""Offline stream-level tests for the /ask_stream publication boundary.

The route is compiled from main.py's actual AST with only server services and
the local model replaced by deterministic fakes. Tests consume the returned
SSE iterator and assert the content emitted to a client.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from intelligence.source_excerpt import source_excerpt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "synthetic-air.pdf"
PAGE = 1
SOURCES = [{"source": SOURCE, "page": PAGE}]
EVIDENCE = (
    f"[SOURCE: {SOURCE} | PAGE {PAGE}]\n"
    "AHU-813 design pressure is 275 Pa, subject to vendor confirmation.\n"
    "Approval status: Approved with Comments."
)
GOOD = "AHU-813 design pressure is 275 Pa, subject to vendor confirmation. [SOURCE: EVIDENCE_1 | PAGE 1]"


class FakeResponse:
    def __init__(self, body_iterator, **kwargs):
        self.body_iterator = body_iterator
        self.media_type = kwargs.get("media_type")


class FakeModel:
    def __init__(self, answers=(), error=None):
        self.answers = list(answers)
        self.error = error
        self.calls = 0

    def stream(self, _messages):
        self.calls += 1
        if self.error:
            raise self.error
        answer = self.answers.pop(0) if self.answers else "I could not find this in the uploaded documents."
        # Exercise token concatenation exactly as the route consumes local-model chunks.
        midpoint = max(1, len(answer) // 2)
        yield types.SimpleNamespace(content=answer[:midpoint])
        yield types.SimpleNamespace(content=answer[midpoint:])


class FakeSession:
    def query(self, _model):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return types.SimpleNamespace(id=7)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeDB:
    Project = object

    def __init__(self, documents):
        self.documents = documents

    def audit(self, *_args, **_kwargs):
        pass

    def list_documents(self, *_args, **_kwargs):
        return self.documents

    def folder_access(self, *_args, **_kwargs):
        return True, set()

    def SessionLocal(self):
        return FakeSession()


class FakeAdmission:
    class Lease:
        def release(self):
            pass

    def acquire(self):
        return self.Lease()


def _event_payload(frame):
    return json.loads(frame.removeprefix("data: ").strip())


class AskStreamPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        route = next(node for node in tree.body
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "ask_stream")
        route.decorator_list = []
        route.returns = None
        for arg in (*route.args.posonlyargs, *route.args.args, *route.args.kwonlyargs):
            arg.annotation = None
        cls.route_code = compile(ast.Module(body=[route], type_ignores=[]), "ask_stream-under-test", "exec")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(self.temp.cleanup)
        source_path = Path(self.temp.name) / SOURCE
        source_path.write_bytes(b"synthetic PDF fixture identity")
        page_text = "AHU-813 design pressure is 275 Pa, subject to vendor confirmation.\nApproval status: Approved with Comments."
        index = {
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "processing_complete": True,
            "pages": [{"page": PAGE, "text": page_text, "tables": ""}],
        }
        Path(str(source_path) + ".index.json").write_text(json.dumps(index), encoding="utf-8")
        self.documents = [{"filename": SOURCE, "path": str(source_path), "status": "ready", "chunks": 1}]
        self.fake_model = FakeModel([GOOD])
        self.issues = []
        self.model_error = None
        self.exact_result = {"status": "NOT_FOUND", "answer": "no exact answer", "sources": []}
        self.memory_result = None
        self.memory_call = None
        self.memory_enabled = False
        self.self_check_enabled = False
        self.self_check_override = None
        self.source_excerpt_override = "__real__"
        self.guard_override = None
        self.settings = types.SimpleNamespace(enable_document_memory=False, enable_self_check=False,
                                              chat_model="fake-local")
        self.context = EVIDENCE
        self.sources = SOURCES

    def _consume(self, query="What is the design pressure for AHU-813?", mode="chat"):
        fake_model = self.fake_model
        fake_model.error = self.model_error
        self.settings.enable_document_memory = self.memory_enabled
        self.settings.enable_self_check = self.self_check_enabled
        admission = FakeAdmission()
        fake_logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                            error=lambda *a, **k: None, exception=lambda *a, **k: None)
        fake_db = FakeDB(self.documents)
        fake_auth = types.SimpleNamespace(
            require_project=lambda *_a, **_k: {"id": 12, "role": "user"},
            require_roles=lambda *_a, **_k: None)

        async def run_in_threadpool(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        def retrieve_context(*_args, **_kwargs):
            return self.sources, self.context

        def make_namespace():
            namespace = {
                "auth": fake_auth, "db": fake_db, "json": json, "re": __import__("re"),
                "os": __import__("os"), "shutil": __import__("shutil"),
                "logger": fake_logger, "_client_ip": lambda *_a: "127.0.0.1",
                "run_in_threadpool": run_in_threadpool, "retrieve_context": retrieve_context,
                "get_llm": lambda _req: fake_model,
                "build_messages": lambda *_a, **_k: [types.SimpleNamespace(content="system")],
                "resolve_sources": lambda _project, items: items,
                "DOCS_DIR": self.temp.name,
                "StreamingResponse": FakeResponse,
                "response_schema": types.SimpleNamespace(build_structured_response=lambda *_a, **_k: {"ok": True}),
                "self_check_answer": self.self_check_override or (lambda answer, _ctx, _query: answer),
                "_save_verified_upload": None,
                "QueryRequest": object, "Request": object,
                "SystemMessage": lambda content: types.SimpleNamespace(content=content),
                "HumanMessage": lambda content: types.SimpleNamespace(content=content),
                "AIMessage": lambda content: types.SimpleNamespace(content=content),
            }
            exec(self.route_code, namespace)
            return namespace["ask_stream"]

        route = make_namespace()
        req = types.SimpleNamespace(project="SYNTH", query=query, mode=mode, k=5, model=None,
                                    discipline=None, messages=[], focus_doc="", attachment_id=None)
        request = types.SimpleNamespace(state=types.SimpleNamespace(user={"id": 12, "role": "user"}))
        exact_module = types.ModuleType("intelligence.exact_answers")
        exact_module.exact_answer = lambda *_a, **_k: self.exact_result
        memory_module = types.ModuleType("intelligence.document_memory")
        def memory_lookup(*args, **kwargs):
            self.memory_call = (args, kwargs)
            return self.memory_result
        memory_module.memory_lookup = memory_lookup
        config_module = types.ModuleType("config")
        config_module.get_settings = lambda: self.settings
        admission_module = types.ModuleType("services.model_admission")
        admission_module.document_model_admission = admission
        background_module = types.ModuleType("starlette.background")
        background_module.BackgroundTask = lambda *_a, **_k: None

        with patch.dict(sys.modules, {
            "intelligence.exact_answers": exact_module,
            "intelligence.document_memory": memory_module,
            "config": config_module,
            "services.model_admission": admission_module,
            "starlette.background": background_module,
        }):
            if self.guard_override:
                guard_patch = patch("intelligence.answer_guard.guarded_answer_with_repair", self.guard_override)
            else:
                guard_patch = patch("intelligence.answer_guard.guarded_answer_with_repair",
                                    __import__("intelligence.answer_guard", fromlist=["guarded_answer_with_repair"]).guarded_answer_with_repair)
            if self.source_excerpt_override == "__real__":
                excerpt_patch = patch("intelligence.source_excerpt.source_excerpt", source_excerpt)
            elif self.source_excerpt_override is None:
                excerpt_patch = patch("intelligence.source_excerpt.source_excerpt", lambda *_a, **_k: None)
            else:
                excerpt_patch = patch("intelligence.source_excerpt.source_excerpt", self.source_excerpt_override)
            with guard_patch, excerpt_patch:
                pending = route(req, request)
                try:
                    pending.send(None)
                except StopIteration as completed:
                    response = completed.value
                else:
                    self.fail("Fake route services should complete without an event loop")
                return [_event_payload(frame) for frame in response.body_iterator]

    def _texts(self, events):
        return "".join(event.get("text", "") for event in events if event.get("type") == "token")

    def test_supported_answer_is_emitted_with_resolved_citation_and_appended_qualification(self):
        events = self._consume()
        content = self._texts(events)
        self.assertIn("275 Pa", content)
        self.assertIn(f"[SOURCE: {SOURCE} | PAGE 1]", content)
        self.assertIn("Source qualifications:", content)
        self.assertIn("APPROVED_WITH_COMMENTS", content)
        self.assertEqual(events[-1]["type"], "done")

    def test_project_name_cannot_be_streamed_as_design_stage_after_repair(self):
        self.context = f"[SOURCE: {SOURCE} | PAGE 1]\nC3085 Expo Hills - Phase 1"
        bad = "Design stage: C3085 Expo Hills - Phase 1 [SOURCE: EVIDENCE_1 | PAGE 1]"
        self.fake_model = FakeModel([bad, bad])
        self.source_excerpt_override = None
        events = self._consume(query="What is the design stage?")
        content = self._texts(events)
        self.assertNotIn("Design stage: C3085", content)
        self.assertIn("could not verify", content.lower())
        self.assertEqual(events[-1]["type"], "done")

    def test_supported_native_cover_stage_is_streamed(self):
        self.context = f"[SOURCE: {SOURCE} | PAGE 1]\nC3085 Expo Hills - Phase 1\nDeveloped Design"
        self.fake_model = FakeModel(["Design stage: Developed Design [SOURCE: EVIDENCE_1 | PAGE 1]"])
        events = self._consume(query="What is the design stage?")
        self.assertIn("Design stage: Developed Design", self._texts(events))
        self.assertIn(f"[SOURCE: {SOURCE} | PAGE 1]", self._texts(events))
        self.assertEqual(events[-1]["type"], "done")

    def test_unsupported_number_missing_unit_and_omitted_qualification_are_withheld(self):
        for answer in (
            "AHU-813 design pressure is 999 Pa. [SOURCE: EVIDENCE_1 | PAGE 1]",
            "AHU-813 design pressure is 275. [SOURCE: EVIDENCE_1 | PAGE 1]",
            "AHU-813 design pressure is 275 Pa. [SOURCE: EVIDENCE_1 | PAGE 1]",
        ):
            with self.subTest(answer=answer):
                self.fake_model = FakeModel([answer, answer])
                self.source_excerpt_override = None
                events = self._consume()
                text = self._texts(events)
                self.assertNotIn("999 Pa", text)
                self.assertNotIn("275 Pa. [SOURCE", text)
                self.assertIn("could not verify", text.lower())

    def test_status_revision_and_negation_conflicts_are_withheld(self):
        questions_answers = (
            ("What is the drawing status?", "The drawing status is Draft. [SOURCE: EVIDENCE_1 | PAGE 1]"),
            ("What is the revision?", "The revision is B. [SOURCE: EVIDENCE_1 | PAGE 1]"),
            ("Is a temporary pressure increase permitted?", "A temporary pressure increase is permitted. [SOURCE: EVIDENCE_1 | PAGE 1]"),
        )
        for query, answer in questions_answers:
            with self.subTest(query=query):
                self.fake_model = FakeModel([answer, answer])
                self.context = EVIDENCE + "\nRevision: A. Temporary pressure increase is not permitted."
                self.source_excerpt_override = None
                events = self._consume(query=query)
                self.assertIn("could not verify", self._texts(events).lower())

    def test_conflicting_revisions_publish_ambiguity(self):
        self.context = (
            "[SOURCE: synthetic-air.pdf | PAGE 1]\nAHU-813 design pressure is 275 Pa.\nRevision: A.\n"
            "[SOURCE: synthetic-air.pdf | PAGE 2]\nAHU-813 design pressure is 300 Pa.\nRevision: B."
        )
        self.sources = [{"source": SOURCE, "page": 1}, {"source": SOURCE, "page": 2}]
        self.fake_model = FakeModel(["The current design pressure is 275 Pa. [SOURCE: EVIDENCE_1 | PAGE 1] [SOURCE: EVIDENCE_2 | PAGE 2]"] * 2)
        self.source_excerpt_override = None
        events = self._consume(query="What is the current design pressure for AHU-813?")
        self.assertIn("ambiguous or conflicting", self._texts(events).lower())

    def test_wrong_cross_page_entity_value_association_is_ambiguous(self):
        self.context = (
            "[SOURCE: synthetic-air.pdf | PAGE 1]\nAHU-813 is listed in the plant room.\n"
            "[SOURCE: synthetic-air.pdf | PAGE 2]\nDesign pressure is 275 Pa."
        )
        self.sources = [{"source": SOURCE, "page": 1}, {"source": SOURCE, "page": 2}]
        self.fake_model = FakeModel(["AHU-813 design pressure is 275 Pa. [SOURCE: EVIDENCE_1 | PAGE 1] [SOURCE: EVIDENCE_2 | PAGE 2]"] * 2)
        self.source_excerpt_override = None
        events = self._consume(query="What is the design pressure for AHU-813?")
        text = self._texts(events).lower()
        self.assertTrue("could not verify" in text or "ambiguous or conflicting" in text)

    def test_missing_citation_for_qualitative_claim_is_withheld(self):
        self.fake_model = FakeModel(["The drawing is for coordination only.", "The drawing is for coordination only."])
        self.source_excerpt_override = None
        events = self._consume(query="What is the drawing status?")
        self.assertIn("could not verify", self._texts(events).lower())

    def test_invalid_repair_is_withheld_and_valid_source_excerpt_fallback_is_published(self):
        bad = "AHU-813 design pressure is 999 Pa. [SOURCE: EVIDENCE_1 | PAGE 1]"
        self.fake_model = FakeModel([bad, bad])
        events = self._consume()
        self.assertNotIn("999 Pa", self._texts(events))
        self.assertIn("275 Pa", self._texts(events))

    def test_native_pdf_table_row_fallback_reaches_chat_with_citation(self):
        self.context = '''[SOURCE: synthetic-air.pdf | PAGE 1]
PARKING CALCULATION
| ITEM | NO. | REQUIRED | PROPOSED |
| --- | --- | --- | --- |
| Tandem | | 2 | 1 |'''
        self.fake_model = FakeModel(["Tandem parking required is 99."] * 2)
        events = self._consume(query="What is tandem parking required?")
        content = self._texts(events)
        self.assertIn("ITEM: Tandem", content)
        self.assertIn("REQUIRED: 2", content)
        self.assertIn("[SOURCE: synthetic-air.pdf | PAGE 1]", content)
        self.assertNotIn("required is 99", content.lower())
        self.assertEqual(events[-1]["type"], "done")

    def test_fallback_that_fails_the_final_gate_is_withheld(self):
        bad = "AHU-813 design pressure is 999 Pa. [SOURCE: EVIDENCE_1 | PAGE 1]"
        self.fake_model = FakeModel([bad, bad])
        self.source_excerpt_override = lambda *_a, **_k: "AHU-813 design pressure is 888 Pa. [SOURCE: synthetic-air.pdf | PAGE 1]"
        events = self._consume()
        self.assertNotIn("888 Pa", self._texts(events))
        self.assertIn("could not verify", self._texts(events).lower())

    def test_verifier_exception_emits_withheld_error_and_no_model_answer(self):
        self.fake_model = FakeModel(["Invented engineering claim: 12 kN."])
        self.guard_override = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("synthetic verifier fault"))
        events = self._consume()
        self.assertTrue(any(event.get("type") == "error" for event in events))
        self.assertNotIn("12 kN", self._texts(events))

    def test_model_exception_emits_error_without_fabricating_an_answer(self):
        self.model_error = RuntimeError("synthetic local model fault")
        events = self._consume()
        self.assertTrue(any(event.get("type") == "error" for event in events))
        self.assertNotIn("275 Pa", self._texts(events))

    def test_invalid_self_check_revision_is_revalidated_before_emission(self):
        self.self_check_enabled = True
        self.self_check_override = lambda _answer, _ctx, _query: (
            "AHU-813 design pressure is 999 Pa. [SOURCE: synthetic-air.pdf | PAGE 1]")
        events = self._consume()
        self.assertNotIn("999 Pa", self._texts(events))
        self.assertIn("independently unverified", self._texts(events).lower())
        self.assertIn("275 Pa", self._texts(events))

    def test_explicit_document_code_focuses_memory_and_publishes_matching_rag_evidence(self):
        project_dir = Path(self.temp.name) / "SYNTH"
        project_dir.mkdir()
        target_name = "260610_C3045_2VA_PROJECT_DATA_SHEET.pdf"
        other_name = "C3085_FIRE_REPORT.pdf"
        target_path = project_dir / target_name
        other_path = project_dir / other_name
        target_path.write_bytes(b"C3045 data sheet")
        other_path.write_bytes(b"C3085 fire report")
        for path, text in ((target_path, "Plot No.: 5210986"),
                           (other_path, "There shall be no limit on the number of mezzanines in a room.")):
            Path(str(path) + ".index.json").write_text(json.dumps({
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "processing_complete": True,
                "pages": [{"page": 1, "text": text, "tables": ""}],
            }), encoding="utf-8")
        self.documents = [
            {"filename": target_name, "path": str(target_path), "status": "ready", "chunks": 1},
            {"filename": other_name, "path": str(other_path), "status": "ready", "chunks": 1},
        ]
        self.context = f"[SOURCE: {target_name} | PAGE 1]\nPlot No.: 5210986"
        self.sources = [{"source": target_name, "page": 1}]
        self.fake_model = FakeModel([f"The plot number is 5210986. [SOURCE: EVIDENCE_1 | PAGE 1]"])
        self.memory_enabled = True
        events = self._consume(query="What plot number is listed in the C3045 project data sheet?")

        self.assertIsNotNone(self.memory_call)
        args, _kwargs = self.memory_call
        self.assertEqual(args[2], {target_name})
        self.assertEqual(args[3], target_name)
        answer = self._texts(events)
        self.assertIn("5210986", answer)
        self.assertIn(f"[SOURCE: {target_name} | PAGE 1]", answer)
        self.assertNotIn("mezzanines", answer.lower())

    def test_exact_answer_shortcut_is_checked_before_stream_publication(self):
        self.exact_result = {"status": "SUCCESS", "answer": "AHU-813 design pressure is 999 Pa. [SOURCE: synthetic-air.pdf | PAGE 1]", "sources": SOURCES}
        events = self._consume()
        self.assertNotIn("999 Pa", self._texts(events))
        self.assertIn("could not verify", self._texts(events).lower())

    def test_supported_exact_answer_remains_publishable(self):
        self.exact_result = {"status": "SUCCESS", "answer": GOOD, "sources": SOURCES}
        events = self._consume()
        self.assertIn("275 Pa", self._texts(events))
        self.assertIn("APPROVED_WITH_COMMENTS", self._texts(events))
        self.assertEqual(events[-1]["type"], "done")

    def test_memory_answer_shortcut_is_checked_before_stream_publication(self):
        self.memory_enabled = True
        self.memory_result = {"answer": "AHU-813 design pressure is 999 Pa. [SOURCE: synthetic-air.pdf | PAGE 1]", "sources": SOURCES}
        events = self._consume()
        self.assertNotIn("999 Pa", self._texts(events))
        self.assertIn("could not verify", self._texts(events).lower())


if __name__ == "__main__":
    unittest.main()
