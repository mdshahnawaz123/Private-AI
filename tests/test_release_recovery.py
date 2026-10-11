import ast,json,os,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from services.jobs import JobQueue

class ReleaseRecovery(unittest.TestCase):
    def test_configured_page_limit_and_truncation_cannot_publish_ready(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='process_document')
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'source.pdf');Path(path).write_bytes(b'%PDF synthetic source')
            calls=[];statuses=[]
            def extract_pdf(*args,**kw):
                calls.append(kw)
                return 'partial source',{'type':'pdf','truncated':True,'pages':[{'page':1,'text':'partial source'}]}
            logger=SimpleNamespace(info=lambda *a:None,warning=lambda *a:None,exception=lambda *a:None)
            scope={'os':os,'json':json,'PROGRESS':{},'_pkey':lambda *a:a,'logger':logger,
                'vision':SimpleNamespace(is_image=lambda path:False,describe_image=lambda *a:''),'cad':SimpleNamespace(is_cad=lambda path:False),
                'extract':SimpleNamespace(extract_pdf=extract_pdf),'db':SimpleNamespace(
                    set_progress=lambda *a:None,get_progress=lambda *a:{},clear_progress=lambda *a:None,
                    update_document_status=lambda *a:statuses.append(a))}
            exec(compile(ast.Module(body=[function],type_ignores=[]),'document-pipeline','exec'),scope)
            with patch('config.get_settings',return_value=SimpleNamespace(max_pages=1)):
                scope['process_document']('Synthetic',path,'source.pdf','','Reports')
            self.assertEqual(calls[0]['max_pages'],1)
            self.assertEqual(statuses[-1][-1],'error')
            self.assertFalse(Path(path+'.index.json').exists())

    def test_index_flush_failure_preserves_published_generation(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_persist_index_generation')
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'Synthetic';target.mkdir();(target/'index.faiss').write_bytes(b'published')
            def write(directory):
                Path(directory).mkdir();(Path(directory)/'index.faiss').write_bytes(b'new');(Path(directory)/'index.pkl').write_bytes(b'new pickle')
            candidate=SimpleNamespace(save_local=write,index=SimpleNamespace(d=2,ntotal=1))
            scope={'os':os,'INDEX_DIR':root,'embedder':SimpleNamespace(model='synthetic')}
            exec(compile(ast.Module(body=[function],type_ignores=[]),'index-publication','exec'),scope)
            with patch('os.fsync',side_effect=OSError('disk flush failed')):
                with self.assertRaises(OSError):scope['_persist_index_generation']('Synthetic',candidate)
            self.assertEqual((target/'index.faiss').read_bytes(),b'published')

    def test_geometry_does_not_auto_discard_small_labels_or_long_strips(self):
        from services.pipeline import classify_image
        self.assertEqual(classify_image(100,100),'UNKNOWN')
        self.assertEqual(classify_image(1200,100),'UNKNOWN')

    def test_crash_restart_does_not_reset_retry_budget(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source';source.write_text('unchanged')
            queue=JobQueue(root,{'document':lambda payload:self.fail('exhausted job executed')})
            queue.enqueue('document',str(source),{})
            queue.claim()
            with queue.connect() as conn:conn.execute("UPDATE jobs SET attempts=3")
            queue.start();queue.stop()
            self.assertEqual(queue.status(),{'failed':1})
            self.assertIsNone(queue.enqueue_stranded('document',str(source),{}))
            self.assertEqual(queue.status(),{'failed':1})
            source.write_text('explicit new source version')
            self.assertIsNotNone(queue.enqueue_stranded('document',str(source),{}))

    def test_source_mutation_in_handler_never_completes(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source';source.write_text('old')
            queue=JobQueue(root,{'document':lambda payload:source.write_text('changed')})
            invalidated=[]
            queue.failure_handlers['document']=lambda payload,error:invalidated.append(error)
            queue.enqueue('document',str(source),{});queue.run_one()
            self.assertEqual(queue.status(),{'failed':1})
            self.assertIn('Source changed during processing',invalidated[0])

    def test_metadata_write_is_atomic_and_original_survives_failure(self):
        import extract
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'meta.json')
            self.assertTrue(extract.save_json(path,{'version':1}))
            with patch('os.replace',side_effect=OSError('publication interrupted')):
                self.assertFalse(extract.save_json(path,{'version':2}))
            self.assertEqual(json.loads(Path(path).read_text()),{'version':1})
            self.assertEqual(len(list(Path(root).iterdir())),1)

    def test_ocr_resume_is_idempotent_and_clears_stale_error(self):
        import pymupdf
        from services.page_ocr import supplement_pages
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'scan.pdf')
            doc=pymupdf.open();doc.new_page();doc.save(path);doc.close()
            digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
            cache=Path(path+'_page_ocr');cache.mkdir()
            (cache/(digest+'-p1.json')).write_text(json.dumps({'text':'Equipment SYNTH-060','confidence':0.8,'boxes':[]}))
            meta={'pages':[{'page':1,'text':'','vision':'','page_ocr_error':'old failure'}]}
            supplement_pages(path,meta);supplement_pages(path,meta)
            self.assertEqual(meta['pages'][0]['vision'].count('Equipment SYNTH-060'),1)
            self.assertNotIn('page_ocr_error',meta['pages'][0])
            self.assertEqual(meta['pages'][0]['verification_state'],'REVIEW_REQUIRED')

    def test_pipeline_does_not_publish_ready_or_skip_failed_pages(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'services/pipeline.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='process_document_pipeline')
        assignments=[n for n in ast.walk(function) if isinstance(n,ast.Assign)
                     and any(isinstance(t,ast.Attribute) and t.attr=='status' for t in n.targets)]
        self.assertFalse(assignments,'Supplemental pipeline must not publish document status')
        text=ast.unparse(function)
        self.assertIn("p.page_status in ('READY', 'REVIEW_REQUIRED')",text)
        self.assertIn("raise RuntimeError('Visual/structured pipeline incomplete')",text)

    def test_high_confidence_model_output_remains_review_required(self):
        from services.vision_adapter import extract_visual_table
        completed=SimpleNamespace(returncode=0,stdout='EXPO_VISUAL_RESULT='+json.dumps({'success':True,'confidence':'HIGH','raw_text':'invented model table'}))
        with patch('subprocess.run',return_value=completed):result=extract_visual_table('synthetic.png')
        self.assertEqual(result['verification_state'],'REVIEW_REQUIRED')
        self.assertEqual(result['interpretation_state'],'INTERPRETED')
