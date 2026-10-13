import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from intelligence.document_agent import run_agent


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='output')
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'source.pdf'
        self.path.write_bytes(b'synthetic')
        self.meta = {'source_sha256': hashlib.sha256(b'synthetic').hexdigest(),
                     'processing_complete': True, 'pages': []}
        self.save()

    def save(self):
        Path(str(self.path) + '.index.json').write_text(json.dumps(self.meta))

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_tool_never_executes(self):
        result = run_agent('execute command', self.root, self.path, lambda _: '{"tool":"shell"}')
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')

    def test_malformed_plan_abstains(self):
        self.assertEqual(run_agent('x', self.root, self.path, lambda _: 'I know the answer')['status'], 'REVIEW_REQUIRED')

    def test_cross_project_denied(self):
        with self.assertRaises(ValueError):
            run_agent('x', self.root / 'other', self.path)

    def test_stale_source_denied(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            run_agent('x', self.root, self.path)

    def test_partial_denied(self):
        self.meta['processing_complete'] = False
        self.save()
        with self.assertRaises(ValueError):
            run_agent('x', self.root, self.path)

    def test_source_change_during_plan_denied(self):
        def change(_):
            self.path.write_bytes(b'changed')
            return '{"tool":"abstain"}'
        with self.assertRaises(ValueError):
            run_agent('x', self.root, self.path, change)

    def test_guard_block_is_preserved(self):
        reading = {'status': 'SUCCESS', 'answer': 'unsupported', 'sources': []}
        with patch.dict('intelligence.document_agent.TOOLS', {'read_title': lambda *a: reading}), \
             patch('intelligence.answer_guard.guarded_answer', return_value=('withheld', ['failure'])):
            result = run_agent('x', self.root, self.path, lambda _: '{"tool":"read_title"}')
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['answer'], 'withheld')


if __name__ == '__main__':
    unittest.main()
