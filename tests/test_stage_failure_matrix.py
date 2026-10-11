"""Fault injection at actual process_document boundaries; no model simulation is
reported as a successful OCR/vision execution or as a hardware crash test."""
import ast,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class Session:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def query(self,*args):return self
    def filter_by(self,**kw):return self
    def first(self):return SimpleNamespace(id=1)
    def all(self):return []

class StageFailureMatrix(unittest.TestCase):
    def test_no_stage_failure_publishes_ready_and_retry_can_complete(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='process_document')
        stages=('PDF_EXTRACTION','OCR','VISION','STRUCTURED_EXTRACTION','STRUCTURED_DATABASE','EMBEDDING','INDEX','DB_COMMIT')
        for stage in stages:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'source.pdf';path.write_bytes(b'%PDF synthetic immutable source')
                statuses=[];active=[stage]
                def fail_at(name):
                    if active[0]==name:raise RuntimeError('injected interruption at '+name)
                def pdf(*args,**kwargs):
                    fail_at('PDF_EXTRACTION')
                    return 'native source',{'type':'pdf','pages':[{'page':1,'text':'Synthetic native source evidence','tables':'','vision':''}]}
                def save(path,data):
                    fail_at('STRUCTURED_DATABASE')
                    Path(path).write_text(json.dumps(data));return True
                def status(*args):
                    if args[-1] in ('ready','ready_with_warnings'):fail_at('DB_COMMIT')
                    statuses.append(args[-1])
                def index(*args):
                    fail_at('EMBEDDING');fail_at('INDEX');return 1
                def structured(*args):fail_at('STRUCTURED_EXTRACTION');return 1
                pipeline=SimpleNamespace(extract_structured_tables=structured,extract_quantities=lambda *a:0)
                scope={'os':os,'json':json,'_pkey':lambda *a:a,'db':SimpleNamespace(SessionLocal=Session,Project=object(),ImageRecord=object(),
                    set_progress=lambda *a:None,get_progress=lambda *a:{},clear_progress=lambda *a:None,update_document_status=status),
                    'vision':SimpleNamespace(is_image=lambda *a:False,describe_image=lambda *a:''),'cad':SimpleNamespace(is_cad=lambda *a:False),
                    'extract':SimpleNamespace(extract_pdf=pdf,save_json=save),'index_structured':index,
                    'logger':SimpleNamespace(info=lambda *a:None,warning=lambda *a:None,exception=lambda *a:None)}
                exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-ingestion','exec'),scope)
                with (patch('services.page_ocr.supplement_pages',side_effect=lambda *a:fail_at('OCR')),
                     patch('services.pipeline.process_document_pipeline',side_effect=lambda *a,**kw:fail_at('VISION') or 'READY'),
                     patch('services.ingestion.get_pipeline',return_value=pipeline),
                     patch('config.get_settings',return_value=SimpleNamespace(max_pages=100,enable_structured_tables=True,enable_quantities_store=False,enable_document_memory=False))):
                    scope['process_document']('SYNTH',str(path),path.name,'','Reports')
                    self.assertTrue(statuses)
                    self.assertNotIn('ready',statuses)
                    self.assertNotIn('ready_with_warnings',statuses)
                    active[0]=None
                    scope['process_document']('SYNTH',str(path),path.name,'','Reports')
                self.assertEqual(statuses[-1],'ready_with_warnings')
                metadata=json.loads(Path(str(path)+'.index.json').read_text())
                self.assertTrue(metadata['processing_complete'])
                self.assertEqual(path.read_bytes(),b'%PDF synthetic immutable source')
