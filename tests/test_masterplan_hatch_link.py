import importlib.util
from pathlib import Path
import unittest
import json
import ast
import re
import runpy
import types
import ezdxf

spec=importlib.util.spec_from_file_location('hatch_link',Path(__file__).resolve().parents[1]/'services/masterplan/parsers/hatch_link.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class HatchTests(unittest.TestCase):
    def test_explicit_leader_links_external_label_at_arrow_tip(self):
        doc=ezdxf.new();doc.header['$INSUNITS']=6
        msp=doc.modelspace()
        hatch=msp.add_hatch();hatch.paths.add_polyline_path([(0,0),(10,0),(10,10),(0,10)],is_closed=True)
        label=msp.add_mtext('5219797 | EF.11.U.10\n99.97 sqm',dxfattribs={'insert':(20,20)})
        msp.add_leader([(5,5),(20,20)],dxfattribs={'annotation_handle':label.dxf.handle,'has_arrowhead':1})
        rows=module.linked_hatches(doc,'leader.dxf')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['plot_id'],'P-5219797')
        self.assertEqual(rows[0]['geometry']['label_anchor'],[5,5])
        self.assertEqual(json.loads(rows[0]['notes'])['annotated_area_sqm'],99.97)

    def drawing(self):
        doc=ezdxf.new();doc.header['$INSUNITS']=6
        block=doc.blocks.new('PARCEL')
        hatch=block.add_hatch()
        hatch.paths.add_polyline_path([(0,0),(10,0),(10,10),(0,10)],is_closed=True)
        block.add_mtext('5210766 | EB.04.C.01\n100 sqm\nGFA: 500 sqm',dxfattribs={'insert':(5,5)})
        doc.modelspace().add_blockref('PARCEL',(100,200),dxfattribs={'rotation':90,'xscale':2,'yscale':2})
        return doc

    def test_block_transform_label_id_and_two_distinct_area_sources(self):
        result=module.linked_hatches(self.drawing(),'source.dxf')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['plot_id'],'P-5210766')
        self.assertAlmostEqual(result[0]['area_sqm'],400)
        evidence=json.loads(result[0]['notes'])
        self.assertEqual(evidence['annotated_area_sqm'],100)
        self.assertEqual(evidence['area_discrepancy_sqm'],-300)
        self.assertIn('PARCEL',evidence['entity_path'])
        self.assertEqual(result[0]['status'],'under_review')

    def test_duplicate_overlapping_hatch_abstains(self):
        doc=self.drawing();block=doc.blocks.get('PARCEL')
        hatch=block.add_hatch();hatch.paths.add_polyline_path([(0,0),(10,0),(10,10),(0,10)],is_closed=True)
        self.assertEqual(module.linked_hatches(doc,'source.dxf'),[])

    def test_two_ids_in_one_boundary_abstains(self):
        doc=self.drawing();doc.blocks.get('PARCEL').add_text('5210767',dxfattribs={'insert':(6,6)})
        self.assertEqual(module.linked_hatches(doc,'source.dxf'),[])

    def test_unknown_units_do_not_claim_measured_area(self):
        doc=self.drawing();doc.header['$INSUNITS']=0
        row=module.linked_hatches(doc,'source.dxf')[0]
        self.assertIsNone(row['geometry'])
        self.assertIsNone(json.loads(row['notes'])['measured_area_sqm'])
        self.assertEqual(row['area_sqm'],100)

    def test_agent_area_answer_uses_linked_evidence(self):
        root=Path(__file__).resolve().parents[1]
        models=runpy.run_path(str(root/'services/masterplan/models.py'))
        record=module.linked_hatches(self.drawing(),'source.dxf')[0]
        plot=models['MasterplanPlot'](project_id='Test',**record)
        tree=ast.parse((root/'services/masterplan/agent.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_fallback_deterministic_plan')
        env={'re':re,'json':json,'db':types.SimpleNamespace(get_plots=lambda p:[plot]),'MasterplanAIQueryResponse':models['MasterplanAIQueryResponse']}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'agent','exec'),env)
        result=env['_fallback_deterministic_plan'](None,'tell me area of 5210766','Test')
        self.assertEqual(result.intent,'INSPECT_PLOT')
        self.assertIn('400.00',result.answer)
        self.assertIn('100.00',result.answer)
        self.assertIn('source.dxf',result.answer)
        self.assertIn('not been verified',result.answer)


if __name__=='__main__':unittest.main()
