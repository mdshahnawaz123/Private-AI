import ast
import runpy
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parse=runpy.run_path(str(ROOT/'services/masterplan/view_commands.py'))['parse_view_command']


class ViewTests(unittest.IsolatedAsyncioTestCase):
    def test_supported_commands_and_unsupported_requests(self):
        for query in ['hide all text','please hide the text','turn off labels']:
            self.assertEqual(parse(query),{'type':'set_text_mode','mode':'off'})
        self.assertEqual(parse('show all text')['mode'],'all')
        self.assertEqual(parse('set text size to 65%')['scale'],.65)
        self.assertEqual(parse('zoom to fit')['type'],'fit_view')
        self.assertEqual(parse('make plot 5210766 yellow'),{'type':'edit_hatches','plot_ids':['P-5210766'],'color':'yellow'})
        self.assertEqual(parse('make all mixed use plots yellow'),{'type':'edit_hatches','land_use':'Mixed Use','color':'yellow'})
        self.assertEqual(parse('change mixed use color to orange'),{'type':'edit_hatches','land_use':'Mixed Use','color':'orange'})
        self.assertEqual(parse('change the color of mixed use to red'),{'type':'edit_hatches','land_use':'Mixed Use','color':'red'})
        self.assertEqual(parse('show me only mixed use'),{'type':'isolate_land_use','land_use':'Mixed Use'})
        self.assertEqual(parse('only show residential plots'),{'type':'isolate_land_use','land_use':'Residential'})
        self.assertEqual(parse('show all plots'),{'type':'isolate_land_use','land_use':None})
        self.assertEqual(parse('change the color to red'),{'type':'recolor_active','color':'red'})
        self.assertEqual(parse('save as copy')['type'],'save_working_copy')
        self.assertEqual(parse('go back to original')['type'],'return_to_original')
        for query in ['do not hide text','why hide text','set text size to 500%','delete all plots']:
            self.assertIsNone(parse(query))

    async def test_view_action_bypasses_database_and_model(self):
        models=runpy.run_path(str(ROOT/'services/masterplan/models.py'))
        tree=ast.parse((ROOT/'services/masterplan/agent.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='process_query')
        import re
        from loguru import logger
        env={'parse_view_command':parse,'MasterplanAIQueryRequest':models['MasterplanAIQueryRequest'],'MasterplanAIQueryResponse':models['MasterplanAIQueryResponse'],'logger':logger,'re':re}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'agent','exec'),env)
        response=await env['process_query'](None,models['MasterplanAIQueryRequest'](query='hide all text',project_id='Test'))
        self.assertEqual(response.intent,'VIEW_ACTION')
        self.assertEqual(response.view_actions,[{'type':'set_text_mode','mode':'off'}])
        self.assertNotIn('Hidden',response.answer)
