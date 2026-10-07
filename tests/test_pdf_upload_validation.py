import ast
import tempfile
import unittest
from pathlib import Path
import pymupdf

class PdfUploadValidationTests(unittest.TestCase):
    def test_valid_corrupt_empty_and_encrypted_sources(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_file_content')
        scope={'MAGIC_BYTES':{'.pdf':b'%PDF'}}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'upload-validation','exec'),scope)
        validate=scope['validate_file_content']
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'sample.pdf'
            for data in (b'%PDF-1.7\ninvalid',b'',b'not a PDF'):
                target.write_bytes(data)
                self.assertFalse(validate(str(target),'.pdf'))
            document=pymupdf.open();document.new_page()
            target.write_bytes(document.tobytes())
            self.assertTrue(validate(str(target),'.pdf'))
            target.write_bytes(document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='reader'))
            self.assertFalse(validate(str(target),'.pdf'))
            document.close()
