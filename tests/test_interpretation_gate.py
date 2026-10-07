import unittest
from intelligence.answer_guard import publication_issues

class InterpretationGateTests(unittest.TestCase):
    def test_focused_page_context_marks_legacy_plain_vision_unverified(self):
        import tempfile,json
        from pathlib import Path
        from intelligence.page_context import select_page_context
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'source.pdf')
            Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':1,'text':'Native pressure 6 bar','vision':'Guess 9 bar'}]}))
            sources,evidence=select_page_context(path,'source.pdf','pressure page 1')
            self.assertIn('[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]',evidence)
            self.assertTrue(publication_issues('Pressure 9 bar. [SOURCE: source.pdf | PAGE 1]',evidence,sources))
            self.assertEqual(publication_issues('Pressure 6 bar. [SOURCE: source.pdf | PAGE 1]',evidence,sources),[])

    def test_conditional_approval_cannot_be_promoted_to_unconditional(self):
        from intelligence.source_semantics import explicit_states,supports_authority
        states=explicit_states('Approval status: Approved With Comments')
        self.assertEqual(states,{'APPROVED_WITH_COMMENTS'})
        self.assertFalse(supports_authority(states,'APPROVED'))
        sources=[{'source':'synthetic.pdf','page':1}]
        evidence='[SOURCE: synthetic.pdf | PAGE 1]\nApproval status: Approved With Comments'
        self.assertTrue(publication_issues('Approved. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources))
        self.assertEqual(publication_issues('Approved With Comments. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources),[])

    def test_generic_approved_column_does_not_establish_authority(self):
        evidence='[SOURCE: synthetic.pdf | PAGE 1]\nApproved | Seal Date\nInitially proposed pressure 6 bar'
        self.assertTrue(publication_issues('The design is approved. [SOURCE: synthetic.pdf | PAGE 1]',evidence,[{'source':'synthetic.pdf','page':1}]))
    def test_visual_only_value_and_identifier_cannot_support_claim(self):
        sources=[{'source':'synthetic.pdf','page':1}]
        evidence='[SOURCE: synthetic.pdf | PAGE 1]\n[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]\nSYNTH-060 pressure 6 bar'
        issues=publication_issues('SYNTH-060 pressure is 6 bar. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources)
        self.assertIn('Numeric values absent from cited page excerpts',issues)
        self.assertIn('Identifier absent from cited page excerpts',issues)

    def test_native_value_before_legacy_visual_section_remains_supported(self):
        sources=[{'source':'synthetic.pdf','page':1}]
        evidence='[SOURCE: synthetic.pdf | PAGE 1]\nNative pressure 6 bar\n[DRAWING/VISION]\nGuess 9 bar'
        self.assertEqual(publication_issues('Pressure 6 bar. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources),[])
        self.assertTrue(publication_issues('Pressure 9 bar. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources))

    def test_same_page_native_excerpt_does_not_validate_different_visual_value(self):
        sources=[{'source':'synthetic.pdf','page':1}]
        evidence='[SOURCE: synthetic.pdf | PAGE 1]\nNative pressure 6 bar\n[SOURCE: synthetic.pdf | PAGE 1]\n[UNVERIFIED VISUAL EXTRACTION]\n9 bar'
        self.assertTrue(publication_issues('Pressure 9 bar. [SOURCE: synthetic.pdf | PAGE 1]',evidence,sources))
