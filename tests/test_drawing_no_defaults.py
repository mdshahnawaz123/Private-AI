import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from intelligence.exact_answers import exact_answer, drawing_annotation_answer
from intelligence.inspection_answers import inspection_answer
from intelligence.page_context import _extract_drawing_structures
from intelligence.native_schedule import native_schedule_answer


class DrawingNoDefaultsTests(unittest.TestCase):
    def test_title_requires_explicit_native_field_and_current_source(self):
        import fitz
        from intelligence.native_titleblock import native_title_answer
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'title.pdf'
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((300, 300), 'Drawing Title')
                page.insert_text((300, 330), 'SYNTHETIC STRUCTURAL PLAN')
                page.insert_text((300, 350), 'LEVEL 2 ZONE 7')
                page.insert_text((300, 390), 'Approved')
                pdf.save(path)
            Path(str(path) + '.index.json').write_text(json.dumps({'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
            docs = [{'filename': path.name, 'path': str(path)}]
            query = 'Give title, level and zone'
            result = native_title_answer(query, docs)
            self.assertIn('SYNTHETIC STRUCTURAL PLAN LEVEL 2 ZONE 7', result['answer'])
            self.assertNotIn('Approved', result['answer'])
            self.assertIsNone(native_title_answer(query + ' page 2', docs))
            path.write_bytes(b'changed')
            self.assertIsNone(native_title_answer(query, docs))

    def test_review_options_do_not_select_approval(self):
        from engines.universal_drawing_engine import get_universal_drawing_engine
        stamp = get_universal_drawing_engine()._extract_review_stamp(None, [], 'Code A Code B Code C')
        self.assertEqual(stamp['status'], 'REVIEW_REQUIRED')

    def test_native_schedule_requires_exact_rows_units_hash_and_page(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic.pdf'
            path.write_bytes(b'synthetic')
            meta = {'source_sha256': hashlib.sha256(b'synthetic').hexdigest(), 'pages': [
                {'page': 2, 'text': 'ALL DIMENSIONS ARE IN MILLIMETERS\nTYPE\nWIDTH\nLENGTH\nDEPTH\nZZ99\n2100\n2300\n375\n'}]}
            sidecar = Path(str(path) + '.index.json')
            sidecar.write_text(json.dumps(meta))
            docs = [{'path': str(path), 'filename': path.name}]
            query = 'Width length depth of ZZ99'
            result = native_schedule_answer(query, docs)
            for value in ('2100 mm', '2300 mm', '375 mm'):
                self.assertIn(value, result['answer'])
            focused = native_schedule_answer('Regarding "synthetic.pdf": ' + query, docs)
            self.assertEqual(result, focused)
            self.assertEqual(result['sources'][0]['page'], 2)
            self.assertIsNone(native_schedule_answer(query + ' page 1', docs))
            meta['pages'].append({'page': 3, 'text': meta['pages'][0]['text'].replace('375', '400')})
            sidecar.write_text(json.dumps(meta))
            self.assertIsNone(native_schedule_answer(query, docs))
            path.write_bytes(b'changed')
            self.assertIsNone(native_schedule_answer(query, docs))

    def test_tokens_do_not_invent_dimensions_or_approval(self):
        text = 'Code A Code B Code C SSL TOB F1 F5 AG Approved DROP PANEL SCEDULE'
        self.assertEqual(_extract_drawing_structures(text), '')
        self.assertIsNone(drawing_annotation_answer('depth difference DP10 DP01', []))
        self.assertIsNone(drawing_annotation_answer('consultant review stamp date', []))

    def test_approval_question_retains_review_comments(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic.pdf'
            path.write_bytes(b'synthetic')
            meta = {'source_sha256': hashlib.sha256(b'synthetic').hexdigest(), 'pages': [
                {'page': 1, 'text': '', 'inspection': {'annotations': [
                    {'type': 'Text', 'id': 'r1', 'bbox': [0, 0, 1, 1],
                     'content': 'Approval is limited to GA concrete work only.'}]}}]}
            Path(str(path) + '.index.json').write_text(json.dumps(meta))
            docs = [{'path': str(path), 'filename': path.name, 'status': 'ready_with_warnings'}]
            answer = exact_answer('Is this drawing approved for all work? What review comments apply?', docs)
            self.assertEqual(answer['status'], 'SUCCESS')
            self.assertIn('limited to GA concrete work', answer['answer'])
            self.assertIn('REVIEW_REQUIRED', answer['answer'])
            path.write_bytes(b'changed')
            self.assertEqual(inspection_answer('review comments', docs)['status'], 'NOT_FOUND')

