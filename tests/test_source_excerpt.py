import unittest
from intelligence.source_excerpt import source_excerpt


class SourceExcerptTests(unittest.TestCase):
    sources=[{'source':'schedule.pdf','page':4}]
    evidence='[SOURCE: schedule.pdf | PAGE 4]\nRevision C. Status: Proposed.\nThe design pressure for AHU-813 is 275 Pa, subject to vendor confirmation.'

    def test_native_quote_retains_qualification_source_and_exact_tag(self):
        answer=source_excerpt('What design pressure is specified for AHU-813?',self.evidence,self.sources)
        self.assertIn('275 Pa, subject to vendor confirmation.',answer)
        self.assertIn('PROPOSED',answer)
        self.assertIn('[SOURCE: schedule.pdf | PAGE 4]',answer)

    def test_wrong_entity_property_or_approval_is_not_answered(self):
        for q in ('What pressure for AHU-814?','What voltage for AHU-813?',
                  'Is AHU-813 approved at 275 Pa?','Convert AHU-813 pressure to psi'):
            self.assertIsNone(source_excerpt(q,self.evidence,self.sources))

    def test_conflicting_values_never_selected(self):
        self.assertIsNone(source_excerpt('What pressure for AHU-813?',self.evidence+'\nAHU-813 pressure is 400 Pa.',self.sources))

    def test_vision_and_foreign_pages_cannot_be_quoted_as_native(self):
        for context,sources in ((self.evidence.replace('Revision C.','[UNVERIFIED OCR]\nRevision C.'),self.sources),
                                (self.evidence,[{'source':'other.pdf','page':4}])):
            self.assertIsNone(source_excerpt('What pressure for AHU-813?',context,sources))

    def test_native_pdf_table_row_is_returned_for_a_specific_question(self):
        evidence='''[SOURCE: schedule.pdf | PAGE 4]
PARKING CALCULATION
| ITEM | NO. | REQUIRED | PROPOSED |
| --- | --- | --- | --- |
| Units less than 150 sqm | 8 | 8 | 9 |
| Tandem | | 2 | 1 |
| TOTAL | | 10 | 10 |'''
        answer=source_excerpt('How many Tandem parking spaces are required?',evidence,self.sources)
        self.assertIsNotNone(answer)
        self.assertIn('ITEM: Tandem',answer)
        self.assertIn('REQUIRED: 2',answer)
        self.assertIn('[SOURCE: schedule.pdf | PAGE 4]',answer)

    def test_named_table_request_returns_all_rows_from_one_source_page(self):
        evidence='''[SOURCE: schedule.pdf | PAGE 4]
PARKING CALCULATION
| ITEM | NO. | REQUIRED | PROPOSED |
| --- | --- | --- | --- |
| Units less than 150 sqm | 8 | 8 | 9 |
| Tandem | | 2 | 1 |
| TOTAL | | 10 | 10 |'''
        answer=source_excerpt('Show the full PARKING CALCULATION table',evidence,self.sources)
        self.assertIsNotNone(answer)
        self.assertIn('ITEM: Units less than 150 sqm',answer)
        self.assertIn('ITEM: Tandem',answer)
        self.assertIn('ITEM: TOTAL',answer)
        self.assertEqual(answer.count('[SOURCE: schedule.pdf | PAGE 4]'),3)

    def test_table_row_cannot_be_matched_to_an_unsupported_identifier(self):
        evidence='''[SOURCE: schedule.pdf | PAGE 4]
PARKING CALCULATION
| ITEM | REQUIRED |
| --- | --- |
| AHU-813 | 2 |'''
        self.assertIsNone(source_excerpt('What is the required value for AHU-814?',evidence,self.sources))

    def test_review_required_visual_table_evidence_is_not_quoted(self):
        evidence='''[SOURCE: schedule.pdf | PAGE 4]
[UNVERIFIED OCR]
PARKING CALCULATION
| ITEM | REQUIRED |
| --- | --- |
| Tandem | 2 |'''
        self.assertIsNone(source_excerpt('What is the Tandem parking required?',evidence,self.sources))

    def test_clipped_page_cannot_be_used_for_a_complete_table_request(self):
        evidence='''[SOURCE: schedule.pdf | PAGE 4]
PARKING CALCULATION
| ITEM | REQUIRED |
| --- | --- |
| Tandem | 2 |
[EXCERPT ENDS; REST OF THIS PAGE NOT INCLUDED]'''
        self.assertIsNone(source_excerpt('Show the full PARKING CALCULATION table',evidence,self.sources))

    def test_native_pdf_prose_fact_is_quoted_with_its_page(self):
        evidence='[SOURCE: project.pdf | PAGE 1]\nProject Name: Expo Valley Views.'
        sources=[{'source':'project.pdf','page':1}]
        answer=source_excerpt('What is the project name?',evidence,sources)
        self.assertIn('Project Name: Expo Valley Views.',answer)
        self.assertIn('[SOURCE: project.pdf | PAGE 1]',answer)

    def test_ambiguous_equal_text_matches_are_withheld(self):
        evidence='''[SOURCE: project.pdf | PAGE 1]
Project Name: Expo Valley Views.
[SOURCE: project.pdf | PAGE 2]
Project Name: Expo Valley Residences.'''
        sources=[{'source':'project.pdf','page':1},{'source':'project.pdf','page':2}]
        self.assertIsNone(source_excerpt('What is the project name?',evidence,sources))

    def test_native_prose_from_review_required_extraction_is_not_quoted(self):
        evidence='''[SOURCE: project.pdf | PAGE 1]
[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]
Project Name: Expo Valley Views.'''
        self.assertIsNone(source_excerpt('What is the project name?',evidence,self.sources))
