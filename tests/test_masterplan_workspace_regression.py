import ast
import asyncio
import re
import runpy
import sqlite3
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_cad_is_used_and_deleted_source_rejected(self):
        from fastapi import Query, HTTPException
        import os
        tree=ast.parse((ROOT/'services/masterplan/api.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='get_project_cad_drawing')
        fn.decorator_list=[]
        with tempfile.TemporaryDirectory() as folder:
            a=Path(folder)/'a.dxf';a.write_text('a')
            b=Path(folder)/'b.dxf';b.write_text('b')
            files=[{'id':'A','file_type':'cad','file_path':str(a)},{'id':'B','file_type':'cad','file_path':str(b)}]
            cache={('Test',str(a),os.path.getmtime(a)):{'selected':'A'},('Test',str(b),os.path.getmtime(b)):{'selected':'B'}}
            from typing import Optional
            env={'Optional':Optional,'Query':Query,'HTTPException':HTTPException,'db':types.SimpleNamespace(get_file_records=lambda p:files),'os':os,'_CAD_DRAWING_CACHE':cache}
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'api','exec'),env)
            self.assertEqual((await env['get_project_cad_drawing']('Test','B'))['selected'],'B')
            with self.assertRaises(HTTPException) as error:
                await env['get_project_cad_drawing']('Test','Deleted')
            self.assertEqual(error.exception.status_code,404)

    async def test_mixed_type_routes_without_model_and_retains_all_ids_and_color(self):
        models = runpy.run_path(str(ROOT/'services/masterplan/models.py'))
        tree = ast.parse((ROOT/'services/masterplan/agent.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('_execute_tool','_fallback_deterministic_plan') or isinstance(n, ast.AsyncFunctionDef) and n.name == 'process_query']
        plots = [types.SimpleNamespace(plot_id=f'P-{i}', far=1.0, achieved_gfa=10, area_sqm=10, sector='A',land_use='Mixed Use',status='compliant', dict=lambda **kw: {}) for i in range(34)]
        for p in plots:
            p.dict = lambda p=p, **kw: vars(p)
        database = types.SimpleNamespace(get_plots=Mock(return_value=plots))
        env = {'parse_view_command':runpy.run_path(str(ROOT/'services/masterplan/view_commands.py'))['parse_view_command'],'re':re,'db':database,'Dict':dict,'Any':object,'MasterplanAIQueryResponse':models['MasterplanAIQueryResponse'],'MasterplanAIQueryRequest':models['MasterplanAIQueryRequest']}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'agent','exec'),env)
        agent = env['MasterplanAIAgent']()
        result = await agent.process_query(models['MasterplanAIQueryRequest'](query='show all mixed type in yellow',project_id='Test'))
        self.assertEqual(result.intent,'QUERY_LAND_USE')
        self.assertEqual(len(result.highlight_plots),34)
        self.assertEqual(result.highlight_color,'#ffff00')
        self.assertIn('34',result.answer)

    async def test_unverified_audit_does_not_claim_fake_compliance(self):
        models=runpy.run_path(str(ROOT/'services/masterplan/models.py'))
        tree=ast.parse((ROOT/'services/masterplan/agent.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_fallback_deterministic_plan')
        env={'re':re,'MasterplanAIQueryResponse':models['MasterplanAIQueryResponse']}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'agent','exec'),env)
        result=env['_fallback_deterministic_plan'](None,'audit cad','Test')
        self.assertEqual(result.confidence,0)
        self.assertNotIn('99.8',result.answer)

    async def test_delete_cad_invalidates_geometry_retains_register(self):
        tree=ast.parse((ROOT/'services/masterplan/db.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='delete_file_record')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.db'
            def connection():
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
            with closing(connection()) as conn:
                conn.executescript("CREATE TABLE mp_files(id,project_id,file_path,filename,file_type); CREATE TABLE mp_file_relations(project_id,cad_file,excel_file); CREATE TABLE mp_plots(project_id,geometry_json); CREATE TABLE mp_audit_log(project_id); INSERT INTO mp_files VALUES('cad','Test',NULL,'old.dwg','cad'),('excel','Test',NULL,'reg.xlsx','excel'); INSERT INTO mp_plots VALUES('Test','old geometry');")
                conn.commit()
            import os
            env={'init_db':lambda:None,'get_connection':connection,'os':os,'__file__':str(ROOT/'services/masterplan/db.py')}
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'db','exec'),env)
            self.assertTrue(env['delete_file_record']('Test','cad'))
            with closing(connection()) as conn:
                self.assertIsNone(conn.execute('SELECT geometry_json FROM mp_plots').fetchone()[0])
                self.assertEqual(conn.execute('SELECT count(*) FROM mp_files').fetchone()[0],1)


if __name__=='__main__':unittest.main()
