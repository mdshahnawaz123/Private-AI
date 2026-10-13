"""Qualitative stage assertions must bind a source label/value, not any text."""
import unittest

from intelligence.answer_guard import publication_issues, guarded_answer


class StageMetadataTests(unittest.TestCase):
    def check(self, answer, pages, page=1):
        evidence = "\n\n====\n\n".join(
            f"[SOURCE: cover.pdf | PAGE {n}]\n{text}" for n, text in pages.items())
        sources = [{"source": "cover.pdf", "page": n} for n in pages]
        return publication_issues(answer + f" [SOURCE: cover.pdf | PAGE {page}]",
                                  evidence, sources, question="What is the design stage?")

    def test_project_name_is_not_a_design_stage(self):
        self.assertTrue(self.check("Design stage: C3085 Expo Hills - Phase 1",
                                   {1: "C3085 Expo Hills - Phase 1"}))

    def test_source_label_and_value_are_bound(self):
        self.assertTrue(self.check("Design stage: Detailed Design",
                                   {1: "Project name: Detailed Design\nDesign stage: Concept Design"}))

    def test_correct_explicit_stage(self):
        self.assertEqual(self.check("Design stage: Developed Design",
                                    {1: "Design stage: Developed Design"}), [])

    def test_native_cover_stage_without_label_is_recognized_narrowly(self):
        self.assertEqual(self.check("Design stage: Developed Design",
                                    {1: "C3085 Expo Hills - Phase 1\nDeveloped Design\nArea Schedule"}), [])

    def test_known_stage_under_project_name_is_not_stage_evidence(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "Project name: Developed Design"}))

    def test_split_other_field_cannot_establish_stage(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "Project name\nDeveloped Design"}))

    def test_another_nearby_label_does_not_override_explicit_stage(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "Project name\nDeveloped Design\nStage\nConcept Design"}))

    def test_stage_mention_in_prose_is_not_stage_authority(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "Do not use Developed Design for this issue."}))

    def test_source_value_on_other_page_cannot_support_citation(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "C3085 Expo Hills - Phase 1", 2: "Design stage: Developed Design"}))

    def test_split_label_value(self):
        self.assertEqual(self.check("The design stage is Developed Design",
                                    {1: "Design stage\nDeveloped Design"}), [])

    def test_markdown_label_variant(self):
        self.assertEqual(self.check("**Design stage:** **Developed Design**",
                                    {1: "STAGE = Developed Design"}), [])

    def test_source_qualification_must_not_be_dropped(self):
        self.assertTrue(self.check("Design stage: Developed Design",
                                   {1: "Design stage: Developed Design (subject to client confirmation)"}))

    def test_unknown_unlabelled_stage_fails_closed(self):
        self.assertTrue(self.check("Design stage: Unicorn Phase",
                                   {1: "Unicorn Phase"}))

    def test_custom_explicit_stage_is_supported(self):
        self.assertEqual(self.check("Design stage: Client Review Phase",
                                    {1: "Design stage: Client Review Phase"}), [])

    def test_conflicting_cited_stages_are_ambiguous(self):
        evidence = "[SOURCE: cover.pdf | PAGE 1]\nDesign stage: Developed Design\n\n====\n\n[SOURCE: cover.pdf | PAGE 2]\nDesign stage: Concept Design"
        answer = "Design stage: Developed Design [SOURCE: cover.pdf | PAGE 1] [SOURCE: cover.pdf | PAGE 2]"
        issues = publication_issues(answer, evidence, [{"source": "cover.pdf", "page": n} for n in (1, 2)])
        self.assertTrue(any(i.startswith("AMBIGUOUS:") for i in issues), issues)

    def test_stage_needs_citation(self):
        self.assertTrue(publication_issues("Design stage: Developed Design",
            "[SOURCE: cover.pdf | PAGE 1]\nDeveloped Design", [{"source": "cover.pdf", "page": 1}]))

    def test_incorrect_stage_is_withheld_in_final_answer(self):
        answer, issues = guarded_answer(
            "Design stage: C3085 Expo Hills - Phase 1 [SOURCE: cover.pdf | PAGE 1]",
            "[SOURCE: cover.pdf | PAGE 1]\nC3085 Expo Hills - Phase 1",
            [{"source": "cover.pdf", "page": 1}])
        self.assertTrue(issues)
        self.assertNotIn("Design stage: C3085", answer)


if __name__ == "__main__":
    unittest.main()
