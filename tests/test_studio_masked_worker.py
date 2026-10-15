import io
import json
import unittest
from pathlib import Path
from PIL import Image
import test_image_engine_job_service as fixtures
from services.image_engine.schemas import JobSubmissionRequest


class MaskedWorkerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.TestJobService.asyncSetUp
    asyncTearDown = fixtures.TestJobService.asyncTearDown

    def request(self):
        source = self.storage.save_input_image(self.project_name, 'reference', self.sample_png_bytes, 'source.png')
        mask = Image.new('L', (128,128), 0)
        mask.paste(255, (20,20,60,60))
        buf = io.BytesIO(); mask.save(buf, 'PNG')
        path = self.storage.save_input_image(self.project_name, 'mask', buf.getvalue(), 'mask.png')
        self.mock_client.upload_image.return_value = {'name':'source.png'}
        generated = io.BytesIO(); Image.new('RGB',(128,128),'red').save(generated,'PNG')
        self.mock_client.get_image_bytes.return_value = generated.getvalue()
        return JobSubmissionRequest(project=self.project_name, workflow_id='render_enhancement', prompt='Redesign only screen', input_image_path=str(source), edit_mask_path=str(path), steps=20, cfg=5)

    async def test_worker_publishes_composite_and_provenance(self):
        request = self.request()
        await self.job_service.start()
        status = await self.job_service.submit_job(request, user_id=1)
        await self.job_service._queue.join()
        final = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final.status, 'completed', final.error)
        output = final.outputs[0]
        path = Path(self.temp_dir)/output.file_path
        with Image.open(path) as image:
            self.assertEqual(image.getpixel((0,0)), (100,150,200,255))
            self.assertEqual(image.getpixel((30,30)), (255,0,0,255))
        metadata = json.loads(Path(str(path)+'.meta.json').read_text())
        self.assertIn('binary_mask_output_composite', json.dumps(metadata))

    async def test_worker_withholds_wrong_framing(self):
        request = self.request()
        wrong = io.BytesIO(); Image.new('RGB',(128,64),'red').save(wrong,'PNG')
        self.mock_client.get_image_bytes.return_value = wrong.getvalue()
        await self.job_service.start()
        status = await self.job_service.submit_job(request, user_id=1)
        await self.job_service._queue.join()
        final = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final.status, 'failed')
        self.assertEqual(final.outputs, [])
        self.assertIn('framing', final.error)

    async def test_cross_project_mask_rejected_before_renderer(self):
        request = self.request()
        other = self.storage.save_input_image('Other', 'mask', self.sample_png_bytes, 'mask.png')
        request.edit_mask_path = str(other)
        with self.assertRaisesRegex(ValueError, 'selected project'):
            await self.job_service.submit_job(request, user_id=1)
        self.mock_client.check_health.assert_not_called()
