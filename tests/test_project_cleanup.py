"""Permanent cleanup preserves other projects and fails closed/retries safely."""
import ast
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, Integer
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
import db
from services.jobs import JobQueue
from services.project_cleanup import purge_project, ProjectCleanupError, ProjectCleanupIOError, project_is_retired


class ProjectCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.engine = create_engine('sqlite:///'+str(self.root/'test.db'))
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
        db.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patches = [patch('db.SessionLocal', self.sessions), patch('db.DATA_DIR', str(self.root))]
        for p in self.patches:p.start()
        self.addCleanup(self.finish)
        self.queue = JobQueue(str(self.root))
        with self.sessions() as s:
            s.add(db.User(id=1, username='fixture-admin', role='admin'));s.commit()
            target=db.Project(name='Delete Test',deleted_at=datetime.datetime.utcnow())
            other=db.Project(name='Keep Test');s.add_all([target,other]);s.commit()
            self.pid,self.other=target.id,other.id
            folder=db.Folder(project_id=self.pid,name='restricted');s.add(folder);s.commit()
            s.add(db.FolderMember(folder_id=folder.id,user_id=1))
            doc=db.Document(project_id=self.pid,filename='same.pdf',path=str(self.root/'docs/Delete Test/same.pdf'),folder_id=folder.id)
            keep=db.Document(project_id=self.other,filename='same.pdf',path=str(self.root/'docs/Keep Test/same.pdf'))
            s.add_all([doc,keep]);s.commit();self.did=doc.id
            s.add_all([db.DocMeta(document_id=doc.id),
                db.Annotation(id='target',document_id=str(doc.id)),db.Annotation(id='keep',document_id=str(keep.id)),
                db.JobProgress(key='Delete Test||same.pdf',stage='queued'),
                db.JobProgress(key='Keep Test||same.pdf',stage='queued'),
                db.Chat(project_id=self.pid,chat_id='target'),db.Chat(project_id=self.other,chat_id='keep'),
                db.DocumentMemory(project_id=self.pid,document_id=doc.id,doc='same.pdf',source_sha256='0'*64,property='pressure',claim='test',evidence_quote='test'),
                db.UserUpload(project_id=self.pid,user_id=1,filename='same.pdf',path=str(self.root/'private_uploads/1/Delete_Test/same.pdf'))])
            s.commit()
        # Every current direct project-owned table is exercised, not just a
        # hand-selected list. Nullable fields need not invent ownership.
        seeded={'documents','folders','chats','document_memory','user_uploads'}
        with self.engine.begin() as conn:
            for table in db.Base.metadata.sorted_tables:
                if 'project_id' not in table.c or table.name in seeded:continue
                values={'project_id':self.pid}
                for col in table.c:
                    if col.name in values or col.primary_key or col.nullable or col.default is not None:continue
                    if col.name=='document_id':values[col.name]=self.did
                    elif col.name.endswith('user_id'):values[col.name]=1
                    else:values[col.name]=1 if isinstance(col.type,Integer) else table.name+'-fixture'
                conn.execute(table.insert().values(**values))
        self.paths=[]
        for folder in ['docs/Delete Test','faiss_index/Delete Test','faiss_index/Delete Test.previous-a',
                       'faiss_index/Delete Test.staging-a','workspace/Delete Test','projects/Delete Test',
                       'recycle_bin/Delete Test','recycle_bin/_projects/20261001-120000-Delete Test',
                       'private_uploads/1/Delete_Test']:
            path=self.root/folder/'same.pdf';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'target')
            self.paths.append(path)
        self.keep=self.root/'docs/Keep Test/same.pdf';self.keep.parent.mkdir(parents=True);self.keep.write_bytes(b'keep unchanged')
        self.job=self.queue.enqueue('document',str(self.paths[0]),{'project':'Delete Test'})
        self.keep_job=self.queue.enqueue('document',str(self.keep),{'project':'Keep Test'})
        self.calls=[]

    def finish(self):
        for p in reversed(self.patches):p.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def purge(self):
        return purge_project('Delete Test',str(self.root),self.queue,lambda n,i:self.calls.append((n,i)))

    def test_complete_cleanup_all_project_tables_artifacts_jobs_and_other_project_preserved(self):
        result=self.purge()
        self.assertTrue(result['cleanup_verified'])
        self.assertTrue(all(not p.exists() for p in self.paths))
        with self.sessions() as s:
            self.assertIsNone(s.get(db.Project,self.pid))
            self.assertIsNotNone(s.get(db.Project,self.other))
            self.assertEqual([a.id for a in s.query(db.Annotation)],['keep'])
            self.assertEqual([p.key for p in s.query(db.JobProgress)],['Keep Test||same.pdf'])
            self.assertEqual(s.query(db.DocMeta).count(),0)
            for table in db.Base.metadata.tables.values():
                if 'project_id' in table.c:
                    self.assertIsNone(s.execute(table.select().where(table.c.project_id==self.pid)).first(),table.name)
        with self.queue.connect() as c:
            self.assertEqual([j['id'] for j in c.execute('SELECT id FROM jobs')],[self.keep_job])
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')
        self.assertEqual(self.calls,[('Delete Test',self.pid)])

    def test_every_other_project_table_is_preserved_with_identical_source_names(self):
        with self.sessions() as s:
            other_doc=s.query(db.Document).filter_by(project_id=self.other).one().id
        folder_map={}
        with self.engine.begin() as conn:
            for table in db.Base.metadata.sorted_tables:
                if 'project_id' not in table.c or table.name in {'documents','chats'}:continue
                for row in conn.execute(table.select().where(table.c.project_id==self.pid)).mappings().all():
                    values={c.name:row[c.name] for c in table.c if not c.primary_key}
                    values['project_id']=self.other
                    if 'document_id' in values:values['document_id']=other_doc
                    if table.name=='user_uploads':values['path']=str(self.root/'private_uploads/1/Keep_Test/same.pdf')
                    inserted=conn.execute(table.insert().values(**values))
                    if table.name=='folders':folder_map[row['id']]=inserted.inserted_primary_key[0]
            for folder_id in folder_map.values():
                conn.execute(db.FolderMember.__table__.insert().values(folder_id=folder_id,user_id=1))
            conn.execute(db.DocMeta.__table__.insert().values(document_id=other_doc))
            before={table.name:[dict(row) for row in conn.execute(table.select().where(table.c.project_id==self.other)).mappings()]
                    for table in db.Base.metadata.tables.values() if 'project_id' in table.c}
        keep_private=self.root/'private_uploads/1/Keep_Test/same.pdf'
        keep_private.parent.mkdir(parents=True);keep_private.write_bytes(b'private other project')
        self.purge()
        with self.engine.connect() as conn:
            after={table.name:[dict(row) for row in conn.execute(table.select().where(table.c.project_id==self.other)).mappings()]
                   for table in db.Base.metadata.tables.values() if 'project_id' in table.c}
            self.assertEqual(conn.execute(db.FolderMember.__table__.select()).fetchall()[0].folder_id,next(iter(folder_map.values())))
            self.assertEqual(conn.execute(db.DocMeta.__table__.select()).fetchall()[0].document_id,other_doc)
        self.assertEqual(before,after)
        self.assertEqual(keep_private.read_bytes(),b'private other project')

    def test_active_project_and_missing_project_cannot_be_purged(self):
        for name in ['Keep Test','missing']:
            with self.assertRaises(ProjectCleanupError) as error:purge_project(name,str(self.root),self.queue)
            if name=='missing':self.assertEqual(error.exception.status_code,404)
        self.assertTrue(self.keep.exists())

    def test_running_job_blocks_cleanup_then_retry_succeeds(self):
        with self.queue.connect() as c:c.execute("UPDATE jobs SET state='running' WHERE id=?",(self.job,))
        with self.assertRaisesRegex(ProjectCleanupError,'running'):self.purge()
        self.assertTrue(self.paths[0].exists())
        with self.queue.connect() as c:c.execute("UPDATE jobs SET state='completed' WHERE id=?",(self.job,))
        self.assertTrue(self.purge()['cleanup_verified'])

    def test_file_failure_is_reported_and_retry_cleans_everything(self):
        with patch('services.project_cleanup.shutil.rmtree',side_effect=PermissionError('locked fixture')):
            with self.assertRaises(ProjectCleanupIOError):self.purge()
        with self.sessions() as s:self.assertIsNotNone(s.get(db.Project,self.pid))
        self.assertTrue(project_is_retired(self.root,'Delete Test'))
        self.assertTrue(self.purge()['cleanup_verified'])

    def test_retry_after_database_commit_but_receipt_failure(self):
        from services.project_cleanup import _write
        def fail_complete(path,record):
            if record['state']=='COMPLETE':raise OSError('receipt completion write failed')
            return _write(path,record)
        with patch('services.project_cleanup._write',fail_complete):
            with self.assertRaises(ProjectCleanupIOError):self.purge()
        with self.sessions() as s:self.assertIsNone(s.get(db.Project,self.pid))
        self.assertTrue(self.purge()['cleanup_verified'])

    def test_repeated_purge_is_verified_and_other_project_stays_intact(self):
        self.purge();self.assertTrue(self.purge()['cleanup_verified'])
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')

    def test_sanitized_name_collision_cannot_delete_shared_storage(self):
        with self.sessions() as s:s.add(db.Project(name='Delete_Test'));s.commit()
        with self.assertRaisesRegex(ProjectCleanupError,'collide'):self.purge()
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_outside_document_path_is_not_followed(self):
        with self.sessions() as s:s.get(db.Document,self.did).path=str(self.keep);s.commit()
        with self.assertRaisesRegex(ProjectCleanupError,'outside'):self.purge()
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')

    def test_unmapped_annotation_cannot_be_guessed_by_basename(self):
        with self.sessions() as s:s.add(db.Annotation(id='legacy',document_id='same.pdf'));s.commit()
        with self.assertRaisesRegex(ProjectCleanupError,'Unmapped'):self.purge()
        self.assertTrue(self.paths[0].exists())

    def test_retired_jobs_cannot_restart_or_recreate_files_after_failure(self):
        with patch('services.project_cleanup.shutil.rmtree',side_effect=PermissionError('locked fixture')):
            with self.assertRaises(ProjectCleanupError):self.purge()
        self.queue.handlers={'document':lambda _:self.fail('retired handler invoked')}
        self.assertTrue(self.queue.run_one())
        with self.assertRaisesRegex(ValueError,'retired'):
            self.queue.enqueue('document',str(self.paths[0]),{'project':'Delete Test'})

    def test_automatic_recreation_is_blocked_but_explicit_recreation_works(self):
        self.purge()
        with self.sessions() as s:
            with self.assertRaises(ValueError):db._get_or_create_project(s,'Delete Test')
        db.create_project('Delete Test',{'id':1,'username':'fixture-admin'})
        self.assertFalse(project_is_retired(self.root,'Delete Test'))

    def test_recoverable_delete_restore_is_preserved_before_permanent_cleanup(self):
        with self.sessions() as s:p=s.get(db.Project,self.pid);p.deleted_at=None;s.commit()
        self.assertIsNotNone(db.soft_delete_project('Delete Test'))
        self.assertIsNotNone(db.restore_project('Delete Test'))
        self.assertTrue(self.paths[0].exists())

    def test_real_process_interruption_is_retryable(self):
        code='''import os,db
from services.jobs import JobQueue
import services.project_cleanup as cleanup
original=cleanup.shutil.rmtree
def crash(path):
 original(path)
 os._exit(17)
cleanup.shutil.rmtree=crash
cleanup.purge_project('Delete Test',os.environ['EXPO_DATA_DIR'],JobQueue(os.environ['EXPO_DATA_DIR']))
'''
        env=dict(os.environ,EXPO_DATA_DIR=str(self.root),EXPO_DATABASE_URL='sqlite:///'+str(self.root/'test.db'))
        result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,17,result.stderr.decode(errors='replace'))
        self.assertTrue(self.purge()['cleanup_verified'])

    def test_admin_route_rejects_non_admin_before_any_mutation(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        route=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='recycle_bin_purge_project_now')
        route.decorator_list=[]
        for arg in route.args.args:arg.annotation=None
        def deny(*args):raise HTTPException(403,'admin only')
        namespace={'auth':types.SimpleNamespace(require_roles=deny),'db':db,'HTTPException':HTTPException,
                   '_permanently_purge_project':lambda _:self.fail('unauthorized mutation'),'_client_ip':lambda _:None}
        exec(compile(ast.Module(body=[route],type_ignores=[]),'actual-purge-route','exec'),namespace)
        pending=namespace['recycle_bin_purge_project_now']('Delete Test',None)
        with self.assertRaises(HTTPException) as error:pending.send(None)
        self.assertEqual(error.exception.status_code,403)
        self.assertTrue(self.paths[0].exists())

    def test_admin_route_returns_verified_cleanup_result(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        route=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='recycle_bin_purge_project_now')
        route.decorator_list=[]
        for arg in route.args.args:arg.annotation=None
        namespace={'auth':types.SimpleNamespace(require_roles=lambda *args:{'id':1,'username':'fixture-admin'}),
                   'db':db,'HTTPException':HTTPException,'_permanently_purge_project':lambda _:self.purge(),
                   '_client_ip':lambda _:None}
        exec(compile(ast.Module(body=[route],type_ignores=[]),'actual-purge-route','exec'),namespace)
        pending=namespace['recycle_bin_purge_project_now']('Delete Test',None)
        with self.assertRaises(StopIteration) as completed:pending.send(None)
        self.assertTrue(completed.exception.value['cleanup_verified'])

    def test_enqueue_rechecks_retirement_after_acquiring_queue_write_lock(self):
        with patch('services.project_cleanup.assert_job_source_active',side_effect=[None,ValueError('retired')]) as check:
            with self.assertRaisesRegex(ValueError,'retired'):
                self.queue.enqueue('document',str(self.paths[0]),{'project':'Delete Test'})
        self.assertEqual(check.call_count,2)

    def test_native_link_or_junction_is_rejected_without_deleting_its_target(self):
        link=self.root/'docs/Delete Test/link'
        try:
            link.symlink_to(self.keep.parent,target_is_directory=True)
        except OSError:
            if os.name!='nt':raise
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(self.keep.parent)],
                                  capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        with self.assertRaises(ProjectCleanupError):self.purge()
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')
        # Remove only the link itself; never recurse through the linked target.
        if link.is_symlink():link.unlink()
        else:link.rmdir()

    def test_knowledge_cache_removes_only_target_entities_and_incident_edges(self):
        from knowledge.hub import KnowledgeHub
        from knowledge.graph import GraphNode,GraphEdge
        hub=KnowledgeHub()
        hub._entities={'target':types.SimpleNamespace(project_id='Delete Test'),
                       'keep':types.SimpleNamespace(project_id='Keep Test')}
        hub._graph.add_node(GraphNode('target','test',project_id='Delete Test'))
        hub._graph.add_node(GraphNode('keep','test',project_id='Keep Test'))
        hub._graph.add_edge(GraphEdge('target','test','linked','keep','test'))
        hub.remove_project('Delete Test')
        self.assertEqual(set(hub._entities),{'keep'})
        self.assertEqual(set(hub._graph._nodes),{'keep'})
        self.assertEqual(hub._graph._edges,[])

    def test_quarantine_ownership_removes_only_target_bytes_and_sidecars(self):
        from services.upload_recovery import staging_lease,quarantine_interrupted_uploads
        for folder,token in [('Delete Test','a'),('Keep Test','b')]:
            staging=self.root/'docs'/folder/('partial.pdf.upload-'+token*32)
            with staging_lease(staging):staging.write_bytes(b'partial source')
        records=quarantine_interrupted_uploads([self.root/'docs'],self.root/'recovery/quarantine')
        self.assertEqual(len(records),2)
        self.purge()
        for record in records:
            artifact=Path(record['quarantined'])
            kept='Keep Test' in record['source']
            self.assertEqual(artifact.exists(),kept)
            self.assertEqual(Path(str(artifact)+'.owner.json').exists(),kept)

    def test_unknown_quarantine_ownership_blocks_a_false_cleanup_guarantee(self):
        orphan=self.root/'recovery/quarantine/unknown-source.pdf';orphan.parent.mkdir(parents=True);orphan.write_bytes(b'unknown')
        with self.assertRaisesRegex(ProjectCleanupError,'ownership review'):self.purge()
        self.assertTrue(orphan.exists())
        self.assertTrue(self.paths[0].exists())

    def test_unsafe_windows_components_and_aliases_are_refused(self):
        from services.project_cleanup import inventory
        for name in ['..','CON','Keep Test.','Keep Test ','../Keep Test']:
            with self.subTest(name=name),self.assertRaises(ProjectCleanupError):
                inventory(self.root,name,[],[])
        with self.assertRaises(ProjectCleanupError):
            inventory(self.root,'Delete Test',['Delete Test.'],[])
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')

    def test_expiry_sweeper_uses_verified_purge_and_preserves_document_identities_until_then(self):
        old=datetime.datetime.utcnow()-datetime.timedelta(days=20)
        with self.sessions() as s:
            s.get(db.Project,self.pid).deleted_at=old
            s.get(db.Document,self.did).deleted_at=old
            s.commit()
        self.assertEqual(db.purge_expired_deleted_documents(),[])
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_start_recycle_bin_sweeper')
        flag=types.SimpleNamespace(done=False)
        flag.is_set=lambda:flag.done
        flag.wait=lambda _:setattr(flag,'done',True)
        logger=types.SimpleNamespace(exception=lambda *a,**k:None,info=lambda *a,**k:None)
        namespace={'db':db,'_recycle_bin_sweeper_stop':flag,'logger':logger,
                   'threading':types.SimpleNamespace(Thread=lambda target,**kwargs:types.SimpleNamespace(start=target)),
                   '_permanently_purge_project':lambda name:self.purge()}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'actual-expiry-sweeper','exec'),namespace)
        namespace['_start_recycle_bin_sweeper']()
        with self.sessions() as s:self.assertIsNone(s.get(db.Project,self.pid))
        self.assertEqual(self.keep.read_bytes(),b'keep unchanged')


if __name__=='__main__':unittest.main()
