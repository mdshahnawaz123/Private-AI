"""Terminate only subprocesses created by these synthetic recovery tests."""
import ast
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def run_to_checkpoint(directory,code):
    marker=Path(directory)/'checkpoint'
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT)
    process=subprocess.Popen([sys.executable,'-c',code,str(directory)],cwd=ROOT,env=env,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+45
    while not marker.exists() and time.monotonic()<deadline:
        if process.poll() is not None:
            out,err=process.communicate()
            raise AssertionError('Recovery child exited before checkpoint: '+err.decode(errors='replace'))
        time.sleep(.05)
    if not marker.exists():
        process.kill();out,err=process.communicate()
        raise AssertionError('Recovery checkpoint timed out: '+err.decode(errors='replace'))
    process.kill();process.communicate(timeout=10)

class ProcessInterruptionTests(unittest.TestCase):
    def test_upload_process_kill_preserves_original_and_quarantines_partial(self):
        from services.upload_recovery import quarantine_interrupted_uploads
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'original.pdf').write_bytes(b'original committed source')
            run_to_checkpoint(root,r'''
import ast,os,sys,time
from pathlib import Path
from types import SimpleNamespace
from services.ingestion import save_upload_capped
root=Path(sys.argv[1])
class Reader:
    calls=0
    def read(self,n):
        self.calls+=1
        if self.calls==1:return b'partial replacement'*1024
        (root/'checkpoint').write_text('upload is partially written')
        time.sleep(120)
tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_save_verified_upload')
scope={'os':os,'_save_upload_capped':lambda file,path:save_upload_capped(file,path,1000000),
       'validate_file_content':lambda *a:True}
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-upload','exec'),scope)
scope['_save_verified_upload'](Reader(),str(root/'original.pdf'),'.pdf')
''')
            recovered=quarantine_interrupted_uploads([root],root/'quarantine')
            self.assertEqual((root/'original.pdf').read_bytes(),b'original committed source')
            self.assertEqual(len(recovered),1)
            self.assertEqual(recovered[0]['status'],'REUPLOAD_REQUIRED')
            self.assertGreater(Path(recovered[0]['quarantined']).stat().st_size,0)

    def test_sqlite_kill_before_commit_never_publishes_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with closing(sqlite3.connect(path)) as c:
                c.execute('create table documents(id integer primary key,status text)')
                c.execute("insert into documents values(1,'processing')")
                c.commit()
            run_to_checkpoint(directory,r'''
import sqlite3,sys,time
from pathlib import Path
root=Path(sys.argv[1]);c=sqlite3.connect(root/'state.db')
c.execute('pragma journal_mode=WAL');c.execute('pragma synchronous=FULL')
c.execute("update documents set status='ready' where id=1")
(root/'checkpoint').write_text('uncommitted ready transaction');time.sleep(120)
c.commit()
''')
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute('select status from documents').fetchone()[0],'processing')
                self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')

    def test_real_faiss_directory_swap_kill_recovers_previous_generation(self):
        from langchain_community.vectorstores import FAISS
        from langchain_core.documents import Document
        from langchain_core.embeddings import Embeddings
        import threading
        from types import SimpleNamespace
        class Tiny(Embeddings):
            model='synthetic'
            def embed_documents(self,texts):return [[float(len(t)),1.] for t in texts]
            def embed_query(self,t):return [float(len(t)),1.]
        with tempfile.TemporaryDirectory() as directory:
            scope={'os':os,'FAISS':FAISS,'embedder':Tiny(),'INDEX_DIR':directory,'vectorstores':{},
                '_index_mutation_lock':threading.RLock(),'_bm25_cache':{},
                'logger':SimpleNamespace(warning=lambda *a:None,exception=lambda *a:None)}
            tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
            nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                   ('get_vectorstore','_persist_index_generation','_replace_source_chunks')]
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-index','exec'),scope)
            scope['_replace_source_chunks']('SYNTH',[Document(page_content='committed evidence',metadata={'source':'s.pdf'})],'s.pdf')
            run_to_checkpoint(directory,r'''
import ast,os,sys,time
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
root=Path(sys.argv[1])
class Tiny(Embeddings):
    model='synthetic'
    def embed_documents(self,texts):return [[float(len(t)),1.] for t in texts]
    def embed_query(self,t):return [float(len(t)),1.]
embed=Tiny();candidate=FAISS.from_documents([Document(page_content='unpublished evidence')],embed)
original=os.replace
def replace(source,target):
    original(source,target)
    if '.previous-' in str(target):
        (root/'checkpoint').write_text('old generation renamed; new not published')
        time.sleep(120)
os.replace=replace
tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_persist_index_generation')
scope={'os':os,'INDEX_DIR':str(root),'embedder':embed}
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-publication','exec'),scope)
scope['_persist_index_generation']('SYNTH',candidate)
''')
            scope['vectorstores'].clear()
            recovered=scope['get_vectorstore']('SYNTH')
            self.assertEqual(recovered.index.ntotal,1)
            self.assertEqual({d.page_content for d in recovered.docstore._dict.values()},{'committed evidence'})

    def test_killed_queue_owner_replays_once_and_keeps_hash(self):
        from services.jobs import JobQueue,source_hash
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.write_text('synthetic immutable source')
            run_to_checkpoint(root,r'''
import sys,time
from pathlib import Path
from services.jobs import JobQueue
root=Path(sys.argv[1])
def handler(payload):
    (root/'checkpoint').write_text('durable job claimed; worker interrupted')
    time.sleep(120)
queue=JobQueue(str(root),{'document':handler})
queue.enqueue('document',str(root/'source'),{});queue.start();time.sleep(120)
''')
            executions=[];queue=JobQueue(str(root),{'document':lambda payload:executions.append(payload)})
            queue.start()
            deadline=time.monotonic()+10
            while queue.status().get('completed')!=1 and time.monotonic()<deadline:time.sleep(.05)
            queue.stop()
            self.assertEqual(queue.status(),{'completed':1})
            self.assertEqual(executions,[{}])
            with queue.connect() as c:
                row=c.execute('select attempts,sha256 from jobs').fetchone()
                self.assertEqual(row['attempts'],2)
                self.assertEqual(row['sha256'],source_hash(source))
