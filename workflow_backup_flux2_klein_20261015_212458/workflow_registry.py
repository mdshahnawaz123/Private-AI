"""
Workflow registry and validator for the Expo Design AI Local Image Engine.

Loads, validates, and manages ComfyUI workflows in Prompt API JSON format.
Validates node graphs, binds execution parameters, and ensures node classes
and required model references conform to real ComfyUI definitions.
"""

import copy
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from loguru import logger

from services.image_engine.schemas import (
    WorkflowMetadata,
    WorkflowParameter,
    JobSubmissionRequest,
)


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition file is malformed or invalid."""
    pass


class WorkflowNotFoundError(KeyError):
    """Raised when an unknown workflow ID is requested."""
    pass


class WorkflowRegistry:
    """
    Registry for discovered and validated ComfyUI Prompt API workflows.
    """

    def __init__(self, workflows_dir: Optional[str] = None):
        self.workflows_dir = Path(workflows_dir or "workflows")
        self._raw_workflows: Dict[str, Dict[str, Any]] = {}
        self._metadata_cache: Dict[str, WorkflowMetadata] = {}

    def discover_and_load(self) -> int:
        """
        Scan workflows_dir for .json files, validate their structure, and register them.
        Returns the number of successfully loaded workflows.
        """
        self._raw_workflows.clear()
        self._metadata_cache.clear()

        if not self.workflows_dir.exists():
            logger.warning(f"Workflows directory does not exist: {self.workflows_dir.resolve()}")
            return 0

        loaded = 0
        for json_path in sorted(self.workflows_dir.glob("*.json")):
            try:
                wf_id, raw_graph, meta = self.load_workflow_file(json_path)
                self._raw_workflows[wf_id] = raw_graph
                self._metadata_cache[wf_id] = meta
                loaded += 1
                logger.info(f"Loaded valid ComfyUI workflow: {wf_id} ({meta.name})")
            except Exception as exc:
                logger.error(f"Failed to load workflow from {json_path.name}: {exc}")

        return loaded

    @classmethod
    def load_workflow_file(cls, path: Path) -> Tuple[str, Dict[str, Any], WorkflowMetadata]:
        """
        Read and strictly validate a ComfyUI workflow JSON file.
        Must conform to ComfyUI Prompt API dictionary structure.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise WorkflowValidationError(f"{path.name} must be a JSON object, got {type(data).__name__}")

        # Distinguish between ComfyUI Web UI Graph format vs API Prompt format
        if "nodes" in data and isinstance(data["nodes"], list):
            raise WorkflowValidationError(
                f"{path.name} is in ComfyUI Web UI format ('nodes' list). "
                "Must be exported in ComfyUI Prompt API format (dict of node_id -> class_type/inputs)."
            )

        # Extract optional embedded _meta block
        meta_block = data.pop("_meta", {})
        wf_id = meta_block.get("id") or path.stem

        # Validate node structure
        cls.validate_prompt_api_graph(data)

        # Inspect graph to infer or combine parameters and metadata
        meta = cls._build_metadata(wf_id, data, meta_block)
        return wf_id, data, meta

    @staticmethod
    def validate_prompt_api_graph(graph: Dict[str, Any]) -> None:
        """
        Validate that every node in the graph follows the ComfyUI Prompt API format.
        """
        if not graph:
            raise WorkflowValidationError("Workflow graph is empty")

        has_output_node = False
        output_node_types = {"SaveImage", "PreviewImage", "ImageSave", "SaveImageWebsocket"}

        for node_id, node_def in graph.items():
            if not isinstance(node_def, dict):
                raise WorkflowValidationError(
                    f"Node {node_id!r} must be an object, got {type(node_def).__name__}"
                )

            class_type = node_def.get("class_type")
            if not class_type or not isinstance(class_type, str):
                raise WorkflowValidationError(f"Node {node_id!r} is missing a valid 'class_type' string")

            inputs = node_def.get("inputs")
            if inputs is None or not isinstance(inputs, dict):
                raise WorkflowValidationError(f"Node {node_id!r} is missing an 'inputs' dictionary")

            if class_type in output_node_types:
                has_output_node = True

        if not has_output_node:
            raise WorkflowValidationError(
                "Workflow contains no recognized output node (SaveImage or PreviewImage)"
            )

    @classmethod
    def _build_metadata(
        cls, wf_id: str, graph: Dict[str, Any], meta_block: Dict[str, Any]
    ) -> WorkflowMetadata:
        """Extract metadata, required models, and parameters from workflow graph."""
        name = meta_block.get("name") or wf_id.replace("_", " ").title()
        version = meta_block.get("version", "1.0.0")
        description = meta_block.get("description", "")
        category = meta_block.get("category", "general")
        license_notes = meta_block.get("license_notes")

        # Discover required models and nodes
        required_models = set()
        required_nodes = set()
        for node in graph.values():
            c_type = node.get("class_type", "")
            required_nodes.add(c_type)
            inputs = node.get("inputs", {})
            for key in ("ckpt_name", "unet_name", "model_name"):
                if key in inputs and isinstance(inputs[key], str) and inputs[key].strip():
                    required_models.add(inputs[key])

        # Discover or use declared parameters
        declared_params = meta_block.get("parameters")
        if declared_params:
            parameters = [WorkflowParameter(**p) for p in declared_params]
        else:
            parameters = cls._infer_default_parameters(graph)

        return WorkflowMetadata(
            id=wf_id,
            name=name,
            version=version,
            description=description,
            category=category,
            required_models=sorted(list(required_models)),
            required_custom_nodes=sorted(list(required_nodes)),
            parameters=parameters,
            available=True,  # Default to available; verified against ComfyUI object_info at runtime
            license_notes=license_notes,
        )

    @classmethod
    def _infer_default_parameters(cls, graph: Dict[str, Any]) -> List[WorkflowParameter]:
        """Infer standard parameters present in the graph nodes."""
        params = []
        has_prompt = False
        has_ksampler = False
        has_latent = False
        has_load_image = False

        for node in graph.values():
            c_type = node.get("class_type", "")
            if c_type == "CLIPTextEncode":
                has_prompt = True
            elif c_type in ("KSampler", "KSamplerAdvanced"):
                has_ksampler = True
            elif c_type in ("EmptyLatentImage", "EmptyFlux2LatentImage"):
                has_latent = True
            elif c_type == "LoadImage":
                has_load_image = True

        if has_prompt:
            params.append(
                WorkflowParameter(
                    name="prompt",
                    type="string",
                    label="Design Brief / Prompt",
                    description="Architectural concept description",
                    required=True,
                )
            )
            params.append(
                WorkflowParameter(
                    name="negative_prompt",
                    type="string",
                    label="Negative Prompt",
                    description="Elements to avoid (clutter, distortions, low quality)",
                    required=False,
                    default="ugly, deformed, disfigured, low quality, blurry",
                )
            )
        if has_latent:
            params.append(
                WorkflowParameter(
                    name="width",
                    type="integer",
                    label="Width",
                    default=1024,
                    min_value=512,
                    max_value=1024,
                )
            )
            params.append(
                WorkflowParameter(
                    name="height",
                    type="integer",
                    label="Height",
                    default=1024,
                    min_value=512,
                    max_value=1024,
                )
            )
        if has_ksampler:
            params.append(
                WorkflowParameter(
                    name="seed",
                    type="integer",
                    label="Seed",
                    description="Deterministic seed for reproducible designs",
                    default=None,
                )
            )
            params.append(
                WorkflowParameter(
                    name="steps",
                    type="integer",
                    label="Sampling Steps",
                    default=20,
                    min_value=10,
                    max_value=50,
                )
            )
            params.append(
                WorkflowParameter(
                    name="cfg",
                    type="float",
                    label="CFG Scale",
                    default=7.0,
                    min_value=1.0,
                    max_value=15.0,
                )
            )
        if has_load_image:
            params.append(
                WorkflowParameter(
                    name="input_image_path",
                    type="image",
                    label="Reference Sketch / Render",
                    description="Source image for conditioning or enhancement",
                    required=True,
                )
            )
            params.append(
                WorkflowParameter(
                    name="denoise",
                    type="float",
                    label="Denoising Strength",
                    description="Transformation intensity (0.2 = subtle refinement, 0.8 = complete reimagining)",
                    default=0.7,
                    min_value=0.1,
                    max_value=1.0,
                )
            )

        return params

    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get the raw workflow graph dictionary for a workflow ID."""
        if workflow_id not in self._raw_workflows:
            raise WorkflowNotFoundError(f"Workflow {workflow_id!r} is not registered")
        return copy.deepcopy(self._raw_workflows[workflow_id])

    def get_metadata(self, workflow_id: str) -> WorkflowMetadata:
        """Get metadata descriptor for a workflow ID."""
        if workflow_id not in self._metadata_cache:
            raise WorkflowNotFoundError(f"Workflow {workflow_id!r} is not registered")
        return self._metadata_cache[workflow_id]

    def list_workflows(self) -> List[WorkflowMetadata]:
        """List metadata for all currently registered workflows."""
        return list(self._metadata_cache.values())

    def build_prompt_graph(self, request: JobSubmissionRequest) -> Dict[str, Any]:
        """
        Clone the target workflow graph and bind the validated request parameters
        into the appropriate node input slots.
        """
        graph = self.get_workflow(request.workflow_id)

        # Collect target node bindings
        clip_text_nodes: List[Tuple[str, Dict[str, Any]]] = []
        empty_latent_nodes: List[Tuple[str, Dict[str, Any]]] = []
        ksampler_nodes: List[Tuple[str, Dict[str, Any]]] = []
        load_image_nodes: List[Tuple[str, Dict[str, Any]]] = []

        for node_id, node in graph.items():
            c_type = node.get("class_type")
            if c_type == "CLIPTextEncode":
                clip_text_nodes.append((node_id, node))
            elif c_type in ("EmptyLatentImage", "EmptyFlux2LatentImage"):
                empty_latent_nodes.append((node_id, node))
            elif c_type in ("KSampler", "KSamplerAdvanced"):
                ksampler_nodes.append((node_id, node))
            elif c_type == "LoadImage":
                load_image_nodes.append((node_id, node))

        # 1. Bind prompt and negative prompt
        # Convention: The first CLIPTextEncode is positive prompt; the second (or one linked as negative) is negative prompt.
        if clip_text_nodes:
            # Build architectural contextual prompt
            arch_prefix = ""
            if request.building_type or request.architectural_style:
                btype_part = f" of a {request.building_type}" if request.building_type else ""
                style_part = f" in {request.architectural_style} style" if request.architectural_style else ""
                arch_prefix = f"Architectural render{btype_part}{style_part}. "
            full_prompt = f"{arch_prefix}{request.prompt}, highly detailed, professional architectural visualization"
            clip_text_nodes[0][1]["inputs"]["text"] = full_prompt

            if len(clip_text_nodes) > 1 and request.negative_prompt:
                clip_text_nodes[1][1]["inputs"]["text"] = request.negative_prompt

        # 2. Bind dimensions to EmptyLatentImage
        for _, l_node in empty_latent_nodes:
            l_node["inputs"]["width"] = request.width
            l_node["inputs"]["height"] = request.height

        # 3. Bind sampling parameters to KSampler
        for _, k_node in ksampler_nodes:
            k_inputs = k_node["inputs"]
            if request.seed is not None:
                k_inputs["seed"] = request.seed
            if request.steps is not None:
                k_inputs["steps"] = request.steps
            if request.cfg is not None:
                k_inputs["cfg"] = request.cfg
            if request.denoise is not None and "denoise" in k_inputs:
                k_inputs["denoise"] = request.denoise

        # 4. Bind input image to LoadImage (for img2img / render enhancement)
        if load_image_nodes and request.input_image_path:
            filename = os.path.basename(request.input_image_path)
            load_image_nodes[0][1]["inputs"]["image"] = filename

        # Distilled FLUX uses its own scheduler and a fixed guidance value.
        if any(n.get("class_type") == "Flux2Scheduler" for n in graph.values()):
            for node in graph.values():
                inputs = node["inputs"]
                if node.get("class_type") == "Flux2Scheduler":
                    inputs.update(steps=4, width=request.width, height=request.height)
                elif node.get("class_type") == "CFGGuider":
                    inputs["cfg"] = 1.0
                elif node.get("class_type") == "RandomNoise" and request.seed is not None:
                    inputs["noise_seed"] = request.seed

        # 5. Apply any explicit extra parameters defined by the caller
        if request.extra_params:
            for node_id, overrides in request.extra_params.items():
                if node_id in graph and isinstance(overrides, dict):
                    graph[node_id]["inputs"].update(overrides)

        return graph

    def validate_against_comfy_object_info(
        self, object_info: Dict[str, Any], validate_models: bool = False
    ) -> Dict[str, List[str]]:
        """
        Verify registered workflows against real ComfyUI runtime node registry.
        Marks workflows unavailable if required nodes are missing and returns
        a dictionary of missing nodes per workflow.
        """
        missing_report = {}
        for wf_id, graph in self._raw_workflows.items():
            meta = self._metadata_cache[wf_id]
            missing_nodes = []
            for node_id, node in graph.items():
                c_type = node.get("class_type")
                if c_type and c_type not in object_info:
                    missing_nodes.append(c_type)
                elif c_type and validate_models:
                    required = object_info[c_type].get("input", {}).get("required", {})
                    for key, value in node.get("inputs", {}).items():
                        if key not in ("ckpt_name", "unet_name", "vae_name", "clip_name", "clip_name1", "clip_name2", "lora_name", "control_net_name"):
                            continue
                        spec = required.get(key)
                        if not spec or not isinstance(spec[0], list) or value not in spec[0]:
                            missing_nodes.append(f"{c_type}.{key}: unavailable model {value}")


            if missing_nodes:
                meta.available = False
                meta.unavailability_reason = (
                    f"Missing required ComfyUI node class(es): {', '.join(sorted(set(missing_nodes)))}"
                )
                missing_report[wf_id] = missing_nodes
            else:
                meta.available = True
                meta.unavailability_reason = None

        return missing_report
