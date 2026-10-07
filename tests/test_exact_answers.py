import json
import tempfile
import unittest
from pathlib import Path
from intelligence.exact_answers import exact_answer


class SourceTableAnswers(unittest.TestCase):
    def test_explicit_wrong_page_does_not_use_matching_value_elsewhere(self):
        table='| TOWER 3 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 8 |'
        self.assertEqual(self.answer('Tower 3 Level 02 GFA page 8',table)['status'],'NOT_FOUND')
        self.assertEqual(self.answer('Tower 3 Level 02 GFA page 9',table)['status'],'SUCCESS')
    def test_parking_categories_and_dispositions_keep_their_columns(self):
        table='| PARKING | NORMAL | TANDEM | POD | CURRENT EV (5%) | FUTURE EV |\n| GRAND TOTAL REQUIRED | 12 | 3 | 0 | 2 | 4 |\n| GRAND TOTAL ACHIEVED | 15 | 3 | 1 | 2 | 4 |'
        result=self.answer('parking required and achieved normal, tandem, POD, current EV and future EV bays',table)
        self.assertEqual(result['status'],'SUCCESS')
        self.assertEqual([f['value'] for f in result['facts']],['12','3','0','2','4','15','3','1','2','4'])
        self.assertTrue(all(f['page']==9 and f['unit']=='bays' for f in result['facts']))
        # A future provision is a separate column, not added to parking supply.
        self.assertNotIn('Sum:',result['answer'])

    def test_parking_missing_or_conflicting_category_is_not_guessed(self):
        table='| PARKING | NORMAL |\n| GRAND TOTAL REQUIRED | 12 |\n| GRAND TOTAL REQUIRED | 13 |'
        self.assertEqual(self.answer('parking required normal bays',table)['status'],'AMBIGUOUS')
        self.assertEqual(self.answer('parking required normal and future EV bays',table)['status'],'NOT_FOUND')

    def answer(self, question, tables, text=''):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'evidence.pdf'
            Path(str(path)+'.index.json').write_text(json.dumps({'pages':[{'page':9,'tables':tables,'text':text}]}),encoding='utf-8')
            return exact_answer(question,[{'filename':'evidence.pdf','path':str(path)}])

    def test_adjacent_tables_do_not_confuse_gfa_and_bua(self):
        result=self.answer('proposed GFA sqm','| ITEM | SQ.M. | ITEM | SQ.M. |\n| GFA Proposed: | 12.5 | BUA Proposed: | 99 |')
        self.assertEqual(result['facts'][0]['value'],'12.5')
        self.assertEqual(result['facts'][0]['page'],9)

    def test_zero_is_a_value(self):
        result=self.answer('Tower 3 Level 02 Floor GFA','| TOWER 3 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 0 |')
        self.assertEqual(result['facts'][0]['value'],'0')

    def test_conflicting_values_are_not_selected(self):
        result=self.answer('proposed GFA sqm','| ITEM | SQ.M. |\n| GFA Proposed: | 12 |\n| GFA Proposed: | 13 |')
        self.assertEqual(result['status'],'AMBIGUOUS')

    def test_missing_entity_is_not_another_tower(self):
        self.assertEqual(self.answer('Tower 4 Level 02 Floor GFA','| TOWER 3 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 8 |')['status'],'NOT_FOUND')

    def test_unit_selection_is_explicit(self):
        result=self.answer('proposed GFA square feet','| ITEM | SQ.M. | SQ.FT. |\n| GFA Proposed: | 12 | 129 |')
        self.assertEqual(result['facts'][0]['value'],'129')
        self.assertEqual(result['facts'][0]['unit'],'sqft')
        self.assertEqual(self.answer('Tower 3 Level 02 Floor GFA square feet',
            '| TOWER 3 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 8 |')['status'],'NOT_FOUND')

    def test_missing_requested_fact_does_not_return_partial_result(self):
        self.assertEqual(self.answer('proposed GFA and bicycle parking total','| ITEM | SQ.M. |\n| GFA Proposed: | 12 |')['status'],'NOT_FOUND')

    def test_concrete_test_basis_is_preserved_not_reinterpreted(self):
        source='The following are the initially proposed concrete cylindrical compressive strength\nat 28-day (equivalent 28-day Cubic strength): -\nFoundation\n32N/mm2 (45 N/mm2)'
        result=self.answer('concrete grade for foundations','',source)
        self.assertIn('initially proposed',result['answer'])
        self.assertIn('equivalent 28-day Cubic strength',result['answer'])
        self.assertIn('32N/mm2 (45 N/mm2)',result['answer'])
        self.assertNotIn('alternative',result['answer'])


if __name__=='__main__': unittest.main()
