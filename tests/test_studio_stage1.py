import ast
import asyncio
import copy
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from PIL import Image
from fastapi import HTTPException
from services.image_engine.workflow_registry import WorkflowRegistry
from services.image_engine.schemas import JobSubmissionRequest, JobStatus
from services.image_engine.comfyui_client import ComfyUIClient
from services.image_engine.image_storage import ImageStorage, StorageSecurityError
from services.image_engine.job_service import JobService

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = WorkflowRegistry('workflows')
        self.registry.discover_and_load()
    def request(self, **kw):
        args = dict(project='Owned', workflow_id='render_enhancement', prompt='Change only the stone finish.', input_image_path='reference.png', steps=16, cfg=1, seed=123)
        args.update(kw)
        return JobSubmissionRequest(**args)
    def test_edit_dimensions_keep_source_links(self):
        for width,height in [(512,1024),(1024,512),(1024,768)]:
            with self.subTest(size=(width,height)):
                raw=self.registry.get_workflow('render_enhancement')
                g=self.registry.build_prompt_graph(self.request(width=width,height=height))
                self.assertEqual(g['75:66']['inputs']['width'],raw['75:66']['inputs']['width'])
                self.assertEqual(g['75:66']['inputs']['height'],raw['75:66']['inputs']['height'])
                self.assertEqual(g['75:64']['inputs']['latent_image'],raw['75:64']['inputs']['latent_image'])
    def test_positive_and_negative_constraints_survive(self):
        raw=self.registry.get_workflow('render_enhancement')
        g=self.registry.build_prompt_graph(self.request(negative_prompt='No new balconies'))
        self.assertIn(raw['75:74']['inputs']['text'],g['75:74']['inputs']['text'])
        self.assertIn('Change only the stone finish.',g['75:74']['inputs']['text'])
        self.assertIn(raw['75:67']['inputs']['text'],g['75:67']['inputs']['text'])
        self.assertIn('No new balconies',g['75:67']['inputs']['text'])
    def test_prompt_roles_do_not_depend_on_dictionary_order(self):
        raw=self.registry.get_workflow('render_enhancement');shuffled=dict(reversed(list(raw.items())))
        with patch.object(self.registry,'get_workflow',return_value=copy.deepcopy(shuffled)):
            g=self.registry.build_prompt_graph(self.request(negative_prompt='No balconies'))
        self.assertIn('Requested edit:',g['75:74']['inputs']['text'])
        self.assertNotIn('Requested edit:',g['75:67']['inputs']['text'])
    def test_reference_and_seed_mapping(self):
        g=self.registry.build_prompt_graph(self.request())
        self.assertEqual(g['75:64']['inputs']['seed'],123)
        self.assertEqual(g['76']['inputs']['image'],'reference.png')
        self.assertEqual(g['75:79:77']['inputs']['latent'],['75:79:78',0])
        self.assertEqual(g['75:79:78']['inputs']['pixels'],['75:80',0])
    def test_unsafe_overrides_rejected(self):
        with self.assertRaises(ValueError):self.registry.build_prompt_graph(self.request(extra_params={'76':{'image':'other-project.png'}}))
    def test_text_only_dimensions_and_defaults(self):
        g=self.registry.build_prompt_graph(JobSubmissionRequest(project='Owned',workflow_id='architecture_concept',prompt='Villa',width=512,height=768,seed=99,steps=16,cfg=1))
        self.assertEqual(g['6']['inputs']['width'],512)
        self.assertEqual(g['6']['inputs']['height'],768)
        self.assertEqual(g['11']['inputs']['seed'],99)

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.storage=ImageStorage(data_dir=self.tmp.name)
        b=io.BytesIO();Image.new('RGB',(40,20)).save(b,format='PNG');self.image=b.getvalue()
    def tearDown(self):self.tmp.cleanup()
    def test_owned_reference_validated(self):
        p=self.storage.save_input_image('Owned','input-test',self.image,'ref.png')
        self.assertEqual(self.storage.validate_input_image('Owned',str(p)),str(p.resolve()))
    def test_cross_project_and_traversal_rejected(self):
        p=self.storage.save_input_image('Other','input-test',self.image,'ref.png')
        for name in ['Owned','../../outside']:
            with self.subTest(project=name),self.assertRaises(StorageSecurityError):self.storage.validate_input_image(name,str(p))
    def test_nonimage_rejected(self):
        p=Path(self.tmp.name)/'projects/Owned/generated_images/input/file.png';p.parent.mkdir(parents=True);p.write_bytes(b'not image')
        with self.assertRaises(Exception):self.storage.validate_input_image('Owned',str(p))
    def test_exif_normalized(self):
        im=Image.new('RGB',(40,20));exif=im.getexif();exif[274]=6;b=io.BytesIO();im.save(b,format='JPEG',exif=exif)
        p=self.storage.save_input_image('Owned','input-test',b.getvalue(),'ref.jpg')
        self.storage.validate_input_image('Owned',str(p))
        with Image.open(p) as result:self.assertEqual(result.size,(20,40))

class SubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry=WorkflowRegistry('workflows');self.registry.discover_and_load()
        self.client=AsyncMock();self.client.check_health.return_value=types.SimpleNamespace(available=True)
        self.client.get_object_info.return_value={}
        self.storage=MagicMock();self.storage.validate_input_image.side_effect=lambda project,path:path
        self.service=JobService(self.client,self.registry,self.storage)
        self.session=patch('db.SessionLocal');self.mock_session=self.session.start();self.mock_session.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.return_value=types.SimpleNamespace(id=1)
        self.create=patch('db.create_image_job');self.created=self.create.start()
        self.audit=patch('db.audit');self.audit.start()
        self.validation=patch.object(self.registry,'validate_against_comfy_object_info',return_value={});self.validation.start()
        self.status=patch.object(self.service,'get_job_status',return_value=JobStatus(job_id='test',project='Owned',workflow_id='architecture_concept',status='queued'));self.status.start()
    async def asyncTearDown(self):
        for p in [self.status,self.validation,self.audit,self.create,self.session]:p.stop()
    async def test_effective_seed_and_metadata_defaults_persist(self):
        req=JobSubmissionRequest(project='Owned',workflow_id='architecture_concept',prompt='Villa')
        await self.service.submit_job(req,1)
        params=self.created.call_args.kwargs['input_params'];self.assertIsInstance(params['seed'],int);self.assertEqual(params['steps'],16);self.assertEqual(params['cfg'],1)
    async def test_reference_required_before_enqueue(self):
        with self.assertRaises(ValueError):await self.service.submit_job(JobSubmissionRequest(project='Owned',workflow_id='render_enhancement',prompt='Stone'),1)
        self.created.assert_not_called();self.client.check_health.assert_not_awaited()
    async def test_reference_reasoning_rejected_before_enqueue(self):
        with self.assertRaises(ValueError):await self.service.submit_job(JobSubmissionRequest(project='Owned',workflow_id='render_enhancement',prompt='Stone',input_image_path='ref.png',enhance_prompt=True),1)
        self.created.assert_not_called()
    async def test_unsupported_negative_prompt_rejected(self):
        req=JobSubmissionRequest(project='Owned',workflow_id='architecture_concept',prompt='Villa',negative_prompt='Bad geometry')
        with self.assertRaises(ValueError):await self.service.submit_job(req,1)
        self.created.assert_not_called()
    async def test_ineffective_denoise_rejected(self):
        req=JobSubmissionRequest(project='Owned',workflow_id='render_enhancement',prompt='Stone',input_image_path='ref.png',denoise=.2)
        with self.assertRaises(ValueError):await self.service.submit_job(req,1)
        self.created.assert_not_called()
    async def test_wrong_project_reference_rejected_before_network(self):
        self.storage.validate_input_image.side_effect=StorageSecurityError('Other project')
        req=JobSubmissionRequest(project='Owned',workflow_id='render_enhancement',prompt='Stone',input_image_path='Other/ref.png')
        with self.assertRaises(ValueError):await self.service.submit_job(req,1)
        self.created.assert_not_called();self.client.check_health.assert_not_awaited()
    async def test_settings_outside_workflow_rejected(self):
        with self.assertRaises(ValueError):await self.service.submit_job(JobSubmissionRequest(project='Owned',workflow_id='architecture_concept',prompt='Villa',steps=30,cfg=5),1)
        self.created.assert_not_called()

class BoundaryTests(unittest.TestCase):
    def test_urls(self):
        for u in ['http://127.0.0.1:8188','http://localhost:11434','http://[::1]:8188']:
            self.assertTrue(ComfyUIClient._validate_and_normalize_url(u))
        for u in ['https://remote.example','http://127.0.0.1@remote.example','http://user:password@localhost:8188','http://localhost:8188/proxy','http://localhost:8188?target=remote','ftp://localhost']:
            with self.subTest(url=u),self.assertRaises(ValueError):ComfyUIClient._validate_and_normalize_url(u)
    def test_legacy_cloud_route_rejects_before_network(self):
        tree=ast.parse(Path('main.py').read_text(encoding='utf-8'));f=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='ai_render_viewport');f.decorator_list=[]
        ns={'auth':types.SimpleNamespace(require_user=MagicMock()),'HTTPException':HTTPException,'Request':object}
        exec(compile(ast.Module(body=[f],type_ignores=[]),'legacy','exec'),ns)
        with self.assertRaises(HTTPException) as caught:asyncio.run(ns['ai_render_viewport'](object()))
        self.assertEqual(caught.exception.status_code,503);ns['auth'].require_user.assert_called_once()
    def test_lifecycle_requires_admin_before_side_effect(self):
        tree=ast.parse(Path('services/image_engine/api.py').read_text())
        for name in ['start_image_engine_service','stop_image_engine_service']:
            f=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name);f.decorator_list=[]
            deny=MagicMock(side_effect=HTTPException(403,'Denied'));ns={'auth':types.SimpleNamespace(require_roles=deny),'Request':object}
            exec(compile(ast.Module(body=[f],type_ignores=[]),'lifecycle','exec'),ns)
            with self.assertRaises(HTTPException):asyncio.run(ns[name](object()))
            self.assertEqual(deny.call_args.args[1],'admin')
    def test_reasoner_remote_url_rejected_before_http(self):
        from services.image_engine import prompt_reasoner as reasoner
        with patch.object(reasoner,'OLLAMA_URL','http://remote.example'),patch.object(reasoner.httpx,'AsyncClient') as client:
            with self.assertRaises(ValueError):asyncio.run(reasoner.enhance_architectural_prompt('Villa'))
            client.assert_not_called()
    def test_workflow_jsons_unchanged(self):
        import hashlib
        manifest=json.loads(Path('tests/fixtures/image_workflow_sha256.json').read_text(encoding='utf-8'))['files']
        for name in ['architecture_concept','render_enhancement','sketch_to_render']:
            path='workflows/'+name+'.json'
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),manifest[path])
    def test_stop_does_not_kill_arbitrary_port_owner(self):
        from services.image_engine import service_manager as manager
        with patch.object(manager,'_owned_process',None),patch.object(manager,'is_engine_reachable',return_value=True),patch.object(manager.subprocess,'run') as run:
            self.assertEqual(manager.stop_engine()['status'],'unmanaged');run.assert_not_called()
    def test_owned_stop(self):
        from services.image_engine import service_manager as manager
        proc=MagicMock();proc.poll.return_value=None
        with patch.object(manager,'_owned_process',proc):
            self.assertEqual(manager.stop_engine()['status'],'offline');proc.terminate.assert_called_once();proc.wait.assert_called_once()

if __name__=='__main__':unittest.main()
