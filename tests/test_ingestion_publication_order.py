import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class Session:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def query(self,*args): return self
    def filter_by(self,**kwargs): return self
    def first(self): return SimpleNamespace(id=1)
    def all(self): return [SimpleNamespace(page_number=2,visual_description='machine image evidence')]


class IngestionPublicationOrder(unittest.TestCase):
    def test_visual_evidence_is_saved_before_index_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            metadata={'type':'pdf','pages':[{'page':2,'text':'native evidence','tables':'','vision':''}]}
            extractor=SimpleNamespace(extract_pdf=lambda *a,**kw:('native evidence',metadata),
                save_json=lambda path,data:Path(path).write_text(json.dumps(data),encoding='utf8'))
            database=SimpleNamespace(SessionLocal=Session,Project=object(),ImageRecord=object(),
                set_progress=lambda *a:None,get_progress=lambda *a:{},clear_progress=lambda *a:None,
                update_document_status=lambda *a:events.append(('status',a[-1])))
            def index(project,meta,*args):
                self.assertIn('machine image evidence',meta['pages'][0]['vision'])
                self.assertEqual(events[0],('visual','complete'))
                events.append(('index','published'))
                return 2
            scope={'os':os,'json':json,'PROGRESS':{},'_pkey':lambda *a:tuple(a),'db':database,
                   'vision':SimpleNamespace(is_image=lambda *a:False,describe_image=lambda *a:''),'cad':SimpleNamespace(is_cad=lambda *a:False),
                   'extract':extractor,'index_structured':index,'logger':SimpleNamespace(info=lambda *a:None,warning=lambda *a:None,exception=lambda *a:None)}
            tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf8'))
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='process_document')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'audited-ingestion-function','exec'),scope)
            def pipeline(*a,**kwargs): events.append(('visual','complete')); return 'WARNINGS'
            with patch('services.page_ocr.supplement_pages',return_value=0),patch('services.pipeline.process_document_pipeline',side_effect=pipeline),patch('config.get_settings',return_value=SimpleNamespace(enable_structured_tables=False,enable_quantities_store=False)):
                path=str(Path(directory)/'source.pdf')
                Path(path).write_bytes(b'%PDF original source')
                scope['process_document']('A',path,'source.pdf','','Reports')
            self.assertEqual(events[-1],('status','ready_with_warnings'))
            self.assertIn('machine image evidence',Path(path+'.extracted.txt').read_text(encoding='utf8'))


if __name__=='__main__': unittest.main()
