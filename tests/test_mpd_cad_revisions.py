import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import ezdxf
import ast
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
engine=load_module('revision_engine','services/masterplan/cad_revisions.py')
matcher=load_module('hatch_matcher','services/masterplan/parsers/hatch_link.py')


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'output');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.dxf'
        doc=ezdxf.new();doc.header['$INSUNITS']=6
        doc.layers.new('RetainMe',dxfattribs={'color':4})
        msp=doc.modelspace()
        hatch=msp.add_hatch();hatch.paths.add_polyline_path([(0,0),(10,0),(10,10),(0,10)],is_closed=True)
        self.handle=hatch.dxf.handle
        msp.add_mtext('5210766 | EB.04.C.01\n100 sqm',dxfattribs={'insert':(5,5)})
        self.line=msp.add_line((50,60),(70,80),dxfattribs={'layer':'RetainMe'}).dxf.handle
        doc.layouts.new('KeepLayout')
        doc.saveas(self.source)
        self.before=self.source.read_bytes()

    def edit(self,**kw):
        return engine.create_revision(self.root/'vault','Project',self.source,['P-5210766'],'yellow',1,ezdxf.readfile,lambda doc,path:doc.saveas(path),match_hatches=matcher.linked_hatches,**kw)

    def test_original_exact_and_working_hatch_saved_with_other_objects(self):
        result=self.edit();folder,manifest=engine.read_revision(self.root/'vault','Project',result['revision'])
        self.assertEqual(self.source.read_bytes(),self.before)
        self.assertEqual((folder/manifest['original']).read_bytes(),self.before)
        working=ezdxf.readfile(folder/manifest['working'])
        self.assertEqual(working.entitydb[self.handle].dxf.true_color,0xffff00)
        self.assertEqual(tuple(working.entitydb[self.line].dxf.start),(50,60,0))
        self.assertIn('RetainMe',working.layers)
        self.assertIn('KeepLayout',working.layouts)

    def test_unknown_plot_does_not_modify_source_or_publish_manifest(self):
        with self.assertRaisesRegex(ValueError,'unique'):
            engine.create_revision(self.root/'vault','Project',self.source,['P-0000000'],'yellow',1,ezdxf.readfile,lambda d,p:d.saveas(p),match_hatches=matcher.linked_hatches)
        self.assertEqual(self.source.read_bytes(),self.before)
        self.assertEqual(list((self.root/'vault').rglob('manifest.json')),[])

    def test_tampered_revision_fails_closed(self):
        result=self.edit();folder=engine.revision_folder(self.root/'vault','Project',result['revision'])
        (folder/result['working']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):
            engine.read_revision(self.root/'vault','Project',result['revision'])

    def test_other_project_cannot_resolve_revision(self):
        result=self.edit()
        with self.assertRaises(OSError):
            engine.read_revision(self.root/'vault','Other',result['revision'])

    def test_bad_revision_path_rejected(self):
        with self.assertRaises(ValueError):engine.revision_folder(self.root,'Project','../escape')

    def test_second_revision_can_start_from_working_copy(self):
        first=self.edit();folder,_=engine.read_revision(self.root/'vault','Project',first['revision'])
        second=self.edit(base_working=folder/first['working'])
        self.assertNotEqual(first['revision'],second['revision'])
        self.assertEqual(self.source.read_bytes(),self.before)

    def test_roundtrip_loss_is_not_published(self):
        def lossy_save(doc,path):
            doc.modelspace().delete_entity(doc.entitydb[self.line])
            doc.saveas(path)
        with self.assertRaisesRegex(ValueError,'Non-target'):
            engine.create_revision(self.root/'vault','Project',self.source,['P-5210766'],'yellow',1,ezdxf.readfile,lossy_save,match_hatches=matcher.linked_hatches)
        self.assertEqual(list((self.root/'vault').rglob('manifest.json')),[])
        self.assertEqual(self.source.read_bytes(),self.before)

    def test_unique_block_edits_original_definition_without_exploding_it(self):
        doc=ezdxf.new();doc.header['$INSUNITS']=6
        block=doc.blocks.new('ParcelBlock')
        hatch=block.add_hatch();hatch.paths.add_polyline_path([(0,0),(10,0),(10,10),(0,10)],is_closed=True)
        block.add_mtext('5210766 | TEST\n100 sqm',dxfattribs={'insert':(5,5)})
        doc.modelspace().add_blockref('ParcelBlock',(100,200),dxfattribs={'rotation':90})
        doc.saveas(self.source);self.before=self.source.read_bytes()
        result=self.edit();folder,_=engine.read_revision(self.root/'vault','Project',result['revision'])
        saved=ezdxf.readfile(folder/result['working'])
        self.assertEqual(len(saved.modelspace().query('INSERT')),1)
        self.assertEqual(saved.blocks.get('ParcelBlock').query('HATCH')[0].dxf.true_color,0xffff00)

    def test_successive_edits_keep_previous_plot_color(self):
        doc=ezdxf.readfile(self.source)
        hatch=doc.modelspace().add_hatch();hatch.paths.add_polyline_path([(20,0),(30,0),(30,10),(20,10)],is_closed=True)
        second_handle=hatch.dxf.handle
        doc.modelspace().add_mtext('5210767 | TEST\n100 sqm',dxfattribs={'insert':(25,5)})
        doc.saveas(self.source);self.before=self.source.read_bytes()
        first=self.edit();folder,_=engine.read_revision(self.root/'vault','Project',first['revision'])
        second=engine.create_revision(self.root/'vault','Project',self.source,['P-5210767'],'blue',1,ezdxf.readfile,lambda d,p:d.saveas(p),base_working=folder/first['working'],match_hatches=matcher.linked_hatches)
        final_folder,_=engine.read_revision(self.root/'vault','Project',second['revision'])
        final=ezdxf.readfile(final_folder/second['working'])
        self.assertEqual(final.entitydb[self.handle].dxf.true_color,0xffff00)
        self.assertEqual(final.entitydb[second_handle].dxf.true_color,0x0080ff)


class RevisionPermissions(unittest.IsolatedAsyncioTestCase):
    def endpoint(self):
        from fastapi import Request, HTTPException
        tree=ast.parse((ROOT/'services/masterplan/api.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='download_cad_revision')
        fn.decorator_list=[]
        fn.body=[n for n in fn.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
        auth=Mock(); read=Mock()
        env={'Request':Request,'HTTPException':HTTPException,'auth':auth,'read_revision':read,'_revision_root':lambda:'vault','FileResponse':Mock()}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'api','exec'),env)
        return env['download_cad_revision'],auth,read

    async def test_non_admin_original_download_denied_before_read(self):
        from fastapi import HTTPException
        endpoint,auth,read=self.endpoint()
        auth.require_roles.side_effect=HTTPException(403,'Admin only')
        with self.assertRaises(HTTPException) as error:
            await endpoint('Project','a'*32,'original',object())
        self.assertEqual(error.exception.status_code,403)
        read.assert_not_called()

    async def test_wrong_project_denied_before_read(self):
        from fastapi import HTTPException
        endpoint,auth,read=self.endpoint()
        auth.require_project.side_effect=HTTPException(403,'No project access')
        with self.assertRaises(HTTPException):
            await endpoint('Other','a'*32,'working',object())
        read.assert_not_called()
