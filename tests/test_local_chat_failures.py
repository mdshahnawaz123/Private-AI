import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import local_chat


class Response:
    def __init__(self,lines): self.lines=lines
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self): pass
    def iter_lines(self): yield from self.lines


class LocalChatFailures(unittest.TestCase):
    def test_empty_answer_is_an_error(self):
        chat=local_chat.LocalChatOllama('test')
        with patch('httpx.stream',return_value=Response([json.dumps({'done':True})])),patch('local_chat.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'no answer'):
                list(chat.stream([SimpleNamespace(type='human',content='question')]))

    def test_partial_answer_is_never_retried(self):
        lines=[json.dumps({'message':{'content':'partial'}}),json.dumps({'error':'offline'})]
        with patch('httpx.stream',return_value=Response(lines)) as stream:
            with self.assertRaisesRegex(RuntimeError,'offline'):
                list(local_chat.LocalChatOllama('test').stream([]))
            self.assertEqual(stream.call_count,1)

    def test_deadline_stops_without_retry(self):
        with patch('httpx.stream',return_value=Response([json.dumps({'done':True})])) as stream,patch('local_chat.time.monotonic',side_effect=[0,121,122]):
            with self.assertRaises(TimeoutError):
                list(local_chat.LocalChatOllama('test',timeout=120).stream([]))
            self.assertEqual(stream.call_count,1)


if __name__=='__main__': unittest.main()
