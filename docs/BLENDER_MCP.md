# Expo Design AI: Drawing to Blender MCP MVP

Adds PDF upload, evidence-based AI interpretation, a human review gate, automatic Blender generation, Cycles rendering, and a local MCP interface to the existing Expo Design AI application.

## What works and what remains

This is a constrained MVP, not a general reconstruction engine or an Astra-equivalent product. It supports one floor with axis-aligned rectangular wall, room and opening footprints. Unsupported geometry, missing scale and missing heights must stop for input. A PDF vision proposal is not dimensionally authoritative until a human checks it. No code can guarantee that a vision model recognized every architectural feature.

The renderer makes walls with explicit opening voids, room floor slabs and procedural catalog furniture. It saves an editable `.blend`, PNG render, geometry manifest and log. Roofs, ceilings, stairs, MEP, door leaves, window frames and glazing are not inferred. Cycles is physically based, but the included simple materials and furniture are demonstration quality, not finished photorealistic interior assets.

## Architecture

```text
Expo UI / authenticated MCP client
  -> Expo API (existing login, role and project membership)
  -> saved job + immutable PDF hash
  -> native PDF text + rendered page evidence (PyMuPDF)
  -> OpenAI vision structured proposal
  -> deterministic geometry validation (ezdxf + Shapely)
  -> bounded repair loop / unresolved information
  -> AI furnishing proposal + collision checks
  -> source + proposal review in UI
  -> human approval of exact review hash
  -> fixed bpy builder in background Blender
  -> Cycles render + output checks
  -> optional visible Blender launch
```

The web workflow calls shared Python tools directly. The stdio MCP server exposes the same workflow through the authenticated HTTP API for external agent hosts. It does not replace Expo's existing general chat agent or make that chat automatically discover MCP tools. Model decisions are constrained to drawing interpretation and furnishing, with bounded validation retries; orchestration is a deterministic state machine. No model-generated Python is executed.

## Installation

The installer copies `expo_blender/`, two UI files and this guide, then adds one router hook in `main.py` and one sidebar link in `ui/app.html`. It backs up the original files in `_checkpoints/blender-mcp-TIMESTAMP`. It does not edit `.env`, replace the existing OCR pipeline, or change the app's main requirements.

From this delivery folder:

```powershell
python install.py --project 'C:\3EH\ExpoDesignAI - Copy'
```

Use the Python runtime which runs Expo. On the inspected computer that runtime is:

```powershell
$expoPython = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
Set-Location -LiteralPath 'C:\3EH\ExpoDesignAI - Copy'
& $expoPython -m pip install -r requirements-blender.txt
```

The required runtime dependencies were already present when inspected. The MCP facade supports both MCP Python SDK 1.x and 2.x import layouts; do not downgrade an existing SDK unnecessarily.

## Configure AI and start

Add these values to the application's local `.env`, or set them in its launch environment. Keep the API key local, not in chat, source control or MCP prompts.

```dotenv
OPENAI_API_KEY=your-own-api-key
EXPO_BLENDER_MODEL=your-enabled-vision-and-structured-output-model-id
EXPO_BLENDER_EXE=C:\Program Files\Blender Foundation\Blender 4.5\blender.exe
```

Use an actual OpenAI API model ID available to your account. A ChatGPT/Codex subscription or the name “Astra Pro” does not configure API access. This project intentionally does not guess an equivalent model. The existing app's local Ollama models are not used by this new cloud workflow.

Start or restart Expo through its usual launcher. Sign in, choose **Drawing to Blender** in the sidebar, and select an existing project. The dedicated page is `/ui/blender.html`. Admin/lead roles can create, revise and build; project members can inspect jobs and artifacts. This MVP uploads a separate job copy, rather than selecting an existing indexed document.

1. Upload an unencrypted PDF, maximum 4 pages and 30 MB. Include the plan and relevant elevations/dimensions.
2. Confirm that its selected pages and native text may be sent to OpenAI.
3. The agent reads all submitted pages, proposes geometry, validates it, and proposes furnishing. It makes at most two geometry attempts and three furniture attempts, plus bounded SDK network retries.
4. If dimensions are unknown, provide verified corrections in the review editor. Never remove an unknown by guessing. Unsupported forms need a future geometry adapter, not false approval.
5. Compare source pages and the geometry/evidence table. Check scale, wall thickness, heights, every opening and overall completeness.
6. Click **Approve and build**. It automatically builds and renders. The checked “Open Blender” option opens the finished scene visibly on this computer.

No OpenAI key or model was configured during implementation. Live PDF AI interpretation and the complete logged-in production workflow therefore still require configuration and acceptance testing on an actual drawing. Existing native/OCR ingestion remains untouched; the new workflow uses PDF native text plus OpenAI image understanding, not the existing `ocrsmart`/`ocrbest` commands.

## MCP configuration

Launch the server with Expo's Python, from the project directory:

```powershell
Set-Location -LiteralPath 'C:\3EH\ExpoDesignAI - Copy'
$env:EXPO_API_URL = 'http://127.0.0.1:8090'
$env:EXPO_API_TOKEN = '<your current Expo login token>'
$env:EXPO_MCP_IMPORT_ROOT = 'C:\3EH\DrawingsForBlender'
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m expo_blender.mcp_server
```

Keep the token in the MCP host's private environment/secret configuration. It retains the same Expo role/project restrictions and expires with the login session. The MCP server is stdio-only; its HTTP client accepts only loopback Expo addresses. If Expo uses another port, configure `EXPO_API_URL` accordingly.

Example host configuration (replace executable path and token locally):

```json
{
  "mcpServers": {
    "expo-blender": {
      "command": "C:/Users/RE&DBIM/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "expo_blender.mcp_server"],
      "env": {
        "PYTHONPATH": "C:/3EH/ExpoDesignAI - Copy",
        "EXPO_API_URL": "http://127.0.0.1:8090",
        "EXPO_API_TOKEN": "SET_PRIVATELY_IN_YOUR_MCP_HOST",
        "EXPO_MCP_IMPORT_ROOT": "C:/3EH/DrawingsForBlender"
      }
    }
  }
}
```

Tools: `blender_health`, `create_pdf_model_job`, `get_model_job`, `revise_model_proposal`, `build_approved_model`, `open_completed_model`. There is deliberately no MCP approval or arbitrary-code tool. Review approval is an authenticated UI action. Source PDF content is treated as untrusted data in the AI prompts.

Example agent request: “Create a model from floor-plan.pdf in my approved import folder for project Office. I authorize OpenAI processing. Inspect the job, report any missing dimensions, and wait for my source review in Expo before building.”

## Files, validation and recovery

Jobs live under `<project>/data/blender_jobs/<job-id>` unless `EXPO_BLENDER_DATA` is set. The page displays the job ID; save it to resume. Each job records source hash, evidence, proposal, review, approval, events and outputs. The `.blend` preserves DXF handle metadata; PDF-derived DXF handles map back to plan IDs and page evidence.

The geometry validator rejects unsupported units, open/curved/nonrectangular footprints, non-ground-plane geometry, unmapped entities, overlapping walls/rooms, unsupported opening placement, missing opening metadata and invalid heights. Furniture uses an allowlist with footprint collision, room clearance and conservative door approach checks. It does not validate accessibility, egress networks or building-code compliance.

Jobs use atomic JSON writes and exclusive operation locks. A process crash can leave `operation.lock` and an in-progress status. This is an in-process background worker, not a durable production queue. Do not delete a lock while its recorded PID is still running. After confirming the worker is gone, preserve the job, remove only that job's stale lock, and upload again for analysis or rebuild an already approved review. There is no automatic crash recovery or job-list UI yet.

For rollback, restore the backed-up `main.py` and `app.html` from the matching checkpoint, then restart Expo. Do not overwrite unrelated later changes; compare them first. Leaving the additive module and job files on disk preserves work and does not activate the router.

## Testing and next implementation steps

Run from the delivery folder with its dependencies plus pytest:

```powershell
python -m pytest -q
```

Tests cover geometry provenance, unresolved scale/heights, invalid numeric data, source mutation, stale approvals, revision invalidation, locks, unauthorized building, bounded AI repair with mock model output, path containment, role/project API access, and the absence of an MCP approval tool. These are not live AI accuracy evaluations.

Recommended next milestones:

1. Accept real reference PDFs; compare extracted boundaries/openings against annotated ground truth and display an aligned source overlay.
2. Add explicit calibrated vector extraction, polygon/rotated wall support, doors/windows assemblies and multilevel geometry without changing source coordinates.
3. Add curated production furniture/PBR assets and interior perspective cameras for photorealistic deliverables.
4. Move long jobs to Expo's durable queue with cancellation, restart recovery and resource limits.
5. Register the MCP client/tools in Expo's existing chat runtime if conversational orchestration is desired; keep human approval outside model tool authority.

Official implementation references: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/), [ezdxf LWPOLYLINE](https://ezdxf.readthedocs.io/en/stable/dxfentities/lwpolyline.html).
