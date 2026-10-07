import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

class RevisionNoticeTests(unittest.TestCase):
    def test_filename_order_does_not_claim_approval_or_supersession(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='revision_notice')
        group={'multi':True,'latest':'B','revisions':['A','B'],'items':[{'revision':'A','filename':'revision-a.pdf'},{'revision':'B','filename':'revision-b.pdf'}]}
        scope={'db':SimpleNamespace(list_documents=lambda project,user:[]),'meta_parse':SimpleNamespace(group_revisions=lambda docs:{'revision':group},_rev_sort_key=lambda r:r)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'revision-notice','exec'),scope)
        text=scope['revision_notice']('test')
        self.assertIn('Highest filename label = B',text)
        self.assertIn('approved value cannot be established',text)
        self.assertNotIn('Use the LATEST',text)
        self.assertNotIn('Superseded: A',text)
