"""Isolated regressions for actual audit defects; never imports the live main module."""
import ast
import os
from pathlib import Path
import sys
import uuid
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
runtime = ROOT/'output'/'audit-2026-10-06'/('regression-runtime-'+uuid.uuid4().hex[:8])
runtime.mkdir(parents=True,exist_ok=True)
os.environ['EXPO_DATA_DIR'] = str(runtime)
os.environ['EXPO_DATABASE_URL'] = 'sqlite:///'+str(runtime/'test.db')
import db
from intelligence.document_query import robust_parse_query, execute_structured_query, query_document
from intelligence.table_evidence import table_row_units
from services.ingestion import contained_upload_path


class AuditHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.admin = {'id':1,'username':'system','role':'admin'}
        for name in ['A','B']:
            db.create_project(name,cls.admin)
        cls.folder = db.create_folder('A','Allowed',by=cls.admin)
        db.record_document('A','schedule.pdf',str(runtime/'schedule.pdf'),1,
                           folder_id=cls.folder['id'],user=cls.admin)
        with db.SessionLocal() as session:
            cls.pid = session.query(db.Project).filter_by(name='A').first().id
            session.query(db.StructuredRecord).delete()
            for ent,val,conf in [('TOWER 7 LEVEL 02',2054,'HIGH'),
                                 ('TOWER 7 LEVEL 03',777,'HIGH'),
                                 ('TOWER 8 LEVEL 02',3229,'HIGH'),
                                 ('TOWER 7 LEVEL 02',9999,'AMBIGUOUS')]:
                session.add(db.StructuredRecord(project_id=cls.pid,doc='schedule.pdf',page=6,
                    entity=ent,field='Floor GFA (sqm)',raw_value=str(val),value=val,confidence=conf))
            session.commit()

    def test_upload_rejects_escape_components(self):
        for bad in ['../x.pdf',r'..\x.pdf','C:\\x.pdf','/x.pdf','x.pdf:payload','..','x.pdf.']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                contained_upload_path(str(runtime),'A','Docs',bad)
        with self.assertRaises(ValueError):
            contained_upload_path(str(runtime),'../B','Docs','x.pdf')

    def test_health_route_is_unique(self):
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        health=[]
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if isinstance(d,ast.Call) and d.args and isinstance(d.args[0],ast.Constant) and d.args[0].value=='/health':
                        health.append(n)
        self.assertEqual(len(health),1)
        import asyncio
        from types import SimpleNamespace
        from config import get_settings
        node=health[0]
        node.decorator_list=[]
        namespace={'Request':object,'db':db}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'audited-health-function','exec'),namespace)
        payload=asyncio.run(namespace['health'](SimpleNamespace(state=SimpleNamespace(user=None))))
        self.assertFalse(payload['documents_indexed'])
        self.assertEqual(payload['model'],get_settings().chat_model)

    def test_tower_and_level_intersect(self):
        plan=robust_parse_query('Tower 7 Level 02 GFA',self.pid)
        self.assertEqual(plan['fields'],['gfa'])
        response,_=execute_structured_query(plan,self.pid,'',self.admin)
        self.assertEqual(response['status'],'SUCCESS')
        self.assertEqual(response['provenance'][0]['value'],2054)
        self.assertEqual(response['provenance'][0]['verification_status'],'EXTRACTED')

    def test_project_name_and_id_resolve_same_boundary(self):
        plan=robust_parse_query('Tower 7 Level 02 GFA','A')
        by_name,_=execute_structured_query(plan,'A','',self.admin)
        by_id,_=execute_structured_query(plan,self.pid,'',self.admin)
        self.assertEqual(by_name['answer'],by_id['answer'])
        other,_=execute_structured_query(plan,'B','',self.admin)
        self.assertEqual(other['status'],'NOT_FOUND')

    def test_no_actor_and_no_folder_cannot_read_records(self):
        plan=robust_parse_query('Tower 7 Level 02 GFA','A')
        r,_=execute_structured_query(plan,'A','',None)
        self.assertEqual(r['status'],'NOT_FOUND')
        user=db.create_user('limited-audit','unused',role='user') if not db.get_user_by_username('limited-audit') else db.get_user_by_username('limited-audit')
        db.assign_member('A',user['id'])
        r,_=execute_structured_query(plan,'A','',user)
        self.assertEqual(r['status'],'NOT_FOUND')

    def test_model_failure_is_error_not_placeholder(self):
        def broken(prompt): raise TimeoutError('model offline')
        response,_=query_document('summarize the supplied evidence','A',lambda *a,**kw:([{'source':'schedule.pdf','page':6}],'wind evidence'),broken,{'user':self.admin})
        self.assertEqual(response['status'],'ERROR')
        self.assertNotIn('Generated Answer',response['answer'])

    def test_empty_evidence_never_calls_model(self):
        def forbidden(prompt): self.fail('Model must not run without evidence')
        response,_=query_document('basic wind speed','A',lambda *a,**kw:([],''),forbidden,{'user':self.admin})
        self.assertEqual(response['status'],'NOT_FOUND')

    def test_table_row_retains_tower_header_and_value(self):
        text='Area\n| LEVEL | Floor GFA (sqm) |\n|---|---|\n| TOWER 7 | |\n| LEVEL 02 | 2,054 |'
        rows=table_row_units(text)
        row=next(x for x in rows if '2,054' in x)
        self.assertIn('TOWER 7',row)
        self.assertIn('Floor GFA (sqm): 2,054',row)
        self.assertIn('LEVEL: LEVEL 02',row)

    def test_explicit_retry_recovers_failed_images_without_repeating_completed_pages(self):
        import fitz, hashlib
        from PIL import Image
        from services.pipeline import process_document_pipeline
        image_path=runtime/'retry-scan.png'
        Image.new('RGB',(500,500),'white').save(image_path)
        pdf_path=runtime/'retry.pdf'
        pdf=fitz.open()
        for _ in range(2):
            page=pdf.new_page()
            page.insert_image(fitz.Rect(0,0,500,500),filename=str(image_path))
        pdf.save(pdf_path);pdf.close()
        with patch('services.vision_adapter.extract_visual_table',side_effect=[
            {'success':True,'engine':'synthetic','raw_text':'Legible synthetic note'},
            {'success':False,'engine':'synthetic','error':'interrupted'}]):
            self.assertEqual(process_document_pipeline(self.pid,str(pdf_path),'retry.pdf'),'WARNINGS')
        digest=hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        with patch('services.vision_adapter.extract_visual_table',return_value={
            'success':True,'engine':'synthetic','raw_text':'Recovered synthetic note'}) as worker:
            process_document_pipeline(self.pid,str(pdf_path),'retry.pdf',resume=True,expected_sha256=digest,retry_failed=True)
            self.assertEqual(worker.call_count,1)
            self.assertIn('p2_',worker.call_args.args[0])
        with db.SessionLocal() as session:
            images=session.query(db.ImageRecord).filter_by(project_id=self.pid,document_filename='retry.pdf').all()
            self.assertEqual(len(images),2)
            self.assertTrue(all(image.vision_status=='COMPLETED' for image in images))
            self.assertTrue(all(image.structured_extraction_status=='REVIEW_REQUIRED' for image in images))

    def test_failed_image_does_not_abort_remaining_pages_or_claim_ready(self):
        import fitz
        from PIL import Image
        from services.pipeline import process_document_pipeline
        image_path=runtime/'scan.png'
        Image.new('RGB',(500,500),'white').save(image_path)
        pdf_path=runtime/'failure.pdf'
        pdf=fitz.open()
        for _ in range(2):
            page=pdf.new_page()
            page.insert_image(fitz.Rect(0,0,500,500),filename=str(image_path))
        pdf.save(pdf_path); pdf.close()
        db.record_document('A','failure.pdf',str(pdf_path),1,folder_id=self.folder['id'],user=self.admin)
        with patch('services.vision_adapter.extract_visual_table',return_value={'success':False,'engine':'ALL_FAILED','error':'offline'}):
            status=process_document_pipeline(self.pid,str(pdf_path),'failure.pdf')
        self.assertEqual(status,'WARNINGS')
        with db.SessionLocal() as session:
            pages=session.query(db.PageRecord).filter_by(project_id=self.pid,document_filename='failure.pdf').all()
            images=session.query(db.ImageRecord).filter_by(project_id=self.pid,document_filename='failure.pdf').all()
            self.assertEqual(len(pages),2)
            self.assertTrue(all(p.processing_completed is not None for p in pages))
            self.assertTrue(all(i.vision_status=='FAILED' and i.processing_error=='offline' for i in images))
        import hashlib
        source_hash=hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        with patch('services.vision_adapter.extract_visual_table',side_effect=AssertionError('completed page repeated')):
            resumed=process_document_pipeline(self.pid,str(pdf_path),'failure.pdf',resume=True,expected_sha256=source_hash)
        self.assertEqual(resumed,'WARNINGS')
        with db.SessionLocal() as session:
            self.assertEqual(session.query(db.PageRecord).filter_by(project_id=self.pid,document_filename='failure.pdf').count(),2)


if __name__=='__main__':
    unittest.main()
