import ast
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services import container_sandbox as runner
from services.cowork_workspace import run_workspace_python, stage_text_write
from services.masterplan.models import MasterplanPlot
from services.masterplan.plot_answers import plot_answer


class WorkerFixes(unittest.TestCase):
    def test_permissions_are_not_reported_as_stopped_daemon(self):
        with patch.object(runner.shutil, 'which', return_value='docker'), patch.object(
                runner.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='permission denied', stdout='')):
            result = runner.find_container_engine()
        self.assertEqual(result['error_kind'], 'permission_denied')
        self.assertIn('does not mean Docker is stopped', result['message'])

    def test_no_unapproved_image_fallback(self):
        with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                runner.get_container_image('docker')

    def test_flags_never_enable_host_execution(self):
        with patch.dict(os.environ, {'EXPO_SANDBOX_CONTAINER': '1', 'EXPO_ALLOW_INSECURE_LOCAL_PYTHON': '1'}), patch.object(
                runner, 'find_container_engine', return_value={'daemon_running': False, 'message': 'API unavailable'}), patch.object(
                runner.subprocess, 'Popen') as host:
            result = run_workspace_python('.', 'print(1)')
        self.assertEqual(result['exit_code'], 1)
        host.assert_not_called()

    def test_working_copy_changes_and_deletions_preserve_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'keep.txt').write_text('source')
            (root / 'delete.txt').write_text('retain original')
            def execute(command, engine, name, timeout):
                self.assertIn('--read-only', command)
                self.assertIn('--cap-drop', command)
                self.assertIn('--pids-limit', command)
                self.assertIn('--pull=never', command)
                binds = [command[i + 1] for i, item in enumerate(command) if item == '--mount']
                self.assertTrue(any('target=/input,readonly' in b for b in binds))
                working = next(root.glob('Cowork Runs/*/working'))
                self.assertTrue(all(str(root).replace('\\', '/') + ',target=' not in b for b in binds))
                (working / 'keep.txt').write_text('proposal')
                (working / 'delete.txt').unlink()
                (working / 'new.txt').write_text('new')
                return 0, 'done', ''
            with patch.object(runner, 'find_container_engine', return_value={'daemon_running': True, 'path': 'docker', 'engine': 'docker'}), patch.object(
                    runner, 'get_container_image', return_value='approved'), patch.object(runner, '_execute', side_effect=execute):
                result = runner.run_code_in_container('', root)
            self.assertEqual(result['exit_code'], 0, result)
            self.assertEqual((root / 'keep.txt').read_text(), 'source')
            self.assertEqual((root / 'delete.txt').read_text(), 'retain original')
            self.assertEqual(result['deleted_files'], ['delete.txt'])
            self.assertEqual(len(result['changed_files']), 2)
            self.assertTrue(all(p.startswith('Cowork Runs/') for p in result['changed_files']))
            manifest = json.loads((root / 'Cowork Runs' / result['run_id'] / 'manifest.json').read_text())
            self.assertIn('keep.txt', manifest['source_hashes'])

    def test_invalid_cwd_does_not_create_outside_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'workspace'
            root.mkdir()
            with patch.object(runner, 'find_container_engine', return_value={'daemon_running': True, 'path': 'docker', 'engine': 'docker'}), patch.object(
                    runner, 'get_container_image', return_value='approved'):
                result = runner.run_code_in_container('', root, '../outside')
            self.assertEqual(result['exit_code'], 1)
            self.assertFalse((Path(directory) / 'outside').exists())

    def test_timeout_removes_container_before_killing_cli(self):
        proc = Mock(stdout=io.BytesIO(b'hello'), stderr=io.BytesIO(b''))
        proc.poll.return_value = None
        with patch.object(runner.subprocess, 'Popen', return_value=proc), patch.object(
                runner, '_remove_container') as remove, patch.object(runner.time, 'monotonic', side_effect=[0, 2]):
            result = runner._execute(['docker'], 'docker', 'expo-task-test', 1)
        self.assertEqual(result[0], 124)
        remove.assert_called_once_with('docker', 'expo-task-test')
        proc.kill.assert_called_once()

    def test_text_generation_is_staged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'report.md').write_text('original')
            result = stage_text_write(root, 'report.md', 'revision')
            self.assertEqual((root / 'report.md').read_text(), 'original')
            self.assertEqual((root / result['path']).read_text(), 'revision')


class PlotFixes(unittest.TestCase):
    def test_actual_provenance_and_gfa_fields(self):
        plot = MasterplanPlot(plot_id='P-5555555', permitted_gfa=900, achieved_gfa=0,
                              provenance=[{'filename': 'new-register.xlsx', 'sheet': 'New sheet', 'row': 7}])
        answer, sources = plot_answer(plot, [{'filename': 'new-register.xlsx'}])
        self.assertIn('Permitted GFA**: 900.0', answer)
        self.assertIn('Achieved GFA**: 0.0', answer)
        self.assertEqual(sources[0]['filename'], 'new-register.xlsx')
        self.assertEqual(sources[0]['row'], 7)
        self.assertNotIn('25-6963', answer)
        answer, sources = plot_answer(plot, [])
        self.assertEqual(sources, [])
        self.assertIn('provenance was not recorded', answer)

    def test_provenance_survives_database_roundtrip(self):
        from services.masterplan import db
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'EXPO_MP_DB_PATH': str(Path(directory) / 'mp.db')}):
            plot = MasterplanPlot(plot_id='P-5555555', provenance=[{'filename': 'register.xlsx', 'row': 9}])
            db.save_plots_bulk('Audit', [plot])
            self.assertEqual(db.get_plot('Audit', plot.plot_id).provenance, plot.provenance)
            db.save_plot('Audit', plot)
            self.assertEqual(db.get_plot('Audit', plot.plot_id).provenance, plot.provenance)

    def test_action_router_returns_proposal_without_fabricated_counts(self):
        import db
        from services.query_router import QueryRouter
        with patch.object(db, 'SessionLocal') as sessions:
            sessions.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(id=1, name='Audit')
            for query in ('make all mixed use plots yellow', 'hide all text', 'save working copy'):
                result = QueryRouter.route_query('Audit', query, exact_documents=[])
                self.assertEqual(result.answer, 'Drawing action requested.')
                self.assertEqual(result.data['action_status'], 'pending')
                self.assertNotIn('33', result.answer)


class SessionFixes(unittest.TestCase):
    def test_application_cookie_rotation_logout_and_source_preservation(self):
        import secrets
        import auth
        import db
        from fastapi.testclient import TestClient
        import main
        db.init_db()
        name = 'audit_' + secrets.token_hex(5)
        password = 'Audit-pass-' + secrets.token_hex(6)
        user = db.create_user(name, auth.hash_password(password), role='admin')
        db.create_project(name, by=user)
        source = Path(main.project_workspace(name)) / 'original.txt'
        source.write_text('KEEP ORIGINAL')
        client = TestClient(main.app)
        login = client.post('/auth/login', json={'username':name, 'password':password})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn('httponly', login.headers['set-cookie'].lower())
        old_token = login.json()['token']
        self.assertEqual(client.get('/auth/me').status_code, 200)
        url = f'/projects/{name}/agent/workspace-file'
        saved = client.put(url, json={'path':'original.txt', 'content':'WORKING COPY'})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(source.read_text(), 'KEEP ORIGINAL')
        self.assertEqual((Path(main.project_workspace(name)) / saved.json()['path']).read_text(), 'WORKING COPY')
        blocked = client.put(url, headers={'Origin':'https://other.invalid'}, json={'path':'original.txt','content':'BAD'})
        self.assertEqual(blocked.status_code, 403)
        rotated = client.post('/auth/change-password', json={'old_password':password,'new_password':password+'-new'})
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(client.get('/auth/me').status_code, 200)
        self.assertEqual(client.get('/auth/me',headers={'Authorization':'Bearer '+old_token}).status_code,401)
        self.assertEqual(client.post('/auth/logout').status_code,200)
        self.assertEqual(client.get('/auth/me').status_code,401)
        self.assertEqual(client.get('/auth/me?token='+rotated.json()['token']).status_code,401)

    def test_query_token_never_authenticates_but_cookie_does(self):
        import auth
        user = {'id': 7, 'username': 'tester', 'role': 'user', 'is_active': True, 'auth_version': 0}
        request = SimpleNamespace(headers={}, query_params={'token': 'stolen'}, cookies={})
        with patch.object(auth, 'decode_token', return_value={'sub': '7'}) as decode, patch('db.get_user', return_value=user):
            self.assertIsNone(auth.user_from_request(request))
            decode.assert_not_called()
            request.cookies = {'expo_token': 'session'}
            self.assertEqual(auth.user_from_request(request)['id'], 7)
            decode.assert_called_once_with('session')

    def test_rotated_session_response_refreshes_httponly_cookie(self):
        from routers.auth_routes import _session_response
        request = SimpleNamespace(url=SimpleNamespace(scheme='https'))
        response = _session_response({'token': 'replacement'}, request)
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie)
        self.assertIn('secure', cookie)

    def test_cookie_mutation_rejects_cross_origin(self):
        import asyncio
        from fastapi.responses import JSONResponse
        from starlette.requests import Request
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_auth_mw')
        node.decorator_list = []
        scope = {'auth': SimpleNamespace(user_from_request=lambda r: {'id': 1}), 'JSONResponse': JSONResponse}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'middleware', 'exec'), scope)
        async def check(origin):
            request = Request({'type':'http', 'method':'POST', 'scheme':'http', 'server':('testserver',80),
                'path':'/change', 'root_path':'', 'query_string':b'',
                'headers':[(b'host',b'testserver'),(b'origin',origin.encode())]})
            async def next_handler(request):
                return JSONResponse({'ok':True})
            return await scope['_auth_mw'](request,next_handler)
        self.assertEqual(asyncio.run(check('https://other.invalid')).status_code,403)
        self.assertEqual(asyncio.run(check('http://testserver')).status_code,200)



if __name__ == '__main__':
    unittest.main()
