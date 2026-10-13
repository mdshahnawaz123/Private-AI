# Expo Design AI — Local Image Engine Operator & Architecture Guide

**System:** Expo Design AI — Local Image Engine Integration  
**Target Hardware:** Windows 11 Pro | NVIDIA GeForce RTX 5080 (16 GB VRAM) | 64 GB System RAM  
**Binding:** 100% Localhost & Air-Gapped Offline Deployment (`127.0.0.1:8188`)  
**Branch:** `feature/image-engine-comfyui`  

---

## 1. System Architecture & Overview

The **Expo Design AI Local Image Engine** integrates a dedicated, locally hosted [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance into the Expo Design AI platform. It provides architects and engineers with private, offline generative rendering and concept exploration capabilities directly adjacent to their project documentation and IFC model analysis.

```
+-----------------------------------------------------------------------------------+
|                            Expo Design AI Frontend                                |
|   ui/app.html & ui/app.js  --  AI Design Studio Tab (Briefs, Viewport, Gallery)   |
+-----------------------------------------------------------------------------------+
                                        |  HTTP / REST API
                                        v
+-----------------------------------------------------------------------------------+
|                        Expo Design AI FastAPI Backend                             |
|  - services/image_engine/api.py              (Authentication & Validation)        |
|  - services/image_engine/job_service.py      (Single-Worker FIFO Queue Worker)    |
|  - services/image_engine/workflow_registry.py(Node Graph Composition & Binding)   |
|  - services/image_engine/image_storage.py    (Atomic Disk Persistence & Sidecars) |
|  - db.py (SQLite: ImageJob & ImageOutput tables)                                  |
+-----------------------------------------------------------------------------------+
               | HTTP (REST)                            ^ WebSocket (ws://)
               | POST /prompt                           | Node Progress & Errors
               | POST /upload/image                     |
               v                                        |
+-----------------------------------------------------------------------------------+
|                     Local ComfyUI Daemon (127.0.0.1:8188)                         |
|  - Checkpoints: models/checkpoints/ (SDXL / SD 1.5 / FLUX FP8)                    |
|  - Workflows: workflows/architecture_concept, sketch_to_render, render_enhance     |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|                   Hardware: NVIDIA GeForce RTX 5080 (16 GB VRAM)                  |
|  - Shared with local Ollama LLM (qwen3.5:9b) & Windows Desktop Compositor         |
|  - Strict Concurrency Limit = 1 (Zero VRAM thrashing or memory oversubscription)  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Supported Architectural Workflows

All workflows are defined as production-validated ComfyUI JSON graphs in `workflows/`:

### 2.1 Architecture Concept Generator (`architecture_concept`)
- **Purpose:** Generates architectural concept options from text prompts, building types, and stylistic descriptors.
- **Inputs:** `prompt`, `negative_prompt`, `building_type`, `architectural_style`, `width`, `height`, `steps`, `cfg`, `seed`.
- **Node Pipeline:** `CheckpointLoaderSimple` -> `CLIPTextEncode` (positive & negative) -> `EmptyLatentImage` -> `KSampler` -> `VAEDecode` -> `SaveImage`.

### 2.2 Sketch to Render (`sketch_to_render`)
- **Purpose:** Transforms 2D architectural sketches, hand drawings, massing studies, or viewport snapshots into refined renders.
- **Inputs:** `input_image_path` (reference image), `prompt`, `denoise` (0.35–0.75), `seed`, `steps`.
- **Node Pipeline:** `LoadImage` -> `VAEEncode` -> `KSampler` (conditioned with denoise factor) -> `VAEDecode` -> `SaveImage`.

### 2.3 Render Enhancement (`render_enhancement`)
- **Purpose:** Enhances existing 3D viewport renders or early-stage visualization assets with photorealistic materials, lighting, and reflections.
- **Inputs:** `input_image_path`, `prompt`, `architectural_style`, `denoise` (0.2–0.5), `seed`.
- **Node Pipeline:** `LoadImage` -> `VAEEncode` -> `KSampler` (subtle denoise) -> `VAEDecode` -> `SaveImage`.

---

## 3. Hardware & VRAM Management (RTX 5080 16 GB)

The RTX 5080 operates with 16 GB GDDR7 VRAM. In a typical engineering environment, VRAM is partitioned across:
- **Windows Desktop Window Manager (DWM):** ~1.5 GB
- **Local Ollama LLM / Vision models:** ~5.0–7.5 GB
- **Available for Diffusion Inference:** ~7.0–9.5 GB

To prevent CUDA Out-of-Memory crashes and maintain operating system stability:

1. **Strict FIFO Queue Serialization (`concurrency = 1`):**
   - The queue worker executes exactly **one** image generation job at any given time.
   - Additional job submissions are recorded in SQLite in `queued` status and processed in first-come, first-served order.
2. **Resolution Clamping:**
   - Width and height are bounded between 512 and 1024 px in increments of 64. Arbitrary or excessively large aspect ratios that could breach VRAM limits are rejected at the schema level.
3. **CUDA OOM Interception & Automatic Recovery:**
   - If ComfyUI emits a `CUDA out of memory` exception, the client intercepts the error, marks the job as `failed` with clear remediation instructions in the UI, and immediately restores the worker to process the next job without crashing the server.
4. **WebSocket Drop Resiliency:**
   - If the WebSocket connection drops during generation, the client seamlessly falls back to HTTP history polling (`/history/{prompt_id}`) so in-flight renders are never lost.

---

## 4. Local Installation & Operation Guide

ComfyUI is located at:
```
C:\3EH\ComfyUI
```

### 4.1 Initial Setup (One-time)
To install PyTorch with CUDA and required dependencies into the isolated virtual environment:
1. Open PowerShell or Command Prompt.
2. Run:
   ```cmd
   cd C:\3EH\ComfyUI
   .\setup_env.bat
   ```
   *This updates pip, installs `torch`, `torchvision`, `torchaudio` with CUDA 12.6 support, and installs all ComfyUI requirements inside `C:\3EH\ComfyUI\venv\`.*

### 4.2 Adding Architectural Model Checkpoints
Place your preferred `.safetensors` model checkpoints into:
```
C:\3EH\ComfyUI\models\checkpoints\
```
Recommended models:
- **SDXL 1.0 Base:** `sd_xl_base_1.0.safetensors` (High quality architectural concepting)
- **Realistic Vision v6.0 / Juggernaut XL:** (Photorealistic facades and materials)
- **Architectural LoRAs:** Placed in `C:\3EH\ComfyUI\models\loras\`

### 4.3 Starting ComfyUI
Launch the daemon before or alongside Expo Design AI:
```cmd
cd C:\3EH\ComfyUI
.\run_comfyui.bat
```
This starts ComfyUI bound strictly to `127.0.0.1:8188` with `--highvram`.

### 4.4 Verifying Connection
Once started, the **🎨 AI Design Studio** tab in Expo Design AI (`http://127.0.0.1:8000/app.html`) will display a green status badge:
```
● ComfyUI Online (127.0.0.1:8188)
```

---

## 5. Storage Hierarchy & Sidecar Metadata

Generated images are stored with strict project containment:
```
C:\3EH\ExpoDesignAI - Copy\data\projects\{project_name}\generated_images\{job_id}\
    ├── ExpoArch_0001.png           (Full-resolution output image)
    ├── ExpoArch_0001.png.meta.json (Sidecar metadata audit log)
    ├── thumb_ExpoArch_0001.png     (256x256 fast thumbnail)
    └── input_sketch.png            (Optional reference upload)
```

### Sidecar Metadata Schema (`.png.meta.json`):
```json
{
  "project": "Dubai_Pavilion_2026",
  "job_id": "imgjob-9d9a62ff4576",
  "filename": "ExpoArch_0001.png",
  "width": 1024,
  "height": 768,
  "seed": 424242,
  "metadata": {
    "workflow_id": "architecture_concept",
    "prompt": "Architectural render of a Cultural Pavilion in Parametric style. Timber lattice facade",
    "architectural_style": "Parametric",
    "building_type": "Cultural Pavilion",
    "comfy_prompt_id": "prompt-e58f-410a-b31c",
    "steps": 25,
    "cfg": 7.0
  }
}
```

---

## 6. REST API Reference

| Endpoint | Method | Description | Guard |
| :--- | :--- | :--- | :--- |
| `/api/images/health` | `GET` | Returns ComfyUI connectivity, queue depth, GPU status | Public / UI Polling |
| `/api/images/workflows` | `GET` | Lists available workflows and configurable parameters | Authenticated User |
| `/api/images/jobs` | `POST` | Submits a generation job (supports multipart uploads) | Project Member |
| `/api/images/jobs/{job_id}` | `GET` | Returns job execution status, progress %, and errors | Project Member |
| `/api/images/jobs/{job_id}/outputs` | `GET` | Returns list of generated outputs with URLs | Project Member |
| `/api/images/outputs/{id}/file` | `GET` | Streams authenticated high-res image binary | Project Member |
| `/api/images/outputs/{id}/thumbnail` | `GET` | Streams authenticated 256x256 thumbnail | Project Member |
| `/api/images/jobs/{job_id}/cancel` | `POST` | Cancels a queued or active generation job | Job Owner / Admin |

---

## 7. Troubleshooting & Recovery

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **Status shows "ComfyUI Offline"** | ComfyUI is not running or listening on port 8188 | Run `C:\3EH\ComfyUI\run_comfyui.bat`. Check that no other process occupies port 8188. |
| **CUDA Out of Memory (OOM)** | Generation resolution too high or VRAM saturated by other applications | Reduce resolution in UI to 768x768 or 512x512. Check if Ollama is running a heavy 70B model. |
| **Missing Custom Nodes** | A workflow requires custom nodes not present in ComfyUI | Check `/api/images/workflows` unavailability reasons. The engine flags missing nodes cleanly. |
| **Image outputs not appearing** | Disk storage permissions or path containment violation | Verify project write permissions in `data/projects/{project}/generated_images/`. |
