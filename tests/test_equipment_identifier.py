import json,tempfile,unittest
from pathlib import Path
from intelligence.exact_answers import exact_answer

class EquipmentIdentifierTests(unittest.TestCase):
    def test_verbatim_page_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'maintenance.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Equipment identifier EQ-001.'},{'page':60,'text':'Equipment identifier SYNTH-060.'}]}))
            docs=[{'path':path,'filename':'maintenance.pdf','status':'ready'}]
            self.assertIn('SYNTH-060',exact_answer('What equipment identifier is on page 60?',docs)['answer'])
            self.assertEqual(exact_answer('What equipment identifier is on page 99?',docs)['status'],'NOT_FOUND')
            self.assertEqual(exact_answer('What equipment identifier is listed?',docs)['status'],'AMBIGUOUS')
