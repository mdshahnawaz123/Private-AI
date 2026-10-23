import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import db
from services import private_pdf


class PrivatePDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = create_engine('sqlite://', poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        db.Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        self.patcher = patch.object(db, 'SessionLocal', self.session)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        with self.session() as session:
            session.add_all([db.User(id=1, username='one'), db.User(id=2, username='two'),
                             db.Project(id=1, name='A'), db.Project(id=2, name='B')])
            session.commit()

    def upload(self, identity, user=1, project=1, contents=b'same source', ready=False):
        path = self.root / f'{identity}.pdf'
        path.write_bytes(contents)
        with self.session() as session:
            session.add(db.UserUpload(id=identity, user_id=user, project_id=project,
                                     filename='Drawing.pdf', path=str(path), size=len(contents),
                                     status='ready' if ready else 'processing'))
            session.commit()
        return str(path)

    def cache(self, path, text='Door width 900 mm'):
        Path(path+'.extracted.txt').write_text(text, encoding='utf-8')
        Path(path+'.index.json').write_text(json.dumps({'private_extraction_version':private_pdf.VERSION,
            'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'extracted_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'processing_complete':True,'pages':[{'page':1,'text':text}]}))

    def test_reuse_requires_same_owner_project_bytes_and_verified_text(self):
        source=self.upload(1,ready=True)
        self.cache(source)
        target=self.upload(2)
        digest=hashlib.sha256(Path(target).read_bytes()).hexdigest()
        self.assertEqual(private_pdf.reusable_result(2,target,digest)[0], 'Door width 900 mm')
        foreign=self.upload(3,user=2)
        self.assertIsNone(private_pdf.reusable_result(3,foreign,digest))
        other_project=self.upload(4,project=2)
        self.assertIsNone(private_pdf.reusable_result(4,other_project,digest))
        Path(source+'.extracted.txt').write_text('tampered')
        self.assertIsNone(private_pdf.reusable_result(2,target,digest))

    def test_changed_source_or_old_extraction_version_is_not_reused(self):
        source=self.upload(1,ready=True)
        self.cache(source)
        target=self.upload(2,contents=b'new source!')
        digest=hashlib.sha256(Path(target).read_bytes()).hexdigest()
        self.assertIsNone(private_pdf.reusable_result(2,target,digest))
        meta=json.loads(Path(source+'.index.json').read_text())
        meta['private_extraction_version']=0
        Path(source+'.index.json').write_text(json.dumps(meta))
        self.assertIsNone(private_pdf.reusable_result(2,target,meta['source_sha256']))

    def test_success_publishes_both_sidecars_before_ready_and_reuse_skips_parser_and_ocr(self):
        first=self.upload(1)
        meta={'pages':[{'page':1,'text':'Width 900 mm','tables':'','vision':''}], 'truncated':False}
        def ocr(path,data,progress_cb=None):
            data['pages'][0]['page_ocr_status']='NATIVE_TEXT_AVAILABLE'
            return 0
        with patch('extract.extract_pdf',return_value=('Width 900 mm',meta)) as native, patch(
                'services.page_ocr.supplement_pages',side_effect=ocr) as scanned:
            result=private_pdf.process(1,first)
            self.assertFalse(result['cache_hit'])
            native.assert_called_once()
            scanned.assert_called_once()
        self.assertEqual(db.get_user_upload(1)['status'],'ready')
        second=self.upload(2)
        with patch('extract.extract_pdf') as native, patch('services.page_ocr.supplement_pages') as scanned:
            result=private_pdf.process(2,second)
            self.assertTrue(result['cache_hit'])
            native.assert_not_called()
            scanned.assert_not_called()
        self.assertEqual(Path(first+'.extracted.txt').read_text(),Path(second+'.extracted.txt').read_text())
        self.assertEqual(db.get_user_upload(2)['status'],'ready')

    def test_truncated_or_failed_ocr_is_never_published_ready(self):
        target=self.upload(1)
        with patch('extract.extract_pdf',return_value=('partial',{'pages':[], 'truncated':True})):
            with self.assertRaisesRegex(ValueError,'page limit'):
                private_pdf.process(1,target)
        meta={'pages':[{'page':1,'text':'partial','page_ocr_status':'FAILED_REVIEW_REQUIRED'}]}
        with patch('extract.extract_pdf',return_value=('partial',meta)), patch('services.page_ocr.supplement_pages',return_value=1):
            with self.assertRaisesRegex(RuntimeError,'required OCR'):
                private_pdf.process(1,target)
        self.assertEqual(db.get_user_upload(1)['status'],'processing')
        self.assertFalse(Path(target+'.index.json').exists())

    def test_cached_document_respects_lowered_page_limit(self):
        from types import SimpleNamespace
        source = self.upload(1, ready=True)
        self.cache(source)
        metadata_path = Path(source + '.index.json')
        meta = json.loads(metadata_path.read_text())
        meta['total_pages'] = 2
        metadata_path.write_text(json.dumps(meta))
        target = self.upload(2)
        with patch('config.get_settings', return_value=SimpleNamespace(max_pages=1)):
            with self.assertRaisesRegex(ValueError, 'page limit'):
                private_pdf.process(2, target)
        self.assertEqual(db.get_user_upload(2)['status'], 'processing')
        self.assertFalse(Path(target + '.index.json').exists())

    def test_chat_request_never_launches_attachment_extraction_or_blocks_on_sleep(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'main.py').read_text(encoding='utf-8'))
        route=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='ask_stream')
        forbidden=[]
        for node in ast.walk(route):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                if node.func.attr in ('extract_pdf','sleep'):
                    forbidden.append((node.func.attr,node.lineno))
        self.assertEqual(forbidden,[])


if __name__=='__main__': unittest.main()
