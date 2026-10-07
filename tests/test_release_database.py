import tempfile,unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import db
from knowledge.extraction import index_quantities,index_visual_structured_records
from services.ingestion import IngestionPipeline,DocumentState

class ReleaseDatabase(unittest.TestCase):
    def test_structured_query_rejects_unverified_vision_incomplete_sources_and_unit_conflicts(self):
        from intelligence.document_query import execute_structured_query,robust_parse_query
        plan=robust_parse_query('Tower 7 Level 02 GFA',self.pid)
        def record(kind,unit):return db.StructuredRecord(project_id=self.pid,doc='fixture.pdf',page=1,entity='TOWER 7 LEVEL 02',field='Floor GFA ('+unit+')',raw_value='12',value=12,unit=unit,source_type=kind,confidence='HIGH')
        with self.session() as s:s.add(record('PDF_IMAGE','sqm'));s.commit()
        docs=[{'filename':'fixture.pdf','status':'ready','chunks':1}]
        with patch('db.user_can_access',return_value=True),patch('db.list_documents',return_value=docs):
            result,_=execute_structured_query(plan,self.pid,'Tower 7 Level 02 GFA',{'id':1,'role':'admin'})
            self.assertEqual(result['status'],'NOT_FOUND')
        with self.session() as s:
            s.query(db.StructuredRecord).delete();s.add(record('PDF_NATIVE','sqm'));s.add(record('PDF_NATIVE','sqft'));s.commit()
        with patch('db.user_can_access',return_value=True),patch('db.list_documents',return_value=docs):
            result,_=execute_structured_query(plan,self.pid,'Tower 7 Level 02 GFA',{'id':1,'role':'admin'})
            self.assertEqual(result['status'],'AMBIGUOUS')
        docs[0]['status']='processing'
        with patch('db.user_can_access',return_value=True),patch('db.list_documents',return_value=docs):
            result,_=execute_structured_query(plan,self.pid,'Tower 7 Level 02 GFA',{'id':1,'role':'admin'})
            self.assertEqual(result['status'],'NOT_FOUND')

    def test_legacy_ready_flag_does_not_override_incomplete_evidence(self):
        import ast,json,os
        from pathlib import Path
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_reconcile_completed_documents')
        scope={'db':db,'json':json,'os':os}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'readiness-reconcile','exec'),scope)
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'incomplete.pdf')
            Path(path+'.index.json').write_text(json.dumps({'processing_complete':False}))
            with self.session() as s:
                s.add(db.Document(project_id=self.pid,filename='incomplete.pdf',path=path,status='ready',chunks=1));s.commit()
            scope['_reconcile_completed_documents']()
            with self.session() as s:self.assertEqual(s.query(db.Document).one().status,'review_required')

    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        db.Base.metadata.create_all(self.engine)
        self.session=sessionmaker(bind=self.engine,expire_on_commit=False)
        with self.session() as s:
            p=db.Project(name='Synthetic release');s.add(p);s.commit();self.pid=p.id
        self.override=patch('db.SessionLocal',self.session);self.override.start()
    def tearDown(self):self.override.stop();self.engine.dispose()
    def test_quantities_replace_updated_values_and_preserve_multiple_dimensions(self):
        def quantities(values):return [dict(project_id=self.pid,building='',metric='dimension',value=str(v),unit='mm',source_doc='fixture.pdf',source_page=1,revision='B') for v in values]
        with patch('knowledge.extraction.extract_quantities_from_pdf',return_value=quantities([100,200])):
            self.assertEqual(index_quantities(self.pid,'fixture.pdf',{}),2)
        with patch('knowledge.extraction.extract_quantities_from_pdf',return_value=quantities([300,400,400])):
            self.assertEqual(index_quantities(self.pid,'fixture.pdf',{}),2)
        with self.session() as s:self.assertEqual({r.value for r in s.query(db.Quantity)}, {'300','400'})
        with patch('knowledge.extraction.extract_quantities_from_pdf',return_value=[]):index_quantities(self.pid,'fixture.pdf',{})
        with self.session() as s:self.assertEqual(s.query(db.Quantity).count(),0)

    def test_quantity_commit_failure_restores_previous_source_version(self):
        q=dict(project_id=self.pid,building='',metric='dimension',value='100',unit='mm',source_doc='fixture.pdf',source_page=1,revision='A')
        with patch('knowledge.extraction.extract_quantities_from_pdf',return_value=[q]):index_quantities(self.pid,'fixture.pdf',{})
        from sqlalchemy.orm import Session
        with patch('knowledge.extraction.extract_quantities_from_pdf',return_value=[]),patch.object(Session,'commit',side_effect=RuntimeError('commit failure')):
            with self.assertRaises(RuntimeError):index_quantities(self.pid,'fixture.pdf',{})
        with self.session() as s:self.assertEqual(s.query(db.Quantity).one().value,'100')

    def test_visual_rows_never_gain_verified_confidence_and_stale_rows_are_cleared(self):
        row={'table_name':'Test','row_key':'Equipment','row_values':{'Load':'5'},'doc':'fixture.pdf','page':1,'source_type':'PDF_IMAGE'}
        with patch('knowledge.extraction.parse_generic_tables',return_value=[row]):
            index_visual_structured_records(self.pid,'fixture.pdf',{'type':'pdf','pages':[{'page':1,'vision':'| model table |'}]})
        with self.session() as s:self.assertEqual(s.query(db.StructuredRecord).one().confidence,'AMBIGUOUS')
        index_visual_structured_records(self.pid,'fixture.pdf',{'type':'pdf','pages':[]})
        with self.session() as s:self.assertEqual(s.query(db.StructuredRecord).count(),0)

    def test_quality_does_not_automatically_verify_or_publish(self):
        pipeline=IngestionPipeline()
        self.assertEqual(pipeline.get_next_state(DocumentState.PROCESSING,1.0),DocumentState.REVIEW_REQUIRED)
        self.assertEqual(pipeline.get_next_state(DocumentState.REVIEW_REQUIRED,1.0),DocumentState.REVIEW_REQUIRED)
        self.assertEqual(pipeline.get_next_state(DocumentState.PROCESSING,1.0,source_verified=True),DocumentState.VERIFIED)
        self.assertFalse(pipeline.quality_check({'text':'native '*100})['can_auto_publish'])
