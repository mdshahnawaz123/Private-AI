"""
Pydantic schemas for the Expo Design AI Local Image Engine.

Defines API data models for ComfyUI status, workflow definitions,
job submission, generation progress, and retrieved outputs.
"""

from typing import List, Optional, Dict, Any, Literal, Annotated
from pydantic import BaseModel, Field, field_validator


class EngineStatus(BaseModel):
    """Health and resource status of the local ComfyUI engine."""
    available: bool = Field(..., description="Whether ComfyUI HTTP/WS API is currently reachable")
    base_url: str = Field(..., description="Base URL of the ComfyUI service")
    device: str = Field(default="cuda", description="Primary compute device reported by ComfyUI")
    vram_total_mb: Optional[int] = Field(default=None, description="Total GPU VRAM in megabytes")
    vram_free_mb: Optional[int] = Field(default=None, description="Free GPU VRAM in megabytes")
    queue_running: int = Field(default=0, description="Number of currently executing prompts")
    queue_pending: int = Field(default=0, description="Number of queued prompts waiting in ComfyUI")
    model_loaded: Optional[str] = Field(default=None, description="Active model checkpoint if known")
    details: Optional[str] = Field(default=None, description="Detailed diagnostic or error message")


class WorkflowParameter(BaseModel):
    """Specification of an exposed, configurable parameter in a workflow."""
    name: str = Field(..., description="Parameter key name (e.g. prompt, seed, width)")
    type: Literal["string", "integer", "float", "boolean", "choice", "image"] = Field(
        ..., description="Data type of the parameter"
    )
    label: str = Field(..., description="Human-readable label for UI rendering")
    description: Optional[str] = Field(default=None, description="Tool tip or explanation")
    default: Any = Field(default=None, description="Default parameter value")
    min_value: Optional[float] = Field(default=None, description="Minimum numeric value if applicable")
    max_value: Optional[float] = Field(default=None, description="Maximum numeric value if applicable")
    choices: Optional[List[str]] = Field(default=None, description="Allowed choices for choice type")
    required: bool = Field(default=False, description="Whether this parameter must be supplied")


class WorkflowMetadata(BaseModel):
    """Metadata describing a registered ComfyUI workflow."""
    id: str = Field(..., description="Unique workflow identifier (e.g. architecture_concept)")
    name: str = Field(..., description="Human-readable name")
    version: str = Field(default="1.0.0", description="Workflow schema version")
    description: str = Field(default="", description="Detailed summary of workflow purpose")
    category: Literal["concept", "sketch", "enhancement", "video", "general"] = Field(
        default="general", description="Architectural category"
    )
    required_models: List[str] = Field(default_factory=list, description="Model checkpoint files required")
    required_custom_nodes: List[str] = Field(
        default_factory=list, description="Custom ComfyUI node classes required"
    )
    parameters: List[WorkflowParameter] = Field(
        default_factory=list, description="Exposed configurable parameters"
    )
    available: bool = Field(default=False, description="Whether all required nodes and models are present")
    license_notes: Optional[str] = Field(default=None, description="Licensing and usage terms for the model")
    unavailability_reason: Optional[str] = Field(
        default=None, description="Explanation if workflow cannot currently execute"
    )


class JobSubmissionRequest(BaseModel):
    """Request payload to submit a new image generation job."""
    project: str = Field(..., min_length=1, max_length=200, description="Target authorized project name")
    workflow_id: str = Field(..., min_length=1, description="Registered workflow identifier")
    prompt: str = Field(..., min_length=1, max_length=4000, description="Positive prompt text")
    negative_prompt: Optional[str] = Field(default=None, max_length=2000, description="Optional negative prompt")
    architectural_style: Optional[str] = Field(
        default="Contemporary", description="Architectural style descriptor"
    )
    building_type: Optional[str] = Field(
        default="Commercial", description="Building typology (Residential, High-rise, etc.)"
    )
    width: int = Field(default=1024, ge=480, le=1920, description="Output width (multiple of 16)")
    height: int = Field(default=1024, ge=480, le=1920, description="Output height (multiple of 16)")
    seed: Optional[int] = Field(default=None, ge=0, le=2**63 - 1, description="Optional deterministic seed")
    steps: Optional[int] = Field(default=20, ge=4, le=50, description="Sampling steps")
    cfg: Optional[float] = Field(default=7.0, ge=1.0, le=20.0, description="Classifier-free guidance scale")
    denoise: Optional[float] = Field(
        default=0.7, ge=0.05, le=1.0, description="Denoising strength for img2img workflows"
    )
    frames: Optional[int] = Field(default=49, ge=17, le=161, description="Number of video frames generated")
    fps: Optional[int] = Field(default=16, ge=8, le=60, description="Video playback frames per second")
    camera_motion: Optional[str] = Field(default=None, description="Architectural camera movement preset")
    input_image_path: Optional[str] = Field(
        default=None, description="Server-relative path to uploaded reference sketch/render"
    )
    edit_mask_path: Optional[str] = Field(default=None, description="Optional project-owned binary PNG: white edits, black protects")
    enhance_prompt: bool = Field(
        default=False, description="Whether to use reasoning AI (qwen3.5:9b) to enrich the architectural brief"
    )
    extra_params: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional workflow-specific parameters"
    )

    @field_validator("width", "height")
    @classmethod
    def validate_dimension_multiple_of_16(cls, val: int) -> int:
        if val % 16 != 0:
            raise ValueError(f"Dimension {val} must be a multiple of 64 (or 16 for video)")
        return val


class JobOutput(BaseModel):
    """Metadata for a successfully generated and persisted image output."""
    output_id: str = Field(..., description="Unique output identifier")
    filename: str = Field(..., description="Basename of the stored image file")
    file_path: str = Field(..., description="Project-relative storage path")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    seed: Optional[int] = Field(default=None, description="Seed used for this generation")
    media_type: Optional[str] = Field(default="image", description="Media type ('image' or 'video')")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Generation metadata sidecar")
    download_url: Optional[str] = Field(default=None, description="Authenticated download endpoint")
    thumbnail_url: Optional[str] = Field(default=None, description="Authenticated thumbnail endpoint")


class JobStatus(BaseModel):
    """Real-time lifecycle status of an image generation job."""
    job_id: str = Field(..., description="Unique job ID")
    project: str = Field(..., description="Project name")
    workflow_id: str = Field(..., description="Workflow ID used")
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = Field(
        ..., description="Current job state"
    )
    progress_percent: int = Field(default=0, ge=0, le=100, description="Progress from 0 to 100")
    current_step: Optional[int] = Field(default=None, description="Current latent sampling step")
    total_steps: Optional[int] = Field(default=None, description="Total latent sampling steps")
    queue_position: Optional[int] = Field(default=None, description="Position in Expo Design AI queue")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    reasoning: Optional[str] = Field(
        default=None, description="Architectural reasoning rationale applied to the prompt"
    )
    enhanced_prompt: Optional[str] = Field(
        default=None, description="Reasoning-enhanced prompt used during render"
    )
    outputs: List[JobOutput] = Field(default_factory=list, description="Generated outputs when completed")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp of job creation")
    completed_at: Optional[str] = Field(default=None, description="ISO timestamp of job completion")
    execution_duration_sec: Optional[float] = Field(
        default=None, description="Execution duration in seconds"
    )


class DesignOption(BaseModel):
    """Architectural design option variant honoring user constraints."""
    id: str = Field(..., description="Unique option identifier, e.g. option_a")
    title: str = Field(..., description="Short title, e.g. Biophilic & Terraced")
    style: Optional[str] = Field(default=None, description="Architectural style name")
    prompt: str = Field(..., description="Full diffusion prompt for this option")
    rationale: Optional[str] = Field(default=None, description="Architectural design intent and rationale")
    materials: str = ""
    shading_strategy: str = ""
    changes: str = ""
    protected_elements: List[str] = Field(default_factory=list)



class PromptEnhanceRequest(BaseModel):
    """Request payload to enhance an architectural prompt using reasoning AI."""
    prompt: str = Field(..., min_length=1, max_length=4000, description="User architectural brief")
    building_type: Optional[str] = Field(default=None, description="Building typology")
    architectural_style: Optional[str] = Field(default=None, description="Architectural style")


    mode: Literal["concept", "materials", "enhancement", "creative_facade"] = "concept"
    protected_elements: List[Annotated[str, Field(min_length=1, max_length=150)]] = Field(default_factory=list, max_length=20)
    materials: str = Field(default="", max_length=600)
    lighting: str = Field(default="", max_length=300)


class PromptEnhanceResponse(BaseModel):
    """Response payload from prompt reasoning enhancement."""
    success: bool = Field(..., description="Whether reasoning model succeeded")
    original_prompt: str = Field(..., description="Original user prompt")
    enhanced_prompt: str = Field(..., description="Enriched architectural prompt")
    reasoning: Optional[str] = Field(default=None, description="Architectural reasoning explanation")
    preserved_constraints: List[str] = Field(
        default_factory=list,
        description="Explicit user constraints strictly preserved (e.g. G+10 floor count, program, materials)",
    )
    design_options: List[DesignOption] = Field(
        default_factory=list,
        description="Distinct architectural design schemes honoring the same constraints",
    )
    model: Optional[str] = Field(default=None, description="Reasoning model used")
    error: Optional[str] = Field(default=None, description="Error message if fallback was used")


