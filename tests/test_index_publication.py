"""Exercise real FAISS publication without importing the running application."""
import ast
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


class TinyEmbeddings(Embeddings):
    fail=False
    def embed_documents(self,texts):
        if self.fail: raise RuntimeError('embedding offline')
        return [[float(len(t)),1.0] for t in texts]
    def embed_query(self,text): return [float(len(text)),1.0]


class IndexPublication(unittest.TestCase):
    def test_replacement_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            embedder=TinyEmbeddings()
            scope={'os':os,'FAISS':FAISS,'embedder':embedder,'INDEX_DIR':directory,
                   'vectorstores':{},'_index_mutation_lock':threading.RLock(),
                   '_bm25_cache':{},'logger':SimpleNamespace(warning=lambda *a:None,exception=lambda *a:None)}
            tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf8'))
            selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                      ['get_vectorstore','_persist_index_generation','_replace_source_chunks']]
            exec(compile(ast.Module(body=selected,type_ignores=[]),'audited-index-functions','exec'),scope)
            publish=scope['_replace_source_chunks']
            publish('A',[Document(page_content='old',metadata={'source':'a.pdf'})],'a.pdf')
            publish('A',[Document(page_content='other',metadata={'source':'b.pdf'})],'b.pdf')
            publish('A',[Document(page_content='new evidence',metadata={'source':'a.pdf'})],'a.pdf')
            self.assertEqual(scope['vectorstores']['A'].index.ntotal,2)
            embedder.fail=True
            with self.assertRaises(RuntimeError):
                publish('A',[Document(page_content='bad',metadata={'source':'a.pdf'})],'a.pdf')
            self.assertEqual(scope['vectorstores']['A'].index.ntotal,2)
            scope['vectorstores'].clear()
            recovered=scope['get_vectorstore']('A')
            self.assertEqual({d.page_content for d in recovered.docstore._dict.values()},{'new evidence','other'})
            # Simulate a crash after the previous directory was renamed.
            target=Path(directory)/'A'
            target.rename(Path(directory)/'A.previous-interrupted')
            scope['vectorstores'].clear()
            self.assertEqual(scope['get_vectorstore']('A').index.ntotal,2)
            # A corrupt pickle is rejected before deserialization.
            interrupted=Path(directory)/'A.previous-interrupted'
            with open(interrupted/'index.pkl','ab') as handle:handle.write(b'corrupt')
            # Make this the newest preceding generation selected by recovery.
            os.utime(interrupted,None)
            scope['vectorstores'].clear()
            self.assertIsNone(scope['get_vectorstore']('A'))


if __name__=='__main__': unittest.main()
