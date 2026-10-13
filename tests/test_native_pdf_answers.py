"""Previously unseen PDFs use native evidence, not audited fixture answers."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz
from extract import extract_pdf
from intelligence.native_pdf_answers import native_pdf_answer
from intelligence.exact_answers import exact_answer
from intelligence.answer_publication import validate_precomputed_answer


class NativePDFAnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def document(self, text, name='never-seen-report.pdf', **changes):
        path = self.root / name
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((40, 50), text)
            pdf.save(path)
        _, meta = extract_pdf(str(path), deep=False)
        meta.update(processing_complete=True, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        meta.update(changes)
        Path(str(path) + '.index.json').write_text(json.dumps(meta), encoding='utf-8')
        return {'filename': name, 'path': str(path), 'status': 'ready'}

    def test_new_native_pdf_extracts_then_answers_through_live_selector_and_final_gate(self):
        doc = self.document('AHU-917 design pressure is 318 Pa, subject to vendor confirmation.')
        question = 'What design pressure is specified for AHU-917?'
        result = exact_answer(question, [doc])
        self.assertEqual(result['method'], 'NATIVE_SOURCE_QUOTATION')
        published, issues, sources = validate_precomputed_answer(result['answer'], [doc], result['sources'], question)
        self.assertEqual(issues, [])
        self.assertIn('318 Pa, subject to vendor confirmation', published)
        self.assertEqual(sources, [{'source': doc['filename'], 'page': 1}])

    def test_unseen_stage_answer_needs_no_model(self):
        doc = self.document('Project name: Aurora Campus\nDesign stage: Client Review Phase')
        result = exact_answer('What is the design stage?', [doc])
        self.assertEqual(result['method'], 'NATIVE_SOURCE_FIELD')
        answer, issues, _ = validate_precomputed_answer(result['answer'], [doc], result['sources'], 'What is the design stage?')
        self.assertEqual(issues, [])
        self.assertIn('client review phase', answer)

    def test_conflicting_native_documents_do_not_get_selected_by_iteration_order(self):
        a = self.document('Design stage: Concept Design', 'first.pdf')
        b = self.document('Design stage: Developed Design', 'second.pdf')
        for docs in ([a, b], [b, a]):
            self.assertIsNone(native_pdf_answer('What is the design stage?', docs))

    def test_changed_source_cannot_use_stale_extraction(self):
        doc = self.document('Design stage: Concept Design')
        Path(doc['path']).write_bytes(b'changed')
        self.assertIsNone(native_pdf_answer('What is the design stage?', [doc]))

    def test_processing_state_and_hash_are_required(self):
        for changes in ({'processing_complete': False}, {'truncated': True}, {'source_sha256': None}):
            with self.subTest(changes=changes):
                doc = self.document('Design stage: Concept Design', **changes)
                self.assertIsNone(native_pdf_answer('What is the design stage?', [doc]))

    def test_not_ready_documents_are_excluded(self):
        doc = self.document('Design stage: Concept Design')
        doc['status'] = 'processing'
        self.assertIsNone(native_pdf_answer('What is the design stage?', [doc]))

    def test_wrong_page_and_missing_evidence(self):
        doc = self.document('AHU-917 design pressure is 318 Pa.')
        self.assertIsNone(native_pdf_answer('What pressure for AHU-917 on page 2?', [doc]))
        self.assertIsNone(native_pdf_answer('What pressure for AHU-999?', [doc]))

    def test_ocr_observations_are_not_upgraded_to_native_answers(self):
        doc = self.document('')
        sidecar = Path(doc['path'] + '.index.json')
        meta = json.loads(sidecar.read_text())
        meta['pages'][0].update(vision='AHU-917 design pressure is 318 Pa.', verification_state='REVIEW_REQUIRED')
        sidecar.write_text(json.dumps(meta))
        self.assertIsNone(native_pdf_answer('What pressure for AHU-917?', [doc]))

    def test_legacy_filename_shortcuts_are_not_called_by_live_selector(self):
        doc = self.document('Drawing number: ZX88-ST-913', 'unseen-SDW.pdf')
        with patch('intelligence.phase4c_exact.drawing_annotation_answer', side_effect=AssertionError('fixture helper called')):
            result = exact_answer('What is the drawing number?', [doc])
        self.assertNotIn('C5055', str(result))

    def test_budget_overflow_does_not_hide_conflicting_sources(self):
        doc = self.document('Design stage: Concept Design')
        self.assertIsNone(native_pdf_answer('What is the design stage?', [doc], budget=10))

    def test_quotes_do_not_establish_approval_or_calculate(self):
        doc = self.document('Design stage: Concept Design\nAHU-917 design pressure is 318 Pa.')
        for q in ('What is the latest design stage?', 'Is the design stage approved?', 'Calculate the pressure for AHU-917'):
            self.assertIsNone(native_pdf_answer(q, [doc]))


if __name__ == '__main__':
    unittest.main()
