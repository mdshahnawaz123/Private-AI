import json
from pathlib import Path
import tempfile
import unittest
from intelligence.exact_answers import exact_answer
from intelligence.table_evidence import table_row_units
from intelligence.document_memory import verify_fact,_page_text_map
from intelligence.document_investigation import inspect_coverage,needs_coverage
from intelligence.answer_guard import publication_issues


class EvidenceRemediation(unittest.TestCase):
    def test_focused_chunks_require_folder_identity(self):
        from intelligence.document_investigation import focused_chunk_allowed
        scope={'same.pdf':4}
        self.assertTrue(focused_chunk_allowed({'source':'same.pdf','folder_id':4},scope))
        self.assertFalse(focused_chunk_allowed({'source':'same.pdf','folder_id':8},scope))
        self.assertFalse(focused_chunk_allowed({'source':'same.pdf'},scope))
        self.assertFalse(focused_chunk_allowed({'source':'different.pdf','folder_id':4},scope))
    def answer(self,question,tables):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'synthetic.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':2,'text':'Synthetic native source','tables':tables}]}))
            return exact_answer(question,[{'path':path,'filename':'synthetic.pdf'}])

    def test_category_does_not_relabel_combined_total(self):
        table='UNIT SUMMARY\n| ITEM | NO. |\n| Retail Units: | 7 |\n| F&B Units: | 4 |\n| TOTAL | 11 |'
        self.assertTrue(all('Table: UNIT SUMMARY' in r for r in table_row_units(table)))
        self.assertEqual(self.answer('How many F&B units are there?',table)['facts'][0]['value'],'4')
        self.assertEqual(self.answer('How many retail units?',table)['facts'][0]['value'],'7')

    def test_limit_comparison_and_missing_conflicting_inputs(self):
        table='| ITEM | SQ.M. |\n| GFA Proposed: | 27.5 |\n| GFA Allowed: | 30 |'
        result=self.answer('Is GFA proposed within GFA allowed limit?',table)
        self.assertEqual(result['calculation']['result'],'2.5')
        self.assertEqual(result['calculation']['operands'],['27.5','30'])
        self.assertNotEqual(self.answer('Is GFA proposed within GFA allowed limit?',table+'\n| GFA Allowed: | 31 |')['status'],'SUCCESS')
        self.assertNotEqual(self.answer('Is GFA proposed within GFA allowed limit?',table.replace('30','-'))['status'],'SUCCESS')

    def test_vision_and_wrong_relationship_do_not_verify(self):
        fact={'property':'Area','page':1,'claim':'Allowed area 24 sqm.','evidence_quote':'Allowed area 24 sqm.'}
        self.assertNotEqual(verify_fact(fact,[1],_page_text_map({'pages':[{'page':1,'vision':fact['claim']}]}))[0],'VERIFIED')
        native={1:fact['claim'].lower()}
        self.assertEqual(verify_fact(fact,[1],native)[0],'VERIFIED')
        fact['claim']='Proposed area 24 sqm.'
        self.assertNotEqual(verify_fact(fact,[1],native)[0],'VERIFIED')

    def test_units_require_affirmative_support(self):
        sources=[{'source':'synthetic.pdf','page':2}]
        answer='Area 24 sqm [SOURCE: synthetic.pdf | PAGE 2]'
        self.assertTrue(publication_issues(answer,'[SOURCE: synthetic.pdf | PAGE 2]\nArea 24',sources))
        self.assertFalse(publication_issues(answer,'[SOURCE: synthetic.pdf | PAGE 2]\n| ITEM | SQ.M. |\n| Plot Area: | 24 |',sources))

    def test_absence_requires_coverage_and_partial_is_disclosed(self):
        self.assertTrue(needs_coverage('What fire requirements are not available?'))
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'synthetic.pdf')
            Path(path+'.index.json').write_text(json.dumps({'total_pages':2,'truncated':True,'pages':[{'page':1,'text':'Read page'}]}))
            _,context,complete=inspect_coverage([{'path':path,'filename':'synthetic.pdf'}])
            self.assertFalse(complete)
            self.assertIn('INCOMPLETE',context)

    def test_ratio_and_missing_comparison_are_not_area_or_inferred_values(self):
        table='| ITEM | SQ.M. |\n| FAR Allowed: | 1.9 |\n| FAR Proposed: | - |'
        result=self.answer('What is FAR allowed?',table)
        self.assertEqual(result['facts'][0]['value'],'1.9')
        self.assertEqual(result['facts'][0]['unit'],'ratio')
        self.assertNotEqual(self.answer('Is FAR proposed within FAR allowed?',table)['status'],'SUCCESS')

    def test_all_floor_metrics_are_exposed_without_choosing_one(self):
        table='BUILT-UP AREA BREAKDOWN\n| ITEM | SQ.M. |\n| 3rd Floor | 41 |\n\nGROSS FLOOR AREA BREAKDOWN\n| ITEM | SQ.M. |\n| 3rd Floor | 32 |\n\nNET SELLABLE AREA BREAKDOWN\n| ITEM | SQ.M. |\n| 3rd Floor | 29 |'
        result=self.answer('What is the 3rd floor area?',table)
        self.assertEqual([f['value'] for f in result['facts']],['41','32','29'])

    def test_partial_or_changed_source_cannot_supply_exact_values(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'synthetic.pdf';path.write_bytes(b'original source')
            meta={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'pages':[{'page':1,'tables':'| ITEM | SQ.M. |\n| GFA Proposed: | 16 |'}]}
            sidecar=Path(str(path)+'.index.json');sidecar.write_text(json.dumps(meta))
            doc={'path':str(path),'filename':path.name}
            self.assertEqual(exact_answer('GFA proposed',[doc])['status'],'SUCCESS')
            meta['truncated']=True;sidecar.write_text(json.dumps(meta))
            self.assertEqual(exact_answer('GFA proposed',[doc])['status'],'NOT_FOUND')
            meta['truncated']=False;sidecar.write_text(json.dumps(meta));path.write_bytes(b'changed source')
            self.assertEqual(exact_answer('GFA proposed',[doc])['status'],'NOT_FOUND')
