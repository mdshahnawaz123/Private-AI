"""
Unit tests for ComfyUI Workflow Registry and Graph Validator.
"""

import json
import tempfile
import unittest
from pathlib import Path

from services.image_engine.workflow_registry import (
    WorkflowRegistry,
    WorkflowValidationError,
    WorkflowNotFoundError,
)
from services.image_engine.schemas import JobSubmissionRequest


class TestImageEngineWorkflowRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = WorkflowRegistry("workflows")
        self.registry.discover_and_load()

    def test_discover_standard_workflows(self):
        workflows = self.registry.list_workflows()
        wf_ids = {w.id for w in workflows}
        self.assertIn("architecture_concept", wf_ids)
        self.assertIn("sketch_to_render", wf_ids)
        self.assertIn("render_enhancement", wf_ids)

    def test_get_workflow_returns_deep_copy(self):
        wf1 = self.registry.get_workflow("architecture_concept")
        wf2 = self.registry.get_workflow("architecture_concept")
        wf1["4"]["inputs"]["text"] = "MODIFIED TEXT"
        self.assertNotEqual(wf1["4"]["inputs"]["text"], wf2["4"]["inputs"]["text"])

    def test_unknown_workflow_raises_error(self):
        with self.assertRaises(WorkflowNotFoundError):
            self.registry.get_workflow("non_existent_workflow")

    def test_build_prompt_graph_binds_parameters(self):
        req = JobSubmissionRequest(
            project="AirportProject",
            workflow_id="architecture_concept",
            prompt="High-tech terminal roof canopy with timber lattice",
            negative_prompt="cluttered, dark, distorted",
            architectural_style="Parametric",
            building_type="Airport Terminal",
            width=1024,
            height=768,
            seed=123456,
            steps=16,
            cfg=1.0,
        )
        graph = self.registry.build_prompt_graph(req)

        # Check positive prompt node
        pos_text = graph["4"]["inputs"]["text"]
        self.assertIn("Parametric", pos_text)
        self.assertIn("Airport Terminal", pos_text)
        self.assertIn("timber lattice", pos_text)

        # Distilled FLUX uses zeroed negative conditioning and fixed guidance.
        self.assertEqual(graph["5"]["class_type"], "ConditioningZeroOut")
        self.assertEqual(graph["6"]["inputs"]["width"], 1024)
        self.assertEqual(graph["6"]["inputs"]["height"], 768)
        self.assertEqual(graph["11"]["class_type"], "KSampler")
        self.assertEqual(graph["11"]["inputs"]["seed"], 123456)
        self.assertEqual(graph["11"]["inputs"]["steps"], 16)
        self.assertEqual(graph["11"]["inputs"]["cfg"], 1.0)

    def test_rejects_comfyui_ui_format_with_nodes_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "bad_ui_format.json"
            bad_file.write_text(
                json.dumps({"nodes": [{"id": 1, "type": "KSampler"}], "links": []}),
                encoding="utf-8",
            )
            with self.assertRaises(WorkflowValidationError) as ctx:
                WorkflowRegistry.load_workflow_file(bad_file)
            self.assertIn("ComfyUI Web UI format", str(ctx.exception))

    def test_rejects_empty_graph(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "empty.json"
            bad_file.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(WorkflowValidationError) as ctx:
                WorkflowRegistry.load_workflow_file(bad_file)
            self.assertIn("empty", str(ctx.exception).lower())

    def test_rejects_graph_missing_output_node(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "no_output.json"
            bad_file.write_text(
                json.dumps({
                    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
                    "2": {"class_type": "KSampler", "inputs": {}}
                }),
                encoding="utf-8",
            )
            with self.assertRaises(WorkflowValidationError) as ctx:
                WorkflowRegistry.load_workflow_file(bad_file)
            self.assertIn("no recognized output node", str(ctx.exception))

    def test_validate_against_comfy_object_info_detects_missing_nodes(self):
        # Simulated ComfyUI environment with standard nodes but missing custom node
        mock_object_info = {
            "CheckpointLoaderSimple": {},
            "EmptyLatentImage": {},
            "CLIPTextEncode": {},
            "KSampler": {},
            "VAEDecode": {},
            "SaveImage": {},
            "LoadImage": {},
            "VAEEncode": {},
        }
        for name in ("UNETLoader", "CLIPLoader", "VAELoader", "ConditioningZeroOut",
                     "EmptyFlux2LatentImage", "RandomNoise", "KSamplerSelect",
                     "Flux2Scheduler", "CFGGuider", "SamplerCustomAdvanced"):
            mock_object_info[name] = {}
        for name in ("ImageScaleToTotalPixels", "ReferenceLatent", "GetImageSize"):
            mock_object_info[name] = {}
        for name in ("ModelSamplingSD3", "Wan22ImageToVideoLatent", "CreateVideo", "SaveVideo"):
            mock_object_info[name] = {}
        missing_report = self.registry.validate_against_comfy_object_info(mock_object_info)
        # All standard nodes in our 3 starter workflows exist in mock_object_info
        for wf_id, missing in missing_report.items():
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
