import unittest
from intelligence.answer_guard import publication_issues,guarded_answer,guarded_answer_with_repair


class AnswerGuardTests(unittest.TestCase):
    def test_repair_is_single_and_checked_before_publication(self):
        from unittest.mock import Mock
        repair=Mock(return_value='2054 sqm [SOURCE: a.pdf | PAGE 6]')
        answer,issues=guarded_answer_with_repair('9999 sqm',self.evidence,self.sources,repair)
        self.assertEqual(issues,[])
        self.assertIn('2054',answer)
        repair.assert_called_once()
        repair.reset_mock()
        repair.return_value='9999 sqm [SOURCE: a.pdf | PAGE 6]'
        answer,issues=guarded_answer_with_repair('9999 sqm',self.evidence,self.sources,repair)
        self.assertTrue(issues)
        self.assertNotIn('9999',answer)
        repair.assert_called_once()

    def test_repair_failure_preserves_refusal_and_valid_answer_skips_repair(self):
        from unittest.mock import Mock
        repair=Mock(side_effect=RuntimeError('offline'))
        answer,issues=guarded_answer_with_repair('9999 sqm',self.evidence,self.sources,repair)
        self.assertTrue(issues)
        self.assertNotIn('9999',answer)
        repair.reset_mock()
        answer,issues=guarded_answer_with_repair('Not stated.',self.evidence,self.sources,repair)
        self.assertEqual(issues,[])
        repair.assert_not_called()
    evidence='[SOURCE: a.pdf | PAGE 6]\nTower 7 GFA 2054 sqm.\n[SOURCE: a.pdf | PAGE 8]\nGFA 3229 sqm.'
    sources=[{'source':'a.pdf','page':6},{'source':'a.pdf','page':8}]
    def test_valid_and_wrong_page_values(self):
        self.assertEqual(publication_issues('2054 sqm [SOURCE: a.pdf | PAGE 6]',self.evidence,self.sources),[])
        self.assertTrue(publication_issues('3229 sqm [SOURCE: a.pdf | PAGE 6]',self.evidence,self.sources))

    def test_invention_and_foreign_citations_withheld(self):
        for answer in ('9999 sqm [SOURCE: a.pdf | PAGE 6]','2054 sqm [SOURCE: secret.pdf | PAGE 6]','2054 sqm'):
            replacement,issues=guarded_answer(answer,self.evidence,self.sources)
            self.assertTrue(issues)
            self.assertNotEqual(replacement,answer)

    def test_not_found_and_list_indices_not_numeric_claims(self):
        self.assertEqual(publication_issues('1. This value is not stated.',self.evidence,self.sources),[])

    def test_known_numeric_filename_is_not_a_quantity(self):
        filename='C3085-SCH-3EH6105-AR-0000001(5).pdf'
        sources=[{'source':filename,'page':1}]
        answer='The contract value and lender are not stated in '+filename+'.'
        self.assertEqual(publication_issues(answer,'[SOURCE: '+filename+' | PAGE 1] Area schedule',sources),[])
        self.assertEqual(publication_issues(answer.replace('.pdf',''),'[SOURCE: '+filename+' | PAGE 1] Area schedule',sources),[])
        self.assertTrue(publication_issues(answer+' The value is 1234.', '',sources))

if __name__=='__main__':unittest.main()
