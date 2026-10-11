import ast
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException, File, Form, Request, UploadFile
from services.cowork_workspace import resolve_path, read_file_page, READ_PAGE_CHARS


class CoworkWorkspaceTests(unittest.TestCase):
    def test_complete_large_unicode_file_has_no_total_read_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'large.txt'
            original = ('engineering Ω\r\n' * 4000) + 'FINAL FACT AFTER 5000'
            path.write_bytes(original.encode('utf-8'))
            offset = 0
            parts = []
            while True:
                page = read_file_page(path, offset)
                self.assertLessEqual(len(page['content']), READ_PAGE_CHARS)
                parts.append(page['content'])
                if page['eof']:
                    break
                self.assertGreater(page['next_offset'], offset)
                offset = page['next_offset']
            self.assertEqual(''.join(parts), original)

    def test_empty_eof_and_invalid_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'empty.txt';path.write_text('')
            self.assertTrue(read_file_page(path)['eof'])
            for offset, limit in [(-1, 10), (0, 0)]:
                with self.assertRaises(ValueError): read_file_page(path, offset, limit)

    def test_paths_reject_escape_and_keep_projects_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'A';root.mkdir()
            self.assertEqual(resolve_path(root, 'code/main.py'), root/'code'/'main.py')
            for path in ('../B/file', '/etc/file', 'C:/file', 'x:stream', 'a/../../B'):
                with self.assertRaises(ValueError): resolve_path(root, path)

    def test_symlink_escape_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'A';root.mkdir();outside=Path(directory)/'B';outside.mkdir()
            try: (root/'link').symlink_to(outside, target_is_directory=True)
            except OSError: self.skipTest('OS does not permit symlink creation')
            with self.assertRaises(ValueError): resolve_path(root,'link/secret.txt')

    def test_binary_is_not_claimed_as_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'binary';path.write_bytes(b'abc\x00def')
            with self.assertRaises(ValueError): read_file_page(path)

    def test_import_is_project_scoped_atomic_and_preserves_existing_files(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='import_cowork_file')
        node.decorator_list=[]
        with tempfile.TemporaryDirectory() as directory:
            workspace=Path(directory)
            checks=[]
            def root(project):
                path=workspace/project;path.mkdir(exist_ok=True);return str(path)
            scope={'os':os,'HTTPException':HTTPException,'Request':Request,'UploadFile':UploadFile,
                   'File':File,'Form':Form,'WORKSPACE_DIR':str(workspace),
                   'project_workspace':root,'resolve_in_workspace':lambda p,r:str(resolve_path(root(p),r)),
                   'auth':SimpleNamespace(require_roles=lambda r,*roles:checks.append(roles) or {'id':1},
                                          require_project=lambda r,p:checks.append(p)),
                   'db':SimpleNamespace(audit=lambda *a,**k:None)}
            exec(compile(ast.Module(body=[node],type_ignores=[]),'cowork-import','exec'),scope)
            upload=lambda data:SimpleNamespace(file=io.BytesIO(data))
            scope['import_cowork_file']('A',None,upload(b'original'),'folder/file.txt')
            with self.assertRaises(HTTPException) as failure:
                scope['import_cowork_file']('A',None,upload(b'replacement'),'folder/file.txt')
            self.assertEqual(failure.exception.status_code,409)
            self.assertEqual((workspace/'A/folder/file.txt').read_bytes(),b'original')
            self.assertFalse((workspace/'B').exists())
            self.assertEqual(list((workspace/'.imports').iterdir()),[])
            with patch('config.get_settings',return_value=SimpleNamespace(max_upload_size_mb=0)):
                with self.assertRaises(HTTPException) as failure:
                    scope['import_cowork_file']('A',None,upload(b'oversize'),'too-large.txt')
            self.assertEqual(failure.exception.status_code,413)
            self.assertFalse((workspace/'A/too-large.txt').exists())
            self.assertIn(('admin',),checks)
            self.assertIn('A',checks)
