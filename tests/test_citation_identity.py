import unittest
from intelligence.citation_identity import prepare_citations, resolve_citations
from intelligence.answer_guard import guarded_answer


class CitationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.context='[SOURCE: spec(4).pdf | PAGE 2]\nAHU-813 design pressure 275 Pa.\n[SOURCE: other.pdf | PAGE 7]\nAHU-922 design pressure 400 Pa.'
        self.sources=[{'source':'spec(4).pdf','page':2},{'source':'other.pdf','page':7}]
        self.model,self.ids=prepare_citations(self.context,self.sources)

    def test_exact_identity_roundtrip_and_claim_validation(self):
        answer=resolve_citations('AHU-813: 275 Pa [SOURCE: EVIDENCE_1 | PAGE 2]',self.ids)
        self.assertIn('[SOURCE: spec(4).pdf | PAGE 2]',answer)
        self.assertEqual(guarded_answer(answer,self.context,self.sources)[1],[])

    def test_handles_never_repair_wrong_page_value_unit_or_entity(self):
        for text in ('AHU-813: 275 Pa [SOURCE: EVIDENCE_1 | PAGE 7]',
                     'AHU-813: 400 Pa [SOURCE: EVIDENCE_1 | PAGE 2]',
                     'AHU-813: 275 psi [SOURCE: EVIDENCE_1 | PAGE 2]',
                     'AHU-814: 275 Pa [SOURCE: EVIDENCE_1 | PAGE 2]',
                     'AHU-813: 275 Pa [SOURCE: PROJECT-X | PAGE 2]'):
            with self.subTest(text=text):
                self.assertTrue(guarded_answer(resolve_citations(text,self.ids),self.context,self.sources)[1])

    def test_request_local_allowlist_and_duplicate_pages(self):
        model,ids=prepare_citations(self.context+'\n'+self.context,self.sources[:1])
        self.assertEqual(len(ids),1)
        self.assertIn('[SOURCE: other.pdf | PAGE 7]',model)
        self.assertEqual(model.count('[SOURCE: EVIDENCE_1 | PAGE 2]'),2)
        self.assertEqual(resolve_citations('no citation',ids),'no citation')

    def test_unverified_observations_cannot_support_handles(self):
        context='[SOURCE: a.pdf | PAGE 1]\n[UNVERIFIED VISION]\nAHU-813: 275 Pa'
        sources=[{'source':'a.pdf','page':1}]
        _,ids=prepare_citations(context,sources)
        answer=resolve_citations('AHU-813: 275 Pa [SOURCE: EVIDENCE_1 | PAGE 1]',ids)
        self.assertTrue(guarded_answer(answer,context,sources)[1])

    def test_observed_citation_prefix_normalizes_only_assigned_exact_page(self):
        answer=resolve_citations('AHU-813: 275 Pa [Citation: SOURCE: EVIDENCE_1 | PAGE 2]',self.ids)
        self.assertEqual(guarded_answer(answer,self.context,self.sources)[1],[])
        for marker in ('[Citation: SOURCE: EVIDENCE_1 | PAGE 99]', '[Citation: SOURCE: EVIDENCE_99 | PAGE 2]'):
            self.assertEqual(resolve_citations(marker,self.ids),marker)

    def test_native_disposition_retained_even_when_model_omits_it(self):
        from intelligence.citation_identity import append_source_qualifications
        evidence='[SOURCE: a.pdf | PAGE 3]\nRevision B. Status: TBC.\nHeight 8 m.'
        answer=append_source_qualifications('Height 8 m [SOURCE: a.pdf | PAGE 3]',evidence,[{'source':'a.pdf','page':3}])
        self.assertIn('Revision B; status TBC',answer)
        self.assertNotIn('TBC',append_source_qualifications('Not found',evidence,[{'source':'a.pdf','page':3}]))

    def test_review_word_is_not_a_revision(self):
        from intelligence.source_semantics import native_revision
        self.assertEqual(native_revision({'pages':[{'text':'Revision C. Status: Draft. Independent engineering review required.'}]}),'C')
        self.assertIsNone(native_revision({'pages':[{'text':'Independent review required.'}]}))
        result=resolve_citations('[Citation: [SOURCE: EVIDENCE_1 | PAGE 2]]',self.ids)
        self.assertEqual(result,'[SOURCE: spec(4).pdf | PAGE 2]')
