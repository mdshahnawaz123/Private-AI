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
