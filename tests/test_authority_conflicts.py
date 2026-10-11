import json,tempfile,unittest
from pathlib import Path
from intelligence.exact_answers import exact_answer


class AuthorityConflictTests(unittest.TestCase):
    def test_newer_filename_never_supersedes_explicit_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            docs=[]
            for filename,revision,state,value in [('schedule(01).pdf','A','Approved','384'),('schedule(99).pdf','Z','Draft','499')]:
                path=Path(directory)/filename
                meta={'processing_complete':True,'pages':[{'page':2,'text':f'Revision {revision}. Status: {state}.',
                    'tables':f'| Metric | SQ.M. |\n| --- | --- |\n| Plot Area | {value} |'}]}
                Path(str(path)+'.index.json').write_text(json.dumps(meta))
                docs.append({'filename':filename,'path':str(path),'status':'ready'})
            self.assertEqual(exact_answer('What is the Plot Area?',docs)['status'],'AMBIGUOUS')
            approved=exact_answer('What is the approved Plot Area?',docs)
            self.assertEqual(approved['status'],'SUCCESS')
            self.assertEqual(approved['facts'][0]['value'],'384')
            self.assertEqual(approved['facts'][0]['revision'],'A')
            self.assertEqual(exact_answer('What is the current Plot Area?',docs)['status'],'NOT_FOUND')

    def test_missing_authority_cannot_be_inferred_from_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'approved-latest-rev99.pdf'
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Revision Z.',
                'tables':'| Metric | SQ.M. |\n| --- | --- |\n| Plot Area | 384 |'}]}))
            docs=[{'filename':path.name,'path':str(path),'status':'ready'}]
            self.assertEqual(exact_answer('What is the approved Plot Area?',docs)['status'],'NOT_FOUND')
