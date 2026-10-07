import json
import tempfile
import unittest
from pathlib import Path
from intelligence.exact_answers import exact_answer


class Calculations(unittest.TestCase):
    def test_decimal_sum_and_difference_preserve_sources(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'schedule.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':6,'tables':
                '| TOWER 7 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 2054.1 |\n\n| TOWER 8 | |\n| LEVEL | Floor GFA (sqm) |\n| LEVEL 02 | 3229.2 |'}]}))
            docs=[{'path':path,'filename':'schedule.pdf'}]
            result=exact_answer('sum GFA Tower 7 and Tower 8 Level 02',docs)
            self.assertEqual(result['calculation']['result'],'5283.3')
            self.assertEqual(result['sources'][0]['page'],6)
            result=exact_answer('difference GFA Tower 7 and Tower 8 Level 02',docs)
            self.assertEqual(result['calculation']['result'],'-1175.1')
            self.assertEqual(exact_answer('sum GFA Tower 7 and Tower 9 Level 02',docs)['status'],'NOT_FOUND')

    def test_unsupported_calculation_never_falls_through_to_model(self):
        for query in ('calculate all parking','sum GFA Tower 7 Level 02 and Tower 8 Level 03','average GFA and NSA Tower 7 Level 02'):
            self.assertEqual(exact_answer(query,[])['status'],'UNSUPPORTED')

if __name__=='__main__': unittest.main()
