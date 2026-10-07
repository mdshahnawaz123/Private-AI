import json
import tempfile
import unittest
import threading
from pathlib import Path
from services.jobs import JobQueue
from intelligence.page_context import select_page_context


class DurableJobsTests(unittest.TestCase):
    def test_reopen_deduplicate_and_finish(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/'source.pdf'
            source.write_bytes(b'original')
            queue = JobQueue(root)
            job_id = queue.enqueue('document',str(source),{'x':1})
            self.assertEqual(job_id,queue.enqueue('document',str(source),{'x':1}))
            calls=[]
            reopened=JobQueue(root,{'document':calls.append})
            self.assertTrue(reopened.run_one())
            self.assertEqual(calls,[{'x':1}])
            self.assertEqual(reopened.status(),{'completed':1})
            self.assertFalse(reopened.active(str(source)))

    def test_changed_source_never_runs(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source'
            source.write_text('old')
            calls=[]
            queue=JobQueue(root,{'document':calls.append})
            queue.enqueue('document',str(source),{})
            source.write_text('new')
            queue.run_one()
            self.assertEqual(calls,[])
            self.assertEqual(queue.status(),{'failed':1})

    def test_retry_and_terminal_failure(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source'
            source.write_text('data')
            def failing(payload): raise RuntimeError('embedding offline')
            queue=JobQueue(root,{'document':failing})
            queue.enqueue('document',str(source),{})
            for attempt in range(3):
                with queue.connect() as conn: conn.execute('UPDATE jobs SET available=0')
                self.assertTrue(queue.run_one())
            self.assertEqual(queue.status(),{'failed':1})

    def test_interrupted_job_replays_and_runner_excludes_second_process(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source'
            source.write_text('data')
            finished=threading.Event()
            queue=JobQueue(root,{'document':lambda payload:finished.set()})
            queue.enqueue('document',str(source),{})
            queue.claim()  # Simulate termination after durable claim.
            queue.start()
            second=JobQueue(root)
            with self.assertRaises(RuntimeError): second.start()
            self.assertTrue(finished.wait(5))
            queue.stop()
            self.assertEqual(queue.status(),{'completed':1})

    def test_later_page_ranks_and_preserves_attribution(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source.pdf'
            Path(str(source)+'.index.json').write_text(json.dumps({'pages':[
                {'page':1,'text':'cover '*10000},{'page':48,'text':'Foundation settlement 20 mm'}]}))
            sources, context=select_page_context(str(source),'source.pdf','foundation settlement',budget=2000)
            self.assertEqual(sources[0]['page'],48)
            self.assertIn('PAGE 48',context)
            self.assertIn('20 mm',context)

if __name__=='__main__': unittest.main()
