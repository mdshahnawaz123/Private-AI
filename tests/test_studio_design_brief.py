import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from pydantic import ValidationError
from services.image_engine.schemas import PromptEnhanceRequest, PromptEnhanceResponse
from services.image_engine.design_brief import compile_option, fallback_options, generate_design_brief


class DesignBriefTests(unittest.IsolatedAsyncioTestCase):
    def brief(self, **kw):
        return PromptEnhanceRequest(prompt='G+10 residential building. Keep the entrance.', **kw)

    async def test_three_local_options_retain_exact_requirements(self):
        brief = self.brief(mode='materials', materials='Limestone only', lighting='Source daylight', protected_elements=['entrance canopy'])
        choices = fallback_options(brief)
        response = MagicMock()
        response.json.return_value = {'message': {'content': json.dumps({'options': choices})}}
        client = AsyncMock()
        client.post.return_value = response
        with patch('services.image_engine.design_brief.httpx.AsyncClient') as transport:
            transport.return_value.__aenter__.return_value = client
            result = PromptEnhanceResponse(**await generate_design_brief(brief))
        self.assertEqual(len(result.design_options), 3)
        self.assertIsNone(result.error)
        transport.assert_called_once_with(timeout=60, trust_env=False)
        self.assertTrue(client.post.call_args.args[0].startswith('http://127.0.0.1:'))
        for option in result.design_options:
            self.assertIn(brief.prompt, option.prompt)
            self.assertIn('Limestone only', option.prompt)
            self.assertIn('Source daylight', option.prompt)
            self.assertIn('entrance canopy', option.protected_elements)
            self.assertIn('camera and perspective', option.protected_elements)

    async def test_invalid_model_response_is_explicit_preset(self):
        response = MagicMock()
        response.json.return_value = {'message': {'content': '{"options": []}'}}
        client = AsyncMock(); client.post.return_value = response
        with patch('services.image_engine.design_brief.httpx.AsyncClient') as transport:
            transport.return_value.__aenter__.return_value = client
            result = await generate_design_brief(self.brief(mode='enhancement'))
        self.assertEqual(len(result['design_options']), 3)
        self.assertIsNone(result['model'])
        self.assertIn('presets', result['error'])
        self.assertIn('not been analysed', result['reasoning'])

    async def test_external_reasoner_rejected_before_transport(self):
        with patch('services.image_engine.design_brief.prompt_reasoner.OLLAMA_URL', 'https://example.com'), patch('services.image_engine.design_brief.httpx.AsyncClient') as transport:
            with self.assertRaises(ValueError):
                await generate_design_brief(self.brief())
            transport.assert_not_called()

    def test_long_compiled_brief_rejected_without_truncation(self):
        brief = PromptEnhanceRequest(prompt='a'*4000, mode='materials')
        with self.assertRaisesRegex(ValueError, 'exceeds 4000'):
            compile_option(brief, fallback_options(brief)[0], 0)

    def test_constraint_input_bounded_and_default_backward_compatible(self):
        self.assertEqual(self.brief().mode, 'concept')
        with self.assertRaises(ValidationError):
            self.brief(protected_elements=['a'*151])

    def test_screen_redesign_changes_pattern_preserves_building(self):
        brief = self.brief(mode='creative_facade', materials='Bronze aluminium')
        options = fallback_options(brief)
        self.assertEqual(len({o['changes'] for o in options}), 3)
        for i, option in enumerate(options):
            compiled = compile_option(brief, option, i)
            self.assertIn('Bronze aluminium', compiled['prompt'])
            self.assertIn('change its pattern, perforations', compiled['prompt'])
            self.assertIn('window and door positions', compiled['prompt'])
            self.assertIn('underlying building geometry must not', compiled['prompt'])
            self.assertIn('camera and perspective', compiled['protected_elements'])
            self.assertNotIn('vary finish texture', compiled['changes'])

    def test_finish_and_quality_modes_do_not_allow_screen_redesign(self):
        for mode in ['materials', 'enhancement']:
            brief = self.brief(mode=mode)
            prompt = compile_option(brief, fallback_options(brief)[0], 0)['prompt']
            self.assertIn('screen pattern', prompt)
            self.assertIn('unchanged', prompt)

    async def test_reasoner_receives_screen_specific_scope(self):
        brief = self.brief(mode='creative_facade')
        response = MagicMock()
        response.json.return_value = {'message': {'content': json.dumps({'options': fallback_options(brief)})}}
        client = AsyncMock(); client.post.return_value = response
        with patch('services.image_engine.design_brief.httpx.AsyncClient') as transport:
            transport.return_value.__aenter__.return_value = client
            await generate_design_brief(brief)
        system = client.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('Redesign only the external facade screen', system)
        self.assertNotIn('finish/lighting variations only', system)


if __name__ == '__main__':
    unittest.main()
