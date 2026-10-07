import json,tempfile,unittest
from pathlib import Path
from intelligence.source_semantics import explicit_states
from intelligence.exact_answers import exact_answer

class ReleaseSemantics(unittest.TestCase):
    def test_quantity_entities_are_not_associated_by_list_order_or_assumed_units(self):
        from knowledge.extraction import extract_quantities_from_pdf
        meta={'filename':'synthetic.pdf','pages':[{'page':3,'text':'TOWER 7\nTOWER 8\nTOS 12.5\nTOPR 14.5\nTOWER 9 TOS -2.5 m'}]}
        rows=extract_quantities_from_pdf(meta,1)
        self.assertEqual([(r['building'],r['metric'],r['value'],r['unit']) for r in rows],[('','TOS','12.5',''),('','TOPR','14.5',''),('Tower 9','TOS','-2.5','m')])

    def answer(self,question,text='',values=('12','24'),unit='sqm'):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'schedule.pdf')
            table=f'| TOWER 7 | |\n| LEVEL | Floor GFA ({unit}) |\n| LEVEL 02 | {values[0]} |\n\n| TOWER 8 | |\n| LEVEL | Floor GFA ({unit}) |\n| LEVEL 02 | {values[1]} |'
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':2,'text':text,'tables':table}]}))
            return exact_answer(question,[{'filename':'schedule.pdf','path':path,'status':'ready'}])

    def test_explicit_statuses_and_negative_approval(self):
        for status in ('Approved','Draft','Proposed','Superseded','Pending','TBC','Existing','Current'):
            self.assertEqual(explicit_states('Approval status: '+status),{status.upper()})
        self.assertEqual(explicit_states('Approval status: Not Approved'),{'UNKNOWN'})
        self.assertEqual(explicit_states('Revision: Z\nLatest revision'),{'UNKNOWN'})
        self.assertEqual(explicit_states('Status: Approved\nStatus: Draft'),{'APPROVED','DRAFT'})

    def test_approval_is_not_assumed_or_carried_into_calculation(self):
        for text in ('','Status: Draft','Status: Not Approved','Status: Approved\nStatus: Pending'):
            self.assertEqual(self.answer('Approved Tower 7 Level 02 GFA',text)['status'],'NOT_FOUND')
            self.assertEqual(self.answer('sum approved GFA Tower 7 and Tower 8 Level 02',text)['status'],'NOT_FOUND')
        self.assertEqual(self.answer('Approved Tower 7 Level 02 GFA','Status: Approved')['status'],'SUCCESS')
        self.assertEqual(self.answer('Current Tower 7 Level 02 GFA','Status: Approved')['status'],'NOT_FOUND')

    def test_formula_operands_sources_and_units(self):
        result=self.answer('average GFA Tower 7 and Tower 8 Level 02')
        self.assertEqual(result['calculation']['formula'],'(12 + 24) / 2')
        self.assertEqual(result['calculation']['operands'],['12','24'])
        self.assertEqual(result['calculation']['result'],'18')
        self.assertEqual(result['calculation']['sources'][0]['page'],2)
        self.assertEqual(result['calculation']['unit'],'sqm')
        self.assertEqual(self.answer('sum GFA Tower 7 and Tower 8 Level 02',unit='sqft')['status'],'NOT_FOUND')

    def test_negative_and_positive_values_do_not_collapse_into_agreement(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'schedule.pdf')
            table='| TOWER 7 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | -12 |\n| LEVEL 02 | 12 |'
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':2,'tables':table}]}))
            self.assertEqual(exact_answer('Tower 7 Level 02 GFA',[{'filename':'schedule.pdf','path':path}])['status'],'AMBIGUOUS')

    def test_identifier_lookup_preserves_requested_approval(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'equipment.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Status: Draft\nEquipment identifier SYNTH-060.'}]}))
            docs=[{'filename':'equipment.pdf','path':path}]
            self.assertEqual(exact_answer('approved equipment identifier',docs)['status'],'NOT_FOUND')
            self.assertEqual(exact_answer('draft equipment identifier',docs)['status'],'SUCCESS')
