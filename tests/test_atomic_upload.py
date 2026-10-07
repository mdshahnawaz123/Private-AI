import ast
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException


class AtomicUploadTests(unittest.TestCase):
    def test_invalid_replacement_preserves_original_and_removes_temporary(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_save_verified_upload')
        scope={'os':os,'HTTPException':HTTPException,
            '_save_upload_capped':lambda file,path:Path(path).write_bytes(file.data),
            'validate_file_content':lambda path,ext:Path(path).read_bytes().startswith(b'%PDF')}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-upload-function','exec'),scope)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'original.pdf';path.write_bytes(b'%PDF original')
            with self.assertRaises(HTTPException):scope['_save_verified_upload'](SimpleNamespace(data=b'invalid'),str(path),'.pdf')
            self.assertEqual(path.read_bytes(),b'%PDF original')
            self.assertEqual(list(Path(root).iterdir()),[path])
            scope['_save_verified_upload'](SimpleNamespace(data=b'%PDF replacement'),str(path),'.pdf')
            self.assertEqual(path.read_bytes(),b'%PDF replacement')

if __name__=='__main__':unittest.main()
