import json
import tempfile
import unittest
from pathlib import Path
from intelligence.page_context import select_page_context


class PageContextTests(unittest.TestCase):
    def test_explicit_page_keeps_complete_row_and_excludes_other_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'schedule.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[
                {'page':1,'text':'OTHER PAGE 999'},
                {'page':7,'text':'Podium','tables':'| GF PODIUM | 12 | 34 | 56 |'},
                {'page':8,'text':'OTHER PAGE 888'}]}))
            sources,text=select_page_context(path,'schedule.pdf','Podium areas on page 7')
            self.assertEqual(sources,[{'source':'schedule.pdf','page':7}])
            self.assertIn('| GF PODIUM | 12 | 34 | 56 |',text)
            self.assertNotIn('OTHER PAGE',text)
            self.assertEqual(select_page_context(path,'schedule.pdf','page 99'),([],''))

    def test_long_page_clipping_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'schedule.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':7,'text':'A'*2000}]}))
            sources,text=select_page_context(path,'schedule.pdf','page 7',budget=500)
            self.assertEqual(sources[0]['page'],7)
            self.assertIn('EXCERPT ENDS',text)
