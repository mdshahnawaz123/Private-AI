import unittest,json
from pathlib import Path
from services.image_engine.workflow_registry import WorkflowRegistry
class StudioReadinessRegression(unittest.TestCase):
 def registry(self):
  r=WorkflowRegistry(workflows_dir='workflows');r.discover_and_load();return r
 def info(self,r):
  result={}
  for graph in r._raw_workflows.values():
   for node in graph.values():
    spec=result.setdefault(node['class_type'],{'input':{'required':{}}})
    for k,v in node['inputs'].items():
     if k.endswith('_name'):
      req = spec['input']['required'].setdefault(k, [[]])
      if v not in req[0]: req[0].append(v)
  return result
 def test_installed_models_publishable(self):
  r=self.registry();self.assertEqual(r.validate_against_comfy_object_info(self.info(r), validate_models=True),{})
 def test_missing_checkpoint_unavailable(self):
  r=self.registry();info=self.info(r);info['UNETLoader']['input']['required']['unet_name']=[[]]
  self.assertIn('architecture_concept',r.validate_against_comfy_object_info(info, validate_models=True))
 def test_missing_node_unavailable(self):
  r=self.registry();info=self.info(r);del info['SamplerCustomAdvanced'];self.assertIn('architecture_concept',r.validate_against_comfy_object_info(info, validate_models=True))
 def test_frontend_uses_api_fields(self):
  s=Path('ui/app.js').read_text(encoding='utf-8');self.assertNotIn('_studioActiveJob.id',s);self.assertNotIn('comfy_online',s);self.assertIn('_studioActiveJob.progress_percent',s);self.assertIn('updated.error',s)
 def test_preflight_precedes_database_insert(self):
  s=Path('services/image_engine/job_service.py').read_text();a=s.index('async def submit_job');b=s.index('def get_job_status',a);s=s[a:b];self.assertLess(s.index('check_health'),s.index('db.create_image_job'));self.assertLess(s.index('get_object_info'),s.index('db.create_image_job'))
if __name__=='__main__':unittest.main()
