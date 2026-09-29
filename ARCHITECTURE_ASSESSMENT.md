# Expo Design AI — Architecture Assessment & Phase 1 Plan

_Prepared by: Lead Architect review · Date: 2026-09-27_
_Status: **Assessment only — no code changed. Awaiting approval before any architectural work.**_

> Ground rule honoured throughout: **do not rebuild, do not duplicate, do not break the working IFC viewer or the local AI.** Everything below is an *evolution* of what already runs, not a replacement.

---

## 1. Current architecture (as it really runs today)

A **single-process FastAPI application** (`main.py`, ~1,400 lines) serves both the API and the web UI on `http://127.0.0.1:8090`. It is launched by `start.bat` via `python main.py`, which calls `uvicorn.run(app, ...)` — **one process, one worker**.

Request flow for a question:
1. Browser (`ui/index.html`) → `POST /ask_stream` with `{project, query, messages, k, discipline}` and a Bearer JWT.
2. Auth middleware resolves the user; `auth.require_project` enforces project access.
3. `retrieve_context()` loads the project's **FAISS** index (cached in a module-level dict `vectorstores={}`), runs similarity search, and applies **folder-level permission filtering** server-side.
4. `build_messages()` assembles a grounded system prompt + context + trimmed history.
5. `local_chat.LocalChatOllama` streams tokens from **Ollama** (`/api/chat`), relayed to the browser as SSE.
6. Sources (file + page + revision) are resolved and streamed as a `sources` event.

Document ingestion is a **background job** (`BackgroundTasks` + `run_in_threadpool`): every PDF page is rendered and vision-read, Excel/Word parsed, output stored as per-file `*.index.json`, then embedded into FAISS.

**The concurrency ceiling is structural and important:** one Python process + in-memory FAISS + SQLite (single-writer) + Ollama with `OLLAMA_MAX_LOADED_MODELS=1` (inference is serialized). This is fine for ~1–5 concurrent reviewers today; it will **not** reach 100+ without the changes in §10.

---

## 2. Current technology stack

| Layer | Technology | Notes |
|---|---|---|
| API / server | FastAPI + Uvicorn (`main.py`), port 8090 | single process, single worker |
| Auth | Local accounts, PBKDF2-SHA256 (passlib), JWT (python-jose) | Bearer header or `?token=` for SSE |
| Database | **SQLite** via SQLAlchemy (`data/expo.db`); Alembic scaffold present | `create_all` used at runtime; migrations not yet the source of truth |
| Vector search | **FAISS** (`langchain_community`), per-project + shared `__codes__` KB | in-memory cache dict, `save_local`/`load_local` to disk |
| Local AI | **Ollama** — chat+vision `qwen2.5vl:32b`, embeddings `bge-m3` | direct HTTP clients `local_chat.py`, `local_embed.py` |
| LLM framework | LangChain (community/ollama/core/text-splitters) | used for loaders, splitter, FAISS; chat/embeddings bypass it via direct clients |
| Doc processing | PyMuPDF, pdfplumber, pypdf, docx2txt, python-docx, openpyxl, unstructured, Pillow | vision-per-page deep extraction |
| CAD | ezdxf (+ ODA File Converter for DWG), matplotlib render → vision | `cad.py` |
| 3D / IFC | **web-ifc (WASM) + three.js + OrbitControls**, vendored in `ui/vendor/` | 100% browser-side parsing, offline |
| Frontend | Static HTML/JS served by backend: `ui/index.html` (single file, 132 KB) + `ui/viewer.html` + `ui/viewer.js` | no build step, no framework |
| Reports | reportlab, jinja2 (present in reqs; report pipeline not yet wired) | |
| Logging/audit | loguru + immutable `audit_log` table (SQLite triggers block UPDATE/DELETE) | |

---

## 3. Existing folder structure

```
ExpoDesignAI/
  main.py            API, endpoints, RAG orchestration, upload/processing, access guards
  db.py              SQLAlchemy models + helpers (9 tables)
  auth.py            PBKDF2 hashing, JWT, role/project guards, admin seed
  local_chat.py      direct Ollama /api/chat streaming client (retry-on-empty)
  local_embed.py     direct Ollama /api/embeddings + /api/embed batch client
  vision.py          local vision-model calls (serialized + retry)
  extract.py         deep extraction (PyMuPDF per-page + vision, Excel, Word) → JSON
  cad.py             DWG/DXF extraction (ezdxf/ODA) + matplotlib render
  meta_parse.py      drawing metadata + revision grouping
  disciplines.py     discipline registry + Architecture checklist + reviewer prompts
  alembic/ , alembic.ini      migration scaffold (not yet authoritative)
  requirements.txt , start.bat , install.ps1 , setup_3d_viewer.{bat,ps1}
  test_*.py          phase tests (cad, excel, extract, phase2/3/5)
  PROJECT_STATUS.md  handover / status doc
  ui/
    index.html       the entire main web UI (chat, docs, admin, 3D launch)
    viewer.html      3D viewer shell (toolbar + panels)
    viewer.js        IFC viewer engine (web-ifc → three.js), 30 KB
    fonts.css , vendor/{three.module.js, OrbitControls.js, web-ifc-api.js, web-ifc.wasm}
  data/
    expo.db          SQLite
    faiss_index/<project>/   per-project vector index
    faiss_index/__codes__/   shared DBC/IBC KB
    docs/<project>/<Category>/…   original uploads + <file>.index.json
    workspace/<project>/     sandboxed cowork file tool area
    logs/expo.log , secret.key
```

---

## 4. Existing IFC architecture (the part to protect)

- **Parsing is entirely browser-side** with `web-ifc` (WASM). The server only *stores and serves* the `.ifc` file (`GET /projects/{project}/file?rel=…&token=…`). There is **no server-side IFC entity extraction** (IfcOpenShell is not installed — PyPI is blocked in this environment).
- `viewer.js` streams meshes via `StreamAllMeshes` and applies each element's `flatTransformation` (the **full IfcLocalPlacement hierarchy** — Project→Site→Building→Storey→Element). This is correct and must not be re-implemented.
- **Coordinate pipeline (recently fixed, must stay):**
  - `COORDINATE_TO_ORIGIN` on the first model normalises large survey coordinates; its **coordination matrix** is reused via `SetGeometryTransformation` for subsequent models → all models share **one common world frame**.
  - Units read from `IfcProject`; True North read from the geometric context; the IfcSite placement rotation (≈ −32° on the current model, from "Shared Coordinates") is detected.
  - **No geometry is ever rotated.** "Plan North / True North" rotate the **camera/view only**. A **Debug** panel surfaces units, true north, site origin/refDir, coordination shift, and world bbox.
- Existing viewer features: model list + per-model visibility, categories (by IFC class), element selection + properties (via `GetLine`), hide/isolate/show-all, colour override/reset, section X/Y/Z + slider, measure length/area, storey plan views, **Ask AI** (model-grounded Q&A → `/ask_model`).
- **Delivery today:** the viewer opens as a semi-separate page (`viewer.html`) launched from the main UI. Per the product vision (§4 of the brief) it should become a **panel inside the unified workspace**, not a separate app — that is a *hosting/layout* change, **reusing the same `viewer.js` engine unchanged**.

---

## 5. Existing AI architecture

- **Model access is already abstracted** into two thin clients: `local_chat.LocalChatOllama` (streaming chat/vision) and `local_embed.LocalOllamaEmbeddings` (single + batch). This is the seed of a proper **model-routing / gateway** layer — a real asset.
- Prompts are grounded and anti-fabrication: `build_messages()` forbids "I can't read files", cites source+page, and refuses to invent values; the 3D `/ask_model` prompt is grounded strictly in browser-extracted model data.
- Tuning: `EXPO_NUM_CTX=16384`, `num_predict=3072`, `keep_alive=5m`, `OLLAMA_MAX_LOADED_MODELS=1`, batch embeddings.
- **Gaps vs. the vision:** no model **router** (one hard-wired chat model, one embed model; no coder/reranker routing), no **reranking** stage, no **request/job queue**, no multi-inference-server fan-out. The abstraction exists; the routing/scaling around it does not yet.

---

## 6. Existing document / RAG architecture

- **Ingestion:** categorised disk storage (Drawings/3D-Models/Schedules/Reports/Images/Other) + **deep per-page vision extraction** → structured `*.index.json` per file (page-aware).
- **Indexing:** page-aware chunking tags `{source, page, folder_id}`; embedded with `bge-m3` into **per-project FAISS**; a shared `__codes__` KB holds DBC/IBC.
- **Retrieval:** `retrieve_context()` does similarity search (k≈8), **enforces folder permissions server-side** (a user assigned to a folder can only retrieve that folder's chunks — with a `doc_folder_map` fallback and a permission self-test), and resolves **file + page + revision** for citations.
- **Answering:** the LLM answers directly and streams; sources are returned as chips with page + "open original".
- **Gaps vs. the vision:** retrieval is **unstructured text only**. There is **no reranker**, no **typed evidence objects**, no **source-precedence** logic, and the structured JSON is text — not typed BIM/schedule/drawing **entities**. The "answer format with ANSWER / PROJECT DATA / CALCULATION / EVIDENCE / STATUS" (§14 of the brief) is not yet enforced.

---

## 7. Existing database

SQLite (`data/expo.db`) via SQLAlchemy. **Nine tables today:**

`users` · `projects` · `chats` · `documents` (has `folder_id`) · `findings` · `audit_log` (immutable) · `project_members` · `folders` · `folder_members`.

Strong foundations: project scoping, folder-level RBAC, immutable audit, membership. **Missing for the platform vision:** no `bim_model` / `bim_element`, no `drawing`, no `schedule` / `schedule_row`, no `qa_finding` (the current `findings` is checklist-oriented, not deterministic-QA), no `graph_edge` (knowledge graph), no `source_precedence`, and `documents` lacks structured metadata (doc number, revision, section, discipline, date, status).

---

## 8. What should be REUSED (unchanged or nearly so)

- **The entire IFC viewer** (`viewer.js` + vendored web-ifc/three) and its coordinate pipeline. Re-host it in the workspace; do not touch the engine.
- **The local AI clients** (`local_chat.py`, `local_embed.py`) — promote them into the model-router, don't replace them.
- **Auth + RBAC + folders + audit** (`auth.py`, membership/folder tables, `retrieve_context` permission filter). This already satisfies much of §22/§23 (project isolation, audit).
- **Ingestion + deep extraction** (`extract.py`, `vision.py`, `cad.py`, categorised storage, `.index.json`). Keep as the document pipeline; layer *structured* extractors on top.
- **FastAPI app, routing style, SSE streaming, discipline registry.**
- **SQLAlchemy models + Alembic scaffold** — extend, don't rewrite.

## 8b. What should be REFACTORED (evolve, carefully, behind the existing behaviour)

- **Serving model:** `python main.py` (1 worker) → Gunicorn/Uvicorn **multiple workers**; move the in-memory FAISS cache out of per-process memory (shared vector DB) so workers are stateless. *(Scaling prerequisite.)*
- **Database:** SQLite → **PostgreSQL** for real concurrency (single-writer SQLite is the hard blocker for 100+). SQLAlchemy makes this mostly a URL + migration change; Alembic becomes authoritative.
- **Vector store:** FAISS (in-proc) → a **persistent, project-partitioned** store shared across workers (Chroma already planned; Qdrant/pgvector are stronger at scale). Keep FAISS running until the swap lands (as the reqs already warn).
- **AI access:** wrap `local_chat`/`local_embed` in a **model-router + gateway** with a **queue** (so 100 users don't all hit one Ollama process); allow multiple inference backends later (Ollama now, vLLM/others later).
- **Answer orchestration:** introduce a **question-engine** service that assembles typed evidence (BIM+drawing+schedule+doc+standard), runs **deterministic calculations in code**, then hands the LLM evidence to explain — matching §13/§14.

---

## 9. Proposed TARGET architecture (evolution, not rewrite)

A layered "Project Intelligence Platform" that keeps the current app as its core:

```
                         ┌─────────────────────────────────────────────┐
  Browser (unified UI)   │  LEFT: project/nav   CENTER: 3D│Drawing│      │
  reuse index.html +     │  Report│Schedule│Chat   RIGHT: AI│Props│      │
  viewer.js engine       │  Evidence     (collapsible: Focus/Split modes)│
                         └───────────────┬─────────────────────────────┘
                                         │ HTTPS / SSE (JWT)
                     ┌───────────────────▼───────────────────┐
                     │  FastAPI API (versioned /api/v1)       │  ← multi-worker
                     │  routers: auth, projects, bim,         │
                     │  drawings, schedules, documents,       │
                     │  standards, qa, graph, ask, admin      │
                     └───┬───────┬────────┬─────────┬─────────┘
        ┌────────────────┘       │        │         └───────────────┐
   ┌────▼─────┐          ┌───────▼──┐ ┌───▼─────────┐        ┌───────▼────────┐
   │ Question │          │ Determin-│ │  RAG +       │        │  AI Gateway /  │
   │ Engine   │─evidence▶│ istic QA │ │  Reranker +  │        │  Model Router  │
   │ (orches.)│          │ Engine   │ │  Evidence    │        │ (Ollama→vLLM…) │
   └────┬─────┘          └────┬─────┘ └───┬──────────┘        └───────┬────────┘
        │                     │           │                          │
   ┌────▼─────────────────────▼───────────▼──────────┐        ┌───────▼────────┐
   │  Structured stores (PostgreSQL):                 │        │  Job/Request   │
   │  bim_element · drawing · schedule/rows ·         │        │  queue (later: │
   │  qa_finding · graph_edge · source_precedence ·   │        │  Redis+worker) │
   │  users/projects/folders/audit (existing)         │        └────────────────┘
   └───────────┬──────────────────────────────────────┘
   ┌───────────▼───────────┐   ┌──────────────────────┐   ┌───────────────────┐
   │ Vector DB (project-   │   │ Object storage:       │   │ Local inference   │
   │ partitioned: Chroma/  │   │ docs, IFC, renders    │   │ server(s): Ollama │
   │ Qdrant/pgvector)      │   │ (disk now → S3-compat)│   │ (+vLLM later)     │
   └───────────────────────┘   └──────────────────────┘   └───────────────────┘
```

**Server-side IFC extraction decision (important):** because IfcOpenShell can't be pip-installed here, the **structured BIM database is populated from the browser**: `viewer.js` (which already parses the IFC with web-ifc) extracts typed entities and property sets and **POSTs them to a new `/api/v1/bim/ingest`** endpoint, which writes `bim_element` rows. This reuses the working parser, adds no server dependency, and keeps everything offline. (Alternative: arrange an offline IfcOpenShell wheel install on the server — only if you want ingestion without opening the model.)

---

## 10. Proposed database schema (additive — existing tables untouched)

New tables (all carry `project_id` for isolation, per §23):

- **bim_model** `(id, project_id, document_id, filename, ifc_schema, length_unit, true_north_deg, site_origin, coordination_matrix, element_count, created_at)`
- **bim_element** `(id, project_id, bim_model_id, guid UNIQUE-ish, ifc_class, type_name, name, level, x, y, z, length, width, height, thickness, area, volume, material, system, classification, psets JSON, created_at)` — **GUID is the stable cross-domain key.**
- **drawing** `(id, project_id, document_id, number, title, revision, discipline, level, sheet, sheet_date, status, file_path, page, source)`
- **schedule** `(id, project_id, document_id, schedule_type, source_sheet)` + **schedule_row** `(id, schedule_id, project_id, mark, guid?, fields JSON)`
- **qa_finding** `(id, project_id, bim_element_guid?, check_id, category, issue, required_value, actual_value, difference, source_doc, page, section, severity, status, recommendation, created_at)`
- **graph_edge** `(id, project_id, src_type, src_id, relation, dst_type, dst_id)` — the knowledge graph (Door→Level, Door→Drawing, Door→ScheduleRow, Door→Spec, Door→DBC, Door→QA).
- **source_precedence** `(id, project_id, discipline, rank, source_type)` — **configurable** per project/discipline (§11).
- **doc_meta** (or new columns on `documents`) `(document_id, doc_number, revision, section, discipline, doc_date, status)`.

Migration approach: make **Alembic authoritative**; each phase ships one additive migration. No destructive changes to the 9 existing tables.

---

## 11. Proposed API structure (add alongside; keep current routes working)

Version under `/api/v1` and group by domain (existing routes keep functioning; new work lands here):

- `/api/v1/auth/*`, `/api/v1/admin/*` — reuse current auth/admin.
- `/api/v1/projects/*`, `/…/folders/*`, `/…/documents/*` — reuse current.
- `/api/v1/bim/ingest` (POST typed entities from viewer), `/bim/elements` (query/filter by level/class/guid), `/bim/elements/{guid}`.
- `/api/v1/drawings` (index/query), `/api/v1/schedules` (+ rows, + `compare` deterministic).
- `/api/v1/standards/*` (DBC/ACI/ASCE KB with revision/section/page metadata).
- `/api/v1/qa/run`, `/api/v1/qa/findings` — deterministic QA engine.
- `/api/v1/graph/{entity}/{id}` — knowledge-graph navigation.
- `/api/v1/ask` — the **question engine** (steps 1–11): retrieves typed evidence, runs deterministic comparisons, returns the **ANSWER/PROJECT DATA/CALCULATION/EVIDENCE/STATUS** envelope.
- Existing `/ask_stream`, `/ask_model`, `/upload`, viewer file serving — **unchanged**.

---

## 12. Migration risks (and mitigations)

| Risk | Mitigation |
|---|---|
| Breaking the working viewer | Re-host `viewer.js` unchanged inside the workspace; gizmo is camera-only; keep `viewer.html` as a fallback route during transition. |
| SQLite→Postgres data loss | Additive schema + Alembic; one-way migration script with a verified backup of `expo.db`; run both read paths until parity confirmed. |
| FAISS→vector-DB regressions | Keep FAISS as default; add the new store behind a flag; re-index per project and diff top-k before switching. |
| Multi-worker + in-memory cache | Move vectorstore cache to the shared store first; only then raise worker count. |
| Ollama serialization under load | Introduce the gateway+queue before advertising concurrency; `MAX_LOADED_MODELS=1` stays until multiple backends exist. |
| Scope creep across 10 phases | Ship one phase at a time; after each: test existing features, report files changed + remaining issues + a test procedure (per §27). |

---

## 13. PHASE 1 — Unified Workspace UI (pure front-end, zero backend risk)

**Goal:** one workspace shell instead of a separate 3D page — without touching the backend, the RAG, the auth, or the viewer engine.

**Scope (all in `ui/`, reusing existing pieces):**
1. **App shell with top navigation:** Home · Chat · 3D Model · Drawings · Reports · Schedules · Documents · Model Review · Automation. (Tabs that have no backend yet render a clear "coming in Phase N" placeholder — no dead ends.)
2. **Three-region layout:** LEFT project/document/KB navigation (reuse existing sidebar) · CENTER active workspace (3D / Drawing / Report / Schedule / Chat) · RIGHT AI assistant / properties / evidence.
3. **Layout modes:** Chat Focus · Split View · 3D Focus · Drawing Focus · Report Focus (collapsible panels; state remembered per user in `localStorage`).
4. **Embed the existing viewer as the CENTER "3D Model" panel** (same `viewer.js`, loaded in-place instead of a separate page). All viewer features and the coordinate pipeline stay exactly as-is.
5. **Navigation gizmo** in the viewer (TOP/BOTTOM/LEFT/RIGHT/FRONT/BACK) — **camera-only** orbit snaps; **never rotates geometry** (consistent with the Plan/True-North rule).
6. Wire the RIGHT panel's AI box to the existing `/ask_stream` (workspace chat) and `/ask_model` (when 3D is active), so chat and 3D already "work together".

**Explicitly NOT in Phase 1:** no DB changes, no new services, no Postgres, no structured BIM/drawing/schedule tables (those are Phases 2–4). Phase 1 is safe and reversible.

**Acceptance / test procedure:**
- Existing login, chat, citations, document upload, admin, and the 3D viewer (load model, sections, measure, Plan/True North, Debug, Ask AI) all still work unchanged.
- New: nav switches panels; layout modes collapse/restore; gizmo faces rotate the camera with geometry fixed; workspace chat answers via the current pipeline.
- Rollback = revert `ui/` files (backups kept per edit); backend untouched.

---

## Decisions I need from you before starting

1. **Database timeline.** Keep SQLite for Phases 1–4 and move to PostgreSQL at Phase 5/10, or move to Postgres earlier? (Driven by *when* you actually need 50–100+ concurrent users.)
2. **Vector DB target.** Proceed with **Chroma** (already in your plan) or go straight to **Qdrant/pgvector** for scale? I can keep FAISS running until the switch either way.
3. **Server-side BIM extraction.** Confirm the **browser-extracts-and-POSTs** approach for the structured BIM DB (recommended, no new server dependency), or do you want me to pursue an offline **IfcOpenShell** install on the server?
4. **Concurrency target & horizon.** Real number and date for "100+ users" — this decides how early to build the gateway/queue/Postgres vs. defer them.
5. **Approve Phase 1** (unified workspace UI + camera gizmo, front-end only) to begin — or adjust its scope first.

_Nothing will be implemented until you approve. Phase 1 is front-end only and fully reversible; it protects the working IFC viewer and local AI by design._
