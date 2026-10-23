import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from intelligence.answer_guard import guarded_answer
from services.pdf_service import PdfService


class MarkupGroundingTests(unittest.TestCase):
    markups = [{'id':'mk_101','page':2,'status':'Pending','text':'Verify transfer slab reinforcement.'},
               {'id':'mk_102','page':3,'status':'Accepted','text':'Clearance checked.'}]

    def run_model(self, text=None, error=None):
        with patch('local_chat.LocalChatOllama') as model:
            if error:
                model.return_value.stream.side_effect = error
            else:
                model.return_value.stream.return_value = [SimpleNamespace(content=text)]
            return PdfService.summarize_markups_ai(self.markups,'test.pdf')

    def test_model_cannot_invent_facts_deadlines_or_counts(self):
        result = self.run_model(json.dumps({'executive_summary':'Submit within 5 business days.',
            'total_count':999, 'action_items':['Cut the slab.'],
            'classifications':[{'index':1,'discipline':'Structural'}]}))
        self.assertEqual(result['total_count'],2)
        self.assertEqual(result['open_issues_count'],1)
        self.assertEqual(result['facts'][0]['text'],self.markups[0]['text'])
        self.assertEqual(result['facts'][0]['citation']['page'],2)
        self.assertEqual(result['by_discipline']['Structural'][0]['markup_id'],'mk_101')
        self.assertNotIn('business days',json.dumps(result))
        self.assertNotIn('Cut the slab',json.dumps(result))

    def test_malformed_or_unavailable_model_never_publishes_raw_text(self):
        for text, error in [('Deadline: tomorrow!',None),(None,RuntimeError('offline'))]:
            result=self.run_model(text,error)
            self.assertEqual(len(result['facts']),2)
            self.assertNotIn('tomorrow',json.dumps(result))
            self.assertEqual(result['classification_basis'],'Unclassified input records')

    def test_only_known_disciplines_and_valid_indices_are_accepted(self):
        result=self.run_model(json.dumps({'classifications':[{'index':1,'discipline':'<script>'},
            {'index':True,'discipline':'MEP'},{'index':100,'discipline':'Structural'}]}))
        self.assertEqual(set(result['by_discipline']),{'General'})

    def test_source_deadline_is_preserved_as_a_quoted_fact(self):
        with patch('local_chat.LocalChatOllama') as model:
            model.return_value.stream.side_effect=RuntimeError('offline')
            result=PdfService.summarize_markups_ai([{'id':'d','page':1,'text':'Respond within 5 business days.'}])
        self.assertEqual(result['facts'][0]['text'],'Respond within 5 business days.')

    def test_broad_question_cannot_publish_a_failed_candidate(self):
        candidate='The report design pressure is 999 Pa. [SOURCE: test.pdf | PAGE 1]'
        answer, issues=guarded_answer(candidate,'[SOURCE: test.pdf | PAGE 1]\nDesign pressure is 275 Pa.',
                                     [{'source':'test.pdf','page':1}],question='Summarize this report.')
        self.assertTrue(issues)
        self.assertNotIn('999',answer)

    def test_unit_superscripts_and_hyphenated_test_age_are_equivalent(self):
        from intelligence.answer_guard import _normalize_unit, publication_issues
        self.assertEqual(_normalize_unit('N/mm²'),_normalize_unit('N/mm2'))
        self.assertEqual(_normalize_unit('kg/m³'),_normalize_unit('kg/m3'))
        evidence='[SOURCE: test.pdf | PAGE 1]\nConcrete compressive strength at 28-day is 40 N/mm2.'
        issues=publication_issues('Concrete compressive strength at 28 days is 40 N/mm². [SOURCE: test.pdf | PAGE 1]',
                                 evidence,[{'source':'test.pdf','page':1}])
        self.assertNotIn('Deadline or duration absent from cited page excerpts',issues)
        self.assertNotIn('Value/unit pair absent from cited page excerpts',issues)

    def test_list_introduction_is_not_a_fact_but_each_value_is_checked(self):
        from intelligence.answer_guard import publication_issues
        evidence='[SOURCE: test.pdf | PAGE 2]\nFoundation: 40 N/mm2 (50 N/mm2).\nBlinding: 16 N/mm2 (20 N/mm2).'
        answer='Based on the attached document **test.pdf**, here are the foundation and blinding strengths exactly as written on page 2:\n\n**Foundation:** 40 N/mm² (50 N/mm²) [SOURCE: test.pdf | PAGE 2]\n\n**Blinding:** 16 N/mm² (20 N/mm²) [SOURCE: test.pdf | PAGE 2]'
        self.assertEqual(publication_issues(answer,evidence,[{'source':'test.pdf','page':2}]),[])
        self.assertTrue(publication_issues(answer.replace('40 N/mm²','400 N/mm²'),evidence,[{'source':'test.pdf','page':2}]))
        wrapped=answer.replace('**Foundation:** 40','**Foundation:**\n- **40').replace('**Blinding:** 16','**Blinding:**\n- **16')
        self.assertEqual(publication_issues(wrapped,evidence,[{'source':'test.pdf','page':2}]),[])
