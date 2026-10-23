"""Regression coverage for the current audit's concrete failure modes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db
from engines.ifc_engine import IFCModel, IFCElement
from knowledge.hub import KnowledgeHub
from services.bim_service import BIMService
from intelligence.answer_publication import source_context_for_sources
from intelligence.reports import ReportEngine


class CitationIdentityTests(unittest.TestCase):
    def test_source_previews_never_choose_the_last_duplicate_file(self):
        import main
        with patch.object(db, 'list_documents', return_value=[
                {'id': 1, 'filename': 'Drawing.pdf', 'path': 'A/Drawing.pdf'},
                {'id': 2, 'filename': 'Drawing.pdf', 'path': 'B/Drawing.pdf'}]):
            source = main.resolve_sources('Fixture', [{'source': 'Drawing.pdf', 'page': 1}])[0]
        self.assertFalse(source['exists'])
        self.assertFalse(source['previewable'])

    def test_duplicate_name_detection_matches_windows_case_rules(self):
        from intelligence.answer_publication import ambiguous_document_names
        self.assertEqual(ambiguous_document_names([
            {'filename': 'Drawing.pdf'}, {'filename': 'drawing.PDF'}, {'filename': 'Unique.pdf'}]), {'drawing.pdf'})

    def test_ambiguous_basename_is_never_last_document_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = []
            for number, value in enumerate((900, 1100), 1):
                path = Path(directory) / str(number) / 'Drawing.pdf'
                path.parent.mkdir()
                path.write_bytes(b'fixture')
                Path(str(path) + '.index.json').write_text(json.dumps({
                    'processing_complete': True, 'source_sha256': hashlib.sha256(b'fixture').hexdigest(),
                    'pages': [{'page': 1, 'text': f'Width {value} mm'}]}))
                documents.append({'id': number, 'filename': path.name, 'path': str(path), 'status': 'ready'})
            allowed, context = source_context_for_sources(documents, [{'source': 'Drawing.pdf', 'page': 1}])
            self.assertEqual(allowed, [])
            self.assertEqual(context, '')
            allowed, context = source_context_for_sources(documents, [{'source': 'Drawing.pdf', 'page': 1, 'document_id': 1}])
            self.assertEqual(len(allowed), 1)
            self.assertIn('900 mm', context)
            self.assertNotIn('1100 mm', context)
            self.assertEqual(source_context_for_sources(documents, [{'source': 'Drawing.pdf', 'page': 1, 'document_id': 99}]), ([], ''))
            self.assertEqual(source_context_for_sources(documents, [
                {'source': 'Drawing.pdf', 'page': 1, 'document_id': 1},
                {'source': 'Drawing.pdf', 'page': 1, 'document_id': 2}]), ([], ''))


class ReportIsolationTests(unittest.TestCase):
    def test_every_report_filters_findings_and_has_unique_identity(self):
        engine = ReportEngine()
        findings = [{'project_id': 'A', 'title': 'ours', 'status': 'PASS'},
                    {'project_id': 'B', 'title': 'foreign', 'status': 'FAIL'},
                    {'title': 'unowned', 'status': 'FAIL'}]
        reports = [engine.generate_compliance_report('A', findings),
                   engine.generate_bim_qa_report('A', {}, findings),
                   engine.generate_drawing_review_report('A', [], findings),
                   engine.generate_issue_register('A', findings)]
        self.assertEqual(len({r.report_id for r in reports}), 4)
        for report in reports:
            self.assertEqual([f['title'] for f in report.findings], ['ours'])
            self.assertNotIn('foreign', str(report.sections))
        self.assertEqual(reports[0].sections[0].data['total'], 1)


class MasterplanContainerTests(unittest.TestCase):
    def test_worker_admission_is_bounded(self):
        from services.masterplan import code_interpreter as interpreter
        self.assertTrue(interpreter._EXECUTION_SLOTS.acquire(blocking=False))
        self.assertTrue(interpreter._EXECUTION_SLOTS.acquire(blocking=False))
        try:
            with patch('services.container_sandbox.run_code_in_container') as run:
                result, error = interpreter.execute_sandboxed_code('result={}', pd.DataFrame())
            self.assertIsNone(result)
            self.assertIn('busy', error)
            run.assert_not_called()
        finally:
            interpreter._EXECUTION_SLOTS.release()
            interpreter._EXECUTION_SLOTS.release()

    def test_missing_container_cannot_fall_back_to_host_python(self):
        from services.masterplan.code_interpreter import execute_sandboxed_code
        with patch('services.container_sandbox.find_container_engine', return_value={
                'daemon_running': False, 'message': 'offline'}), patch('subprocess.Popen') as host:
            result, error = execute_sandboxed_code('result={"n": 1}', pd.DataFrame([{'plot_id': 'P1'}]))
        self.assertIsNone(result)
        self.assertIn('offline', error)
        host.assert_not_called()

    def test_only_dataset_and_trusted_runner_are_staged_and_removed(self):
        from services.masterplan.code_interpreter import execute_sandboxed_code
        paths = []
        def isolated(code, root, timeout):
            paths.append(Path(root))
            self.assertEqual(timeout, 15)
            self.assertEqual({p.name for p in Path(root).iterdir()}, {'job.json', 'interpreter_runner.py'})
            self.assertIn('/input/job.json', code)
            payload = json.loads((Path(root) / 'job.json').read_text())
            self.assertEqual(payload['plots'][0]['plot_id'], 'P1')
            return {'exit_code': 0, 'stdout': '{"result":{"n":1}}'}
        with patch('services.container_sandbox.run_code_in_container', side_effect=isolated):
            self.assertEqual(execute_sandboxed_code('result={"n":1}', pd.DataFrame([{'plot_id': 'P1'}])), ({'n': 1}, None))
        self.assertFalse(paths[0].exists())


class BIMRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        db.Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        self.patcher = patch.object(db, 'SessionLocal', self.session)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.engine.dispose)
        with self.session() as session:
            session.add_all([db.Project(name='A'), db.Project(name='B')])
            session.commit()
        self.service = BIMService()
        self.service._hub = KnowledgeHub()

    def model(self, names=('door',)):
        return IFCModel(filename='Model.ifc', ifc_schema='IFC4', element_count=len(names),
                        elements=[IFCElement(guid='guid-' + name, ifc_class='IfcDoor', name=name,
                                             level='L1', dimensions={'width': 0.9}) for name in names])

    def test_registration_persists_replaces_and_hydrates_without_cross_project_collision(self):
        key_a = self.service.register_model(self.model(), 'A')
        key_b = self.service.register_model(self.model(), 'B')
        self.assertNotEqual(key_a, key_b)
        self.assertEqual(len(self.service.list_models('A')), 1)
        self.service.register_model(self.model(('other',)), 'A')
        self.assertEqual([e['name'] for e in self.service.query_elements('A', ifc_class='IfcDoor')], ['other'])
        self.assertEqual([e['name'] for e in self.service.query_elements('B')], ['door'])
        restarted = BIMService()
        restarted._hub = KnowledgeHub()
        self.assertEqual(restarted.get_stats('A')['total_elements'], 1)
        self.assertEqual(restarted.query_elements('A')[0]['dimensions']['width'], 0.9)
        with self.session() as session:
            self.assertEqual(session.query(db.BimModel).count(), 2)
            self.assertEqual(session.query(db.BimElement).count(), 2)

    def test_failed_registration_rolls_back_persistent_and_cached_model(self):
        with patch.object(self.service._hub, 'add_entity', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.service.register_model(self.model(), 'A')
        self.assertEqual(self.service._models, {})
        self.assertEqual(self.service._hub._entities, {})
        with self.session() as session:
            self.assertEqual(session.query(db.BimModel).count(), 0)
            self.assertEqual(session.query(db.BimElement).count(), 0)

    def test_blender_and_report_operations_share_purge_lock_and_retirement_guard(self):
        from services.project_cleanup import active_project_operation, _lock, _receipt, ProjectCleanupError
        with tempfile.TemporaryDirectory() as directory:
            with active_project_operation(directory, 'A'):
                with self.assertRaises(ProjectCleanupError):
                    with _lock(_receipt(directory, 'A')):
                        self.fail('Overlapping cleanup was admitted')
            with self.session() as session:
                session.query(db.Project).filter_by(name='A').one().deleted_at = db._utcnow()
                session.commit()
            with self.assertRaisesRegex(ValueError, 'active project'):
                with active_project_operation(directory, 'A'):
                    self.fail('Retired project created an artifact')

    def test_permanent_cleanup_removes_blender_and_reports_only_for_own_project(self):
        from services.project_cleanup import purge_project
        from services.jobs import JobQueue
        with tempfile.TemporaryDirectory() as directory, patch.object(db, 'DATA_DIR', directory):
            root = Path(directory).resolve()
            with patch.dict(os.environ, {'EXPO_BLENDER_DATA': str(root/'blender_jobs')}):
                owned = root/'blender_jobs'/('a'*32)
                foreign = root/'blender_jobs'/('b'*32)
                for folder, project in ((owned, 'A'), (foreign, 'B')):
                    folder.mkdir(parents=True)
                    (folder/'job.json').write_text(json.dumps({'project': project}))
                    (folder/'source.pdf').write_bytes(b'original')
                    report = root/'reports'/project
                    report.mkdir(parents=True)
                    (report/'result.pdf').write_bytes(b'report')
                with self.session() as session:
                    session.query(db.Project).filter_by(name='A').one().deleted_at = db._utcnow()
                    session.commit()
                queue = JobQueue(str(root))
                with patch('services.masterplan.db.delete_project_records', return_value=True):
                    result = purge_project('A', root, queue)
                self.assertTrue(result['cleanup_verified'])
                self.assertFalse(owned.exists())
                self.assertFalse((root/'reports/A').exists())
                self.assertTrue((foreign/'source.pdf').exists())
                self.assertTrue((root/'reports/B/result.pdf').exists())


class PDFAssetSecurityTests(unittest.TestCase):
    def test_pinned_offline_pdf_assets_match_manifest_and_both_callers_share_safe_loader(self):
        root = Path(__file__).resolve().parents[1]
        vendor = root/'ui/vendor_pdfjs'
        manifest = json.loads((vendor/'asset-manifest.json').read_text())
        self.assertEqual(manifest['version'], '6.2.108')
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((vendor/name).read_bytes()).hexdigest(), digest, name)
        wrapper = (root/'ui/pdf_preview.js').read_text()
        self.assertIn('isEvalSupported: false', wrapper)
        self.assertIn('enableScripting: false', wrapper)
        for name in ('ui/app.html', 'ui/review.html', 'ui/cowork_studio.js', 'ui/review.js'):
            source = (root/name).read_text(encoding='utf-8')
            self.assertNotIn('2.16.105', source)


class BlenderOwnershipTests(unittest.TestCase):
    def test_inventory_discovers_only_owned_jobs_and_refuses_active_job(self):
        from services.project_cleanup import inventory, ProjectCleanupError
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=False):
            root = Path(directory).resolve()
            with patch.dict('os.environ', {'EXPO_BLENDER_DATA': str(root/'blender_jobs')}):
                owned = root/'blender_jobs'/('a'*32)
                foreign = root/'blender_jobs'/('b'*32)
                for path, project in ((owned, 'A'), (foreign, 'B')):
                    path.mkdir(parents=True)
                    (path/'job.json').write_text(json.dumps({'project': project}))
                    (path/'source.pdf').write_bytes(b'original')
                paths = inventory(root, 'A', ['B'], [])
                self.assertIn(owned, paths)
                self.assertNotIn(foreign, paths)
                (owned/'operation.lock').write_text('busy')
                with self.assertRaisesRegex(ProjectCleanupError, 'Blender operation is active'):
                    inventory(root, 'A', ['B'], [])

    def test_storage_honors_data_directory(self):
        from expo_blender import service
        with tempfile.TemporaryDirectory() as directory, patch.object(db, 'DATA_DIR', directory), patch.dict('os.environ', {}, clear=False):
            import os
            old = os.environ.pop('EXPO_BLENDER_DATA', None)
            try:
                self.assertEqual(service.root(), (Path(directory)/'blender_jobs').resolve())
            finally:
                if old is not None: os.environ['EXPO_BLENDER_DATA'] = old


class ModelEvidenceTests(unittest.TestCase):
    def test_exact_counts_and_no_invented_area_or_unexecuted_filter(self):
        from intelligence.model_answers import exact_model_answer, validate_model_prose, MISSING
        context = json.dumps({'models': [{'name': 'A', 'counts': {'IFCDOOR': 2}},
                                        {'name': 'B', 'counts': {'IFCDOOR': 3}}],
                              'counts': {'IFCDOOR': 5}, 'counts_complete': True})
        self.assertIn('**5**', exact_model_answer('How many doors are there?', context))
        for question in ('How many doors on level 2?', 'How many blue doors?', 'What is the total area?'):
            self.assertEqual(exact_model_answer(question, context), MISSING)
        self.assertEqual(exact_model_answer('How many doors?', '{"categories":["IFCDOOR"]}'), MISSING)
        self.assertEqual(validate_model_prose('The area is 999 m2.', context, ''), MISSING)
        selected = '[{"OverallWidth":{"value":0.9,"unit":"m"}}]'
        self.assertIn('**0.9** m', exact_model_answer('What is the width?', context, selected))
        self.assertEqual(exact_model_answer('What is the width?', context, '[{"Width":0.9},{"Width":1.1}]'), MISSING)


class EvaluationIntegrityTests(unittest.TestCase):
    def test_success_status_and_wrong_answer_cannot_pass(self):
        from intelligence.answer_evaluation import evaluate_cases
        cases = [{'question': 'Width?', 'source_hash': 'fixture-sha256', 'expected_answer': '900 mm',
                  'expected_sources': [{'document_id': 'd1', 'page': 1}]}]
        def wrong(question):
            return {'status': 'SUCCESS', 'answer': '1100 mm', 'model_digest': 'real-digest',
                    'sources': [{'document_id': 'd1', 'page': 1}]}
        result = evaluate_cases(cases, wrong)
        self.assertEqual(result['answer_exact_match'], 0)
        self.assertFalse(result['results'][0]['passed'])
        correct = lambda question: {**wrong(question), 'answer': '900 mm'}
        self.assertTrue(evaluate_cases(cases, correct)['results'][0]['passed'])
        with self.assertRaises(ValueError):
            evaluate_cases(cases, lambda question: {**correct(question), 'mocked': True})

    def test_legacy_mock_runner_cannot_start(self):
        from intelligence.forensic_engine import start_forensic_test, run_forensic_test_bg
        self.assertEqual(start_forensic_test('A', 'doc')['status'], 'disabled')
        with self.assertRaisesRegex(RuntimeError, 'mock evaluation is disabled'):
            run_forensic_test_bg('A', 'doc')


class AuthenticatedBoundaryTests(unittest.TestCase):
    def test_bim_ingest_and_report_use_real_authenticated_routes(self):
        import secrets
        from types import SimpleNamespace
        from dataclasses import asdict
        import pymupdf
        import auth
        import main
        import routers.api_v1_routes as routes
        from fastapi.testclient import TestClient
        db.init_db()
        suffix = secrets.token_hex(5)
        username, password = 'auditfix_' + suffix, 'Fixture-' + secrets.token_hex(8)
        user = db.create_user(username, auth.hash_password(password), role='admin')
        projects = ('AuditFixA_' + suffix, 'AuditFixB_' + suffix)
        for project in projects:
            db.create_project(project, by=user)
        client = TestClient(main.app)
        self.assertEqual(client.post('/auth/login', json={'username': username, 'password': password}).status_code, 200)
        for project, width in zip(projects, (0.9, 1.1)):
            model = IFCModel(filename='Same.ifc', ifc_schema='IFC4', elements=[IFCElement(
                guid='same-guid', ifc_class='IfcDoor', name='Door', level='L1', dimensions={'width': width})])
            result = client.post('/api/v1/bim/ingest', params={'project': project}, json={'model_data': asdict(model)})
            self.assertEqual(result.status_code, 200, result.text)
        for project, width in zip(projects, (0.9, 1.1)):
            response = client.get('/api/v1/bim/elements', params={'project': project, 'ifc_class': 'IfcDoor'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['count'], 1)
            self.assertEqual(response.json()['elements'][0]['dimensions']['width'], width)
        findings = {
            'ours': SimpleNamespace(project_id=projects[0], finding_id='ours', title='OUR_FINDING_ABC', status='PASS'),
            'foreign': SimpleNamespace(project_id=projects[1], finding_id='foreign', title='FOREIGN_FINDING_XYZ', status='FAIL')}
        with patch.object(routes.validation_engine, '_findings', findings):
            report = client.post('/api/v1/reports/generate', params={'project': projects[0]}, json={'report_type': 'compliance', 'format': 'pdf'})
        self.assertEqual(report.status_code, 200, report.text)
        with pymupdf.open(report.json()['file_path']) as pdf:
            text = '\n'.join(page.get_text() for page in pdf)
        self.assertIn('OUR_FINDING_ABC', text)
        self.assertNotIn('FOREIGN_FINDING_XYZ', text)
        self.assertEqual(client.get('/api/v1/reports/list', params={'project': '../outside'}).status_code, 400)
        client.close()

    def test_worker_status_is_authenticated_and_reports_unavailability(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.sandbox_status import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(client.get('/agent/sandbox-status').status_code, 401)
        with patch('routers.sandbox_status.auth.require_user', return_value={'role': 'admin'}), patch(
                'services.container_sandbox.find_container_engine', return_value={'daemon_running': False, 'message': 'offline'}):
            response = client.get('/agent/sandbox-status')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['ready'])
        self.assertIn('offline', response.json()['message'])
        client.close()


if __name__ == '__main__':
    unittest.main()
