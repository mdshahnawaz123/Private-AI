# MASTER ARCHITECTURE ASSESSMENT
## Private Engineering AI Platform — ExpoDesignAI

**Prepared by:** Lead Software Architect / AI Engineer / BIM Technology Architect
**Date:** 2026-09-29
**Status:** Assessment only — no code changed. Awaiting approval before any implementation.

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [Existing Components](#2-existing-components)
3. [Working Components](#3-working-components)
4. [Partial Components](#4-partial-components)
5. [Missing Components](#5-missing-components)
6. [Duplicate Components](#6-duplicate-components)
7. [Security Risks](#7-securitys-risks)
8. [Performance Risks](#8-performance-risks)
9. [Data Architecture](#9-data-architecture)
10. [AI Architecture](#10-ai-architecture)
11. [Document Processing Architecture](#11-document-processing-architecture)
12. [Retrieval Architecture](#12-retrieval-architecture)
13. [Compliance Architecture](#13-compliance-architecture)
14. [Agent Architecture](#14-agent-architecture)
15. [Recommended Target Architecture](#15-recommended-target-architecture)
16. [Migration Strategy](#16-migration-strategy)
17. [Phase 0 Implementation Plan](#17-phase-0-implementation-plan)
18. [Proposed Folder/Module Structure](#18-proposed-foldermodule-structure)
19. [Proposed Database Schema](#19-proposed-database-schema)
20. [Proposed API/Service Boundaries](#20-proposed-apiservice-boundaries)
21. [Proposed Model Registry](#21-proposed-model-registry)
22. [Proposed Admin Ingestion Workflow](#22-proposed-admin-ingestion-workflow)
23. [Proposed User Query Workflow](#23-proposed-user-query-workflow)
24. [Local Deployment Architecture](#24-local-deployment-architecture)
25. [Future Private Data Center Architecture](#25-future-private-data-center-architecture)
26. [Technology Recommendations](#26-technology-recommendations)
27. [Risks](#27-risks)
28. [Testing Strategy](#28-testing-strategy)
29. [Evaluation Strategy](#29-evaluation-strategy)
30. [First Vertical-Slice Implementation Plan](#30-first-vertical-slice-implementation-plan)

---

## 1. Current Architecture

### 1.1 System Type
A **single-process FastAPI monolith** serving both API and web UI on `http://127.0.0.1:8090`. Launched via `start.bat` → `python main.py` → `uvicorn.run(app)` — **one process, one worker**.

### 1.2 Request Flow (User Query)
```
Browser (ui/index.html)
  → POST /ask_stream {project, query, messages, k, discipline} + Bearer JWT
  → Auth middleware resolves user
  → auth.require_project enforces project access
  → retrieve_context() loads FAISS index (in-memory dict), similarity search
  → Folder-level permission filtering (server-side)
  → build_messages() assembles grounded system prompt + context + history
  → local_chat.LocalChatOllama streams tokens from Ollama /api/chat
  → Sources (file + page + revision) resolved and streamed as SSE
```

### 1.3 Document Ingestion Flow
```
Upload → categorised disk storage → background task (BackgroundTasks)
  → Deep per-page vision extraction (PDF) / openpyxl (Excel) / python-docx (Word)
  → Structured JSON per file (*.index.json)
  → Page-aware chunking → bge-m3 embeddings → FAISS index
```

### 1.4 Concurrency Ceiling
**Structural limit:** One Python process + in-memory FAISS + SQLite (single-writer) + Ollama with `OLLAMA_MAX_LOADED_MODELS=1` (inference serialized). Practical ceiling: **~1–5 concurrent reviewers**. Will not scale to 100+ without architectural changes.

### 1.5 Key Architectural Characteristics
- **No AI Orchestrator** — direct prompt + RAG → LLM pipeline
- **No model router** — single hardcoded chat model, single embed model
- **No reranker** — pure vector similarity
- **No job queue** — BackgroundTasks only (in-memory, lost on restart)
- **No deterministic validation** — LLM does 100% of compliance reasoning
- **No structured entity extraction** — text chunked as prose, not typed objects
- **Browser-side IFC parsing only** — no server-side BIM entity extraction
- **Working, battle-tested** — real project data, real users, real engineering reviews

---

## 2. Existing Components

| Module | Lines | Purpose | Status |
|---|---|---|---|
| `main.py` | ~1,400 | FastAPI app, all endpoints, RAG orchestration, upload/processing, access guards | Working, but too large |
| `db.py` | ~690 | SQLAlchemy models (9 tables) + helpers | Working, solid foundation |
| `auth.py` | ~154 | PBKDF2 hashing, JWT, role/project guards, admin seed | Working |
| `extract.py` | ~113 | Deep extraction (PyMuPDF + vision, Excel, Word) → JSON | Working |
| `vision.py` | ~97 | Local vision model calls (serialized + retry) | Working |
| `cad.py` | ~186 | DWG/DXF extraction (ezdxf + ODA) + matplotlib render | Working |
| `local_embed.py` | ~87 | Direct Ollama /api/embeddings + /api/embed batch client | Working, well-engineered |
| `local_chat.py` | ~139 | Direct Ollama /api/chat streaming client (retry-on-empty) | Working, well-engineered |
| `disciplines.py` | ~156 | Discipline registry + Architecture checklist (25 items) + reviewer prompts | Working (Architecture only) |
| `meta_parse.py` | ~145 | Drawing metadata + revision grouping from filenames | Working |
| `ui/index.html` | ~132KB | Entire web UI (chat, docs, admin, 3D launch) | Working, monolithic |
| `ui/viewer.js` | ~30KB | IFC viewer engine (web-ifc → three.js) | Working, sophisticated |
| `ui/viewer.html` | — | 3D viewer shell | Working |
| `alembic/` | — | Migration scaffold | Present, not authoritative |

---

## 3. Working Components

### 3.1 Authentication & RBAC ✅
- Local accounts with PBKDF2-SHA256 password hashing
- JWT tokens (HS256) with 12-hour TTL
- Three roles: admin, lead, user
- Project membership enforcement
- Folder-level permissions (users assigned to folders see only those folders' documents)
- Admin panel for user/project management
- Immutable audit log (SQLite triggers block UPDATE/DELETE)

### 3.2 Document Ingestion & Deep Extraction ✅
- Categorised disk storage (Drawings/3D-Models/Schedules/Reports/Images/Other)
- Background processing with live progress tracking
- PDF: PyMuPDF text + rendered page → vision model (smart mode: vision only on image-only pages)
- Excel: openpyxl sheet/row extraction
- Word: python-docx paragraphs + tables
- CAD: ezdxf data extraction + matplotlib render → vision
- Images: direct vision model reading
- Structured JSON output per file (*.index.json)
- Page-aware chunking with {source, page, folder_id} metadata

### 3.3 RAG Retrieval ✅
- FAISS vector search with bge-m3 embeddings
- Per-project indexes + shared __codes__ KB for DBC/IBC
- Folder-level permission enforcement during retrieval
- Source + page + revision resolution for citations
- k=8 context chunks per question

### 3.4 Local AI Integration ✅
- Ollama backend: qwen2.5vl:32b (chat+vision), bge-m3 (embeddings)
- Direct HTTP clients with retry/backoff (not LangChain's less reliable wrappers)
- Vision serialization (one inference at a time to prevent GPU OOM)
- Streaming SSE responses to browser
- No internet dependency at runtime

### 3.5 IFC 3D Viewer ✅
- Browser-side parsing with web-ifc (WASM)
- three.js rendering with OrbitControls
- Full IfcLocalPlacement hierarchy (Project→Site→Building→Storey→Element)
- Coordinate pipeline: COORDINATE_TO_ORIGIN, True North detection, shared world frame
- Features: model list, categories, element selection + properties, hide/isolate, section views, measure, storey plans, Ask AI
- 100% offline, no server dependency

### 3.6 Discipline System (Architecture) ✅
- 25-item Architecture checklist across 4 areas
- DBC 2021 + IBC 2021 code references
- Anti-fabrication prompt engineering
- Other disciplines scaffolded (structural, MEP, landscape, BIM, cost/VE)

### 3.7 Audit Trail ✅
- Immutable audit_log table
- Records: who, what, when, where (IP), project, target, detail
- SQLite triggers prevent UPDATE/DELETE

---

## 4. Partial Components

### 4.1 Database (Phase 2) ⚠️
- 9 tables: users, projects, chats, documents, findings, audit_log, project_members, folders, folder_members
- **Findings table exists but is empty/unused** — schema only, no writes
- **Missing tables** for: bim_model, bim_element, drawing, schedule, schedule_row, qa_finding, graph_edge, source_precedence, doc_meta
- Alembic scaffold present but `create_all` used at runtime instead
- SQLite only (Postgres supported via env var but not tested)

### 4.2 Disciplines (Phase 3) ⚠️
- Architecture: fully built with checklist + reviewer prompt
- Structural, MEP, Landscape, BIM, Cost/VE: registered with `"status": "planned"`, empty checklists, no prompts
- No code knowledge base for non-Architecture disciplines

### 4.3 Cowork Mode ⚠️
- Basic agent-like capability via `<tool>` tag protocol
- Sandboxed file operations (list/read/write/mkdir) within project workspace
- Path traversal protection
- **Not a real agent framework** — prompt-based, no planning/observation/validation loop
- Max 5 tool loops per request
- No persistent agent state

### 4.4 Report Generation ⚠️
- Dependencies installed: reportlab, jinja2, python-docx
- **Zero implementation** — no report templates, no generation pipeline

### 4.5 Vector Store ⚠️
- FAISS working but in-memory cache (lost on restart)
- Chroma installed but completely unused
- No persistent, multi-process-safe vector store

---

## 5. Missing Components

### 5.1 AI Orchestrator ❌
The **single biggest gap**. No task classification, no model routing, no evidence assembly, no deterministic calculation, no answer verification. User query goes directly to LLM with RAG chunks.

### 5.2 Compliance Engine ❌
No deterministic rule checking. LLM does 100% of compliance reasoning. No PASS/FAIL/REVIEW pipeline. No structured finding creation from automated checks.

### 5.3 Validation Engine ❌
No automated QA runs. No finding lifecycle (open → pass/fail → resolved). No batch checking. No `/qa/run` endpoint.

### 5.4 Report Engine ❌
No PDF/Excel/Word report generation. No report templates. No compliance report output.

### 5.5 Hybrid Retrieval ❌
No BM25/keyword search. No reranker. No reciprocal rank fusion. No entity-aware retrieval. Pure vector similarity only.

### 5.6 Structured Data Layer ❌
No typed entity extraction (doors, walls, rooms, schedules as objects). No knowledge graph. No source precedence system. No BIM element storage.

### 5.7 Server-Side BIM Engine ❌
No IfcOpenShell. No server-side IFC entity extraction. No Revit API integration. BIM data only exists in browser memory.

### 5.8 Job Queue ❌
No persistent job queue. BackgroundTasks are in-memory and lost on restart. No worker architecture. No retry/dead-letter handling.

### 5.9 Model Registry ❌
No model abstraction beyond two hardcoded clients. No model roles (FAST_LLM, REASONING_LLM, etc.). No model routing based on task type.

### 5.10 Evaluation Framework ❌
No formal evaluation datasets. No accuracy metrics. No model comparison framework. No citation correctness tracking.

### 5.11 OCR Engine ❌
No dedicated OCR (Tesseract, PaddleOCR, etc.). Vision model does OCR-like work but isn't specialized for it. No layout detection.

### 5.12 Drawing Intelligence Engine ❌
No drawing comparison (two revisions). No annotation/redline. No drawing-to-code automated validation.

---

## 6. Duplicate Components

### 6.1 Backup Files (Technical Debt)
- **30+ `.bak` files** across the project (main.py.bak, db.py.bak, etc.)
- **30+ `.bak` files** in ui/ (index.html.bak, viewer.js.bak, etc.)
- These are manual backups, not version control
- **Recommendation:** Initialize git repository immediately

### 6.2 LangChain vs Direct Clients
- LangChain used for: document loaders, text splitters, FAISS wrapper
- Direct HTTP clients used for: chat (local_chat.py), embeddings (local_embed.py), vision (vision.py)
- This is actually a **good pattern** — LangChain for utilities, direct clients for reliability
- Not true duplication, but worth noting the split

### 6.3 Unused Dependencies
- `chromadb` + `langchain-chroma` — installed, completely unused
- `unstructured[xlsx]` — used for Excel loading but openpyxl path also exists
- `reportlab` + `jinja2` — installed, zero implementation
- `networkx` — removed per requirements.txt comment

---

## 7. Security Risks

### 7.1 Critical
| Risk | Detail | Mitigation |
|---|---|---|
| **Default admin password** | `admin/admin` is the default if env var not set | Force password change on first login; remove default |
| **JWT secret fallback** | Falls back to `"dev-insecure-secret-change-me"` if file read fails | Fail startup if no secret configured |
| **No HTTPS** | All traffic is HTTP on localhost | Acceptable for local; required for network deployment |

### 7.2 Moderate
| Risk | Detail | Mitigation |
|---|---|---|
| **No rate limiting** | Login endpoint has no brute-force protection | Add rate limiting (slowapi or similar) |
| **No session revocation** | JWT tokens cannot be invalidated before expiry | Add token blacklist or shorter TTL |
| **File upload validation** | Extension-based only, no content validation | Add MIME type + magic byte validation |
| **CORS wildcard in dev** | `allow_methods=["*"]` and `allow_headers=["*"]` | Restrict in production |

### 7.3 Low (Acceptable for Current Stage)
- SQL injection: Protected by SQLAlchemy ORM
- XSS: UI is server-rendered HTML, limited attack surface
- Path traversal: Sandboxed cowork workspace with traversal protection
- Audit log: Immutable via SQLite triggers

### 7.4 What's Already Good
- PBKDF2-SHA256 password hashing (not bcrypt, but acceptable)
- Folder-level document isolation
- Project membership enforcement
- Sandboxed file operations
- Immutable audit trail
- No external API calls (fully offline capable)

---

## 8. Performance Risks

### 8.1 Critical
| Risk | Detail | Impact |
|---|---|---|
| **Single process** | One uvicorn worker handles all requests | Max ~5 concurrent users |
| **In-memory FAISS** | Vector index lost on restart; reload from disk is slow | Downtime on restart |
| **SQLite single-writer** | All DB writes serialize | Bottleneck under load |
| **Ollama serialization** | `OLLAMA_MAX_LOADED_MODELS=1` means one model at a time | Vision + chat cannot run concurrently |
| **No job queue** | BackgroundTasks lost on restart | Processing jobs disappear |

### 8.2 Moderate
| Risk | Detail | Impact |
|---|---|---|
| **Deep PDF vision** | Every image-only page rendered + vision-read | Slow for large drawing sets |
| **No caching** | Repeated queries re-embed and re-search | Wasted compute |
| **Large context** | k=8 chunks × 800 chars = ~6.4KB per query | May need tuning |
| **No connection pooling** | SQLite connections created per request | Minor overhead |

### 8.3 Acceptable for Current Stage
- Single-machine deployment
- Small user base (1-5 reviewers)
- Local network latency is negligible

---

## 9. Data Architecture

### 9.1 Current State
```
data/
  expo.db                     SQLite (9 tables)
  secret.key                  JWT signing secret
  logs/expo.log               Structured audit + app log
  faiss_index/<project>/      Per-project vector index (in-memory + disk)
  faiss_index/__codes__/      Shared DBC/IBC code KB
  docs/<project>/<Category>/  Original uploads + *.index.json + *.extracted.txt
  workspace/<project>/        Sandboxed cowork file tool area
  projects/                   Legacy JSON chats (migrated on first run)
```

### 9.2 Database Tables (Existing)
| Table | Purpose | Status |
|---|---|---|
| users | Local accounts with roles | Working |
| projects | Project registry | Working |
| chats | Chat history per project | Working |
| documents | Uploaded file registry | Working |
| findings | Structured review findings | **Schema only, unused** |
| audit_log | Immutable audit trail | Working |
| project_members | User-project membership | Working |
| folders | Project folders | Working |
| folder_members | User-folder assignments | Working |

### 9.3 Missing Tables (Required for Target Architecture)
| Table | Purpose | Priority |
|---|---|---|
| bim_model | IFC/Revit model registry | Phase 7 |
| bim_element | Typed BIM elements (GUID, class, properties) | Phase 7 |
| drawing | Drawing metadata (number, title, revision, discipline) | Phase 2 |
| schedule | Schedule registry | Phase 2 |
| schedule_row | Individual schedule rows with typed fields | Phase 2 |
| qa_finding | Deterministic QA findings with lifecycle | Phase 4 |
| graph_edge | Knowledge graph relationships | Phase 2 |
| source_precedence | Configurable source authority ranking | Phase 2 |
| doc_meta | Extended document metadata | Phase 2 |
| requirement | Extracted code requirements with provenance | Phase 2 |
| evidence | Typed evidence objects | Phase 2 |

### 9.4 Data Separation Assessment
| Layer | Current | Target |
|---|---|---|
| Source data | ✅ Immutable files on disk | Same |
| Processed data | ✅ *.index.json per file | Same + structured entities |
| Engineering knowledge | ❌ Not implemented | Typed entities with provenance |
| Search indexes | ✅ FAISS (in-memory) | Persistent vector DB + BM25 |
| AI models | ✅ Ollama (external) | Model registry + routing |
| Engineering rules | ❌ Not implemented | Version-controlled rule engine |
| Agent state | ⚠️ In-memory only | Persistent, separated |
| Audit data | ✅ Immutable audit_log | Same |

---

## 10. AI Architecture

### 10.1 Current State
```
User Query
  → retrieve_context() [FAISS similarity search]
  → build_messages() [system prompt + context + history]
  → local_chat.LocalChatOllama [Ollama /api/chat]
  → SSE stream to browser
```

### 10.2 Model Usage
| Role | Model | Provider | Status |
|---|---|---|---|
| Chat/Reasoning | qwen2.5vl:32b | Ollama | Working |
| Vision | qwen2.5vl:32b | Ollama | Working (same model) |
| Embeddings | bge-m3 | Ollama | Working |
| OCR | ❌ None | — | Missing |
| Layout | ❌ None | — | Missing |
| Reranker | ❌ None | — | Missing |
| Coding | ❌ None | — | Missing |

### 10.3 What Exists (Assets to Reuse)
- `local_chat.py` — Clean, model-agnostic streaming client with retry logic
- `local_embed.py` — Batch embedding client with fallback
- `vision.py` — Serialized vision calls with retry/backoff
- These are the **seeds of a proper model router**

### 10.4 What's Missing
- **Model router** — No task-based model selection
- **Model registry** — No configuration-driven model management
- **Orchestrator** — No planning, routing, verification
- **Reranker** — No cross-encoder for result refinement
- **OCR engine** — No specialized OCR (vision model does it implicitly)
- **Layout engine** — No document layout detection
- **Evaluation framework** — No accuracy measurement

---

## 11. Document Processing Architecture

### 11.1 Current Pipeline
```
Upload → File validation (extension) → Categorised storage
  → Background task:
    → PDF: PyMuPDF text + render page → vision (smart mode)
    → Excel: openpyxl sheet/row extraction
    → Word: python-docx paragraphs + tables
    → CAD: ezdxf data + matplotlib render → vision
    → Image: direct vision model
  → Structured JSON (*.index.json)
  → Page-aware chunking → bge-m3 embeddings → FAISS
```

### 11.2 Strengths
- Smart mode: vision only on image-only pages (fast for text-rich documents)
- Per-page error isolation (one bad page doesn't lose the document)
- Structured JSON output for reuse
- Page-aware metadata for citations

### 11.3 Gaps
- **No dedicated OCR** — vision model does OCR-like work but isn't specialized
- **No layout detection** — tables, figures, columns not detected as structures
- **No entity extraction** — text is prose, not typed objects (doors, walls, specs)
- **No table structure preservation** — tables become pipe-delimited text
- **No drawing comparison** — cannot compare two revisions
- **No requirement extraction** — code clauses not extracted as structured requirements

---

## 12. Retrieval Architecture

### 12.1 Current Pipeline
```
Query → FAISS similarity search (k=8) → folder permission filter → context assembly → LLM
```

### 12.2 Strengths
- Folder-level permission enforcement (server-side)
- Source + page + revision resolution
- Per-project indexes + shared code KB
- Anti-fabrication prompt engineering

### 12.3 Gaps
- **No BM25/keyword search** — misses exact clause numbers, dimension values
- **No reranker** — pure vector similarity, no cross-encoder refinement
- **No hybrid retrieval** — no fusion of vector + keyword
- **No entity-aware retrieval** — cannot query "all doors on Level 2"
- **No source precedence** — no configurable priority (spec > drawing > schedule)
- **No reciprocal rank fusion** — no combining multiple search signals

---

## 13. Compliance Architecture

### 13.1 Current State
- **Checklist exists** (25 Architecture items with IBC/DBC references)
- **LLM does all compliance reasoning** via prompt engineering
- **No deterministic checks** — no code compares actual vs. required values
- **No PASS/FAIL/REVIEW pipeline** — no structured finding creation
- **No finding lifecycle** — no open → pass/fail → resolved tracking

### 13.2 What's Needed
```
CODE REQUIREMENT (from KB)
  + DRAWING/MODEL EVIDENCE (from project)
  + DETERMINISTIC RULE (version-controlled)
  = PASS / FAIL / REVIEW
  → Evidence-backed finding
  → Professional report
```

### 13.3 Gap Summary
| Component | Status |
|---|---|
| Rule definitions | ⚠️ Scaffolded (checklist only) |
| Deterministic rule checking | ❌ Missing |
| AI-augmented compliance | ⚠️ Prompt-only |
| Finding creation from checks | ❌ Missing |
| Finding lifecycle | ❌ Missing |
| Multi-discipline | ⚠️ Architecture only |

---

## 14. Agent Architecture

### 14.1 Current State
- **Cowork mode** — basic agent-like capability via `<tool>` tag protocol
- Sandboxed file operations (list/read/write/mkdir)
- Max 5 tool loops per request
- **Not a real agent framework** — prompt-based, no planning/observation/validation

### 14.2 What's Needed
- **Planning** — task decomposition
- **Tool execution** — controlled, permission-checked
- **Observation** — structured tool results
- **Validation** — answer verification
- **Agent state** — persistent, separated from knowledge
- **Agent logging** — full audit trail

### 14.3 Gap Summary
| Component | Status |
|---|---|
| Planning | ❌ Missing |
| Tool execution | ⚠️ Basic (file ops only) |
| Observation | ⚠️ Text-based |
| Validation | ❌ Missing |
| Agent state | ❌ Missing |
| Agent logging | ❌ Missing |
| Controlled permissions | ⚠️ Path-based only |

---

## 15. Recommended Target Architecture

### 15.1 High-Level Vision
```
USER / ADMIN UI (unified workspace)
        ↓
API / APPLICATION LAYER (FastAPI, multi-worker)
        ↓
AUTHENTICATION / RBAC (existing + enhanced)
        ↓
AI ORCHESTRATOR (new)
        ↓
ENGINEERING INTELLIGENCE SERVICES
  ├── Document Intelligence (existing + enhanced)
  ├── PDF Engine (existing)
  ├── Word Engine (existing)
  ├── Excel Engine (existing)
  ├── Image Engine (existing)
  ├── OCR Engine (new)
  ├── Layout Engine (new)
  ├── CAD Engine (existing)
  ├── IFC Engine (enhanced)
  ├── Revit Engine (future)
  ├── Code / Requirement Engine (new)
  ├── Drawing Intelligence Engine (new)
  ├── Retrieval Engine (enhanced: hybrid + reranker)
  ├── Compliance Engine (new)
  ├── Validation Engine (new)
  ├── Report Engine (new)
  ├── AI Model Service (enhanced: model router)
  └── Agent Runtime (enhanced)
        ↓
ENGINEERING KNOWLEDGE HUB (new)
  ├── Structured entities (BIM, drawings, schedules, requirements)
  ├── Knowledge graph
  ├── Source precedence
  └── Provenance tracking
        ↓
PRIVATE DATA / STORAGE
  ├── PostgreSQL (replaces SQLite)
  ├── Vector DB (Chroma/Qdrant, replaces in-memory FAISS)
  ├── Object storage (disk → S3-compatible)
  ├── Job queue (Redis + Celery)
  └── Local AI (Ollama → vLLM/others)
```

### 15.2 Key Design Principles
1. **Evolution, not rewrite** — build on existing working components
2. **Interfaces over vendors** — all AI/DB/storage behind abstractions
3. **Process once, retrieve many** — heavy work at ingestion, fast at query
4. **Deterministic first, AI second** — code checks values, LLM explains
5. **Private by design** — no external API dependencies
6. **Independently testable phases** — each phase delivers working functionality

---

## 16. Migration Strategy

### 16.1 Guiding Principles
- **No big-bang rewrite** — incremental, additive changes
- **Keep existing functionality working** — each phase is independently testable
- **Backup before every change** — continue the .bak file pattern + git
- **Rollback strategy for every phase** — revert to previous working state

### 16.2 Migration Waves

**Wave 1: Foundation (Phase 0)**
- Git initialization
- Model registry abstraction
- AI Orchestrator skeleton
- Database schema extension (additive)
- No breaking changes

**Wave 2: Knowledge Hub (Phase 1-2)**
- Structured entity extraction
- Knowledge graph
- Source precedence
- Admin ingestion pipeline
- Document processing enhancements

**Wave 3: Retrieval & Compliance (Phase 3-4)**
- Hybrid retrieval (BM25 + vector + reranker)
- Deterministic compliance engine
- Validation engine
- Finding lifecycle

**Wave 4: Intelligence (Phase 5-7)**
- Drawing intelligence
- Agent orchestration
- IFC/Revit BIM engine
- Report engine

**Wave 5: Scale (Phase 8-10)**
- PostgreSQL migration
- Vector DB migration
- Multi-worker deployment
- Private data center
- Fine-tuning

### 16.3 Risk Mitigation
| Risk | Mitigation |
|---|---|
| Breaking working IFC viewer | Re-host unchanged; keep viewer.html as fallback |
| SQLite → Postgres data loss | Additive schema + Alembic; backup + migration script |
| FAISS → vector DB regressions | Keep FAISS as default; feature-flag new store; diff top-k |
| Multi-worker + in-memory cache | Move to shared store first; then raise worker count |
| Ollama serialization | Gateway + queue before advertising concurrency |
| Scope creep | One phase at a time; test after each |

---

## 17. Phase 0 Implementation Plan

### 17.1 Goal
**Architecture + Security + Model Abstraction** — establish the foundation without breaking anything.

### 17.2 Scope

#### 17.2.1 Version Control (Immediate)
- Initialize git repository
- Add `.gitignore` (exclude data/, *.bak, __pycache__, .env)
- Commit current working state as baseline
- **Eliminates 30+ .bak files** as technical debt

#### 17.2.2 Model Registry
- Create `model_registry.py` — configuration-driven model management
- Define model roles: FAST_LLM, REASONING_LLM, VISION_MODEL, OCR_MODEL, LAYOUT_MODEL, EMBEDDING_MODEL, RERANKER_MODEL, CODING_MODEL
- Each model config: name, provider, endpoint, version, quantization, context_length, capabilities, requirements, latency, enabled, status
- Wrap existing `local_chat.py` and `local_embed.py` as default providers
- **No breaking changes** — existing code continues to work

#### 17.2.3 AI Orchestrator Skeleton
- Create `orchestrator.py` — task classification, model routing, evidence assembly
- Define orchestrator interface (abstract base class)
- Implement basic query classification (compliance_check, comparison, general, calculation)
- Wire into existing `/ask_stream` endpoint as optional mode
- **Fallback to current behavior** if orchestrator fails

#### 17.2.4 Database Schema Extension
- Add new tables (additive, no changes to existing):
  - `doc_meta` — extended document metadata
  - `requirement` — extracted code requirements with provenance
  - `evidence` — typed evidence objects
  - `source_precedence` — configurable source authority
  - `graph_edge` — knowledge graph relationships
- Make Alembic authoritative for new tables
- Existing tables untouched

#### 17.2.5 Security Hardening
- Force admin password change on first login
- Add rate limiting to login endpoint
- Add file content validation (magic bytes)
- Restrict CORS in production mode
- Add health check endpoints

#### 17.2.6 API Versioning
- Create `/api/v1/` router structure
- Move existing endpoints under versioned routes (or keep as default)
- New endpoints land in versioned structure
- Existing endpoints continue working

### 17.3 Deliverables
| Deliverable | File(s) | Risk |
|---|---|---|
| Git repository | `.git/`, `.gitignore` | None |
| Model registry | `model_registry.py` | Low — new module |
| Orchestrator skeleton | `orchestrator.py` | Low — new module, optional wiring |
| DB schema extension | Alembic migration | Low — additive |
| Security hardening | `main.py`, `auth.py` | Medium — touches working code |
| API versioning | `main.py`, new routers | Medium — restructures routes |

### 17.4 Acceptance Criteria
- [ ] All existing functionality works unchanged
- [ ] Git repository initialized with clean commit history
- [ ] Model registry can list and select models by role
- [ ] Orchestrator skeleton can classify queries
- [ ] New database tables exist alongside existing ones
- [ ] Admin must change password on first login
- [ ] Health endpoints respond correctly
- [ ] All existing tests pass

---

## 18. Proposed Folder/Module Structure

```
ExpoDesignAI/
├── main.py                    # FastAPI app (slimmed down)
├── db.py                      # SQLAlchemy models (extended)
├── auth.py                    # Auth + RBAC (enhanced)
├── config.py                  # Centralized configuration (new)
│
├── core/                      # Core services (new)
│   ├── __init__.py
│   ├── orchestrator.py        # AI Orchestrator
│   ├── model_registry.py      # Model registry + routing
│   ├── audit.py               # Audit service (extracted from db.py)
│   └── security.py            # Security utilities
│
├── engines/                   # Specialized file engines (new)
│   ├── __init__.py
│   ├── base.py                # DocumentEngine interface
│   ├── pdf_engine.py          # PDF processing (wraps extract.py)
│   ├── word_engine.py         # Word processing (wraps extract.py)
│   ├── excel_engine.py        # Excel processing (wraps extract.py)
│   ├── image_engine.py        # Image processing (wraps vision.py)
│   ├── cad_engine.py          # CAD processing (wraps cad.py)
│   ├── ifc_engine.py          # IFC processing (new, server-side)
│   ├── revit_engine.py        # Revit processing (future)
│   ├── ocr_engine.py          # OCR processing (new)
│   └── layout_engine.py       # Layout detection (new)
│
├── intelligence/              # Engineering intelligence (new)
│   ├── __init__.py
│   ├── document_intelligence.py  # Document Intelligence interface
│   ├── code_engine.py         # Code/requirement extraction
│   ├── drawing_intelligence.py   # Drawing analysis
│   ├── retrieval_engine.py    # Hybrid retrieval + reranker
│   ├── compliance_engine.py   # Deterministic compliance
│   ├── validation_engine.py   # PASS/FAIL/REVIEW pipeline
│   └── report_engine.py       # Report generation
│
├── knowledge/                 # Knowledge Hub (new)
│   ├── __init__.py
│   ├── hub.py              # Engineering Knowledge Hub
│   ├── entities.py            # Typed entity models
│   ├── graph.py               # Knowledge graph
│   ├── provenance.py          # Provenance tracking
│   └── precedence.py          # Source authority/precedence
│
├── agents/                    # Agent runtime (new)
│   ├── __init__.py
│   ├── runtime.py             # Agent execution runtime
│   ├── tools.py               # Controlled tool definitions
│   ├── planning.py            # Task planning
│   └── state.py               # Agent state management
│
├── services/                  # Business services (new)
│   ├── __init__.py
│   ├── project_service.py     # Project management
│   ├── document_service.py    # Document management
│   ├── bim_service.py         # BIM data management
│   └── qa_service.py          # QA finding management
│
├── routers/                   # API routers (new)
│   ├── __init__.py
│   ├── auth.py                # Auth endpoints
│   ├── projects.py            # Project endpoints
│   ├── documents.py           # Document endpoints
│   ├── bim.py                 # BIM endpoints
│   ├── drawings.py            # Drawing endpoints
│   ├── schedules.py            # Schedule endpoints
│   ├── standards.py           # Standards endpoints
│   ├── qa.py                  # QA endpoints
│   ├── graph.py               # Knowledge graph endpoints
│   ├── ask.py                 # Question engine endpoints
│   └── admin.py               # Admin endpoints
│
├── models/                    # AI model clients (enhanced)
│   ├── __init__.py
│   ├── base.py                # Model client interface
│   ├── ollama_client.py       # Ollama (wraps local_chat/local_embed)
│   ├── vllm_client.py         # vLLM (future)
│   └── registry.py            # Model registry
│
├── extract.py                 # Existing (wrap into engines/)
├── vision.py                  # Existing (wrap into engines/)
├── cad.py                     # Existing (wrap into engines/)
├── local_chat.py              # Existing (wrap into models/)
├── local_embed.py             # Existing (wrap into models/)
├── disciplines.py             # Existing (extend)
├── meta_parse.py              # Existing (reuse)
│
├── alembic/                   # Migrations (make authoritative)
├── tests/                     # Test suite (new structure)
│   ├── unit/
│   ├── integration/
│   └── evaluation/
│
├── ui/                        # Frontend (evolve)
│   ├── index.html             # Main UI (break into components)
│   ├── viewer.html            # 3D viewer shell
│   ├── viewer.js              # IFC viewer engine (unchanged)
│   ├── components/            # UI components (new)
│   └── vendor/                # Vendored libraries (unchanged)
│
└── data/                      # Data directory (unchanged)
```

---

## 19. Proposed Database Schema

### 19.1 Existing Tables (Unchanged)
```sql
users, projects, chats, documents, findings, audit_log,
project_members, folders, folder_members
```

### 19.2 New Tables (Additive)

```sql
-- Extended document metadata
CREATE TABLE doc_meta (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    doc_number VARCHAR(200),
    revision VARCHAR(50),
    section VARCHAR(200),
    discipline VARCHAR(40),
    doc_date DATE,
    status VARCHAR(20),
    authority_level INTEGER,
    jurisdiction VARCHAR(100),
    effective_date DATE,
    applicable_scope TEXT
);

-- Extracted code requirements with provenance
CREATE TABLE requirement (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    req_id VARCHAR(100) UNIQUE,
    title TEXT,
    description TEXT,
    value TEXT,
    unit TEXT,
    source_type VARCHAR(50),      -- code, spec, bep, eir, company
    source_doc VARCHAR(400),
    source_page INTEGER,
    source_clause VARCHAR(200),
    evidence TEXT,
    confidence VARCHAR(20),
    status VARCHAR(20),           -- draft, verified, published, superseded
    version VARCHAR(50),
    authority_rank INTEGER,
    discipline VARCHAR(40),
    created_at DATETIME,
    updated_at DATETIME
);

-- Typed evidence objects
CREATE TABLE evidence (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    evidence_id VARCHAR(100) UNIQUE,
    evidence_type VARCHAR(50),    -- text, table, drawing, bim_element, schedule_row, image
    content TEXT,
    source_doc VARCHAR(400),
    source_page INTEGER,
    bounding_box JSON,
    confidence FLOAT,
    metadata JSON,
    created_at DATETIME
);

-- Source authority/precedence configuration
CREATE TABLE source_precedence (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    discipline VARCHAR(40),
    rank INTEGER,
    source_type VARCHAR(50),
    source_doc_pattern VARCHAR(400),
    effective_date DATE,
    notes TEXT
);

-- Knowledge graph edges
CREATE TABLE graph_edge (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    src_type VARCHAR(50),         -- door, wall, room, requirement, etc.
    src_id VARCHAR(100),
    relation VARCHAR(100),        -- located_in, required_by, etc.
    dst_type VARCHAR(50),
    dst_id VARCHAR(100),
    metadata JSON,
    created_at DATETIME
);

-- Drawing metadata
CREATE TABLE drawing (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    document_id INTEGER REFERENCES documents(id),
    number VARCHAR(200),
    title TEXT,
    revision VARCHAR(50),
    discipline VARCHAR(40),
    level VARCHAR(100),
    sheet VARCHAR(100),
    sheet_date DATE,
    status VARCHAR(20),
    file_path TEXT,
    page INTEGER,
    source VARCHAR(200)
);

-- Schedule registry
CREATE TABLE schedule (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    document_id INTEGER REFERENCES documents(id),
    schedule_type VARCHAR(100),
    source_sheet VARCHAR(200),
    created_at DATETIME
);

-- Schedule rows with typed fields
CREATE TABLE schedule_row (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER REFERENCES schedules(id),
    project_id INTEGER REFERENCES projects(id),
    mark VARCHAR(100),
    guid VARCHAR(100),
    fields JSON,
    created_at DATETIME
);

-- QA findings with lifecycle
CREATE TABLE qa_finding (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    finding_id VARCHAR(100) UNIQUE,
    discipline VARCHAR(40),
    severity VARCHAR(20),
    status VARCHAR(20),           -- open, review_required, verified, rejected, resolved, superseded
    check_id VARCHAR(100),
    issue TEXT,
    required_value TEXT,
    actual_value TEXT,
    difference TEXT,
    calculation TEXT,
    rule_id VARCHAR(100),
    evidence TEXT,
    source_doc VARCHAR(400),
    source_page INTEGER,
    confidence FLOAT,
    recommendation TEXT,
    created_by INTEGER REFERENCES users(id),
    verified_by INTEGER REFERENCES users(id),
    created_at DATETIME,
    updated_at DATETIME,
    revision VARCHAR(50)
);

-- BIM model registry
CREATE TABLE bim_model (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    document_id INTEGER REFERENCES documents(id),
    filename VARCHAR(400),
    ifc_schema VARCHAR(50),
    length_unit VARCHAR(20),
    true_north_deg FLOAT,
    site_origin JSON,
    coordination_matrix JSON,
    element_count INTEGER,
    created_at DATETIME
);

-- BIM elements (typed)
CREATE TABLE bim_element (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    bim_model_id INTEGER REFERENCES bim_model(id),
    guid VARCHAR(100),
    ifc_class VARCHAR(100),
    type_name VARCHAR(200),
    name VARCHAR(400),
    level VARCHAR(200),
    x FLOAT, y FLOAT, z FLOAT,
    length FLOAT, width FLOAT, height FLOAT,
    thickness FLOAT, area FLOAT, volume FLOAT,
    material VARCHAR(200),
    system VARCHAR(200),
    classification VARCHAR(200),
    psets JSON,
    created_at DATETIME
);

-- Engineering rules (version-controlled)
CREATE TABLE engineering_rule (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    rule_id VARCHAR(100) UNIQUE,
    discipline VARCHAR(40),
    category VARCHAR(100),
    title TEXT,
    description TEXT,
    rule_type VARCHAR(50),        -- deterministic, ai_assisted
    rule_definition JSON,         -- the actual rule logic
    version VARCHAR(50),
    status VARCHAR(20),           -- draft, active, deprecated
    created_at DATETIME,
    updated_at DATETIME
);

-- Evaluation datasets
CREATE TABLE eval_dataset (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200),
    description TEXT,
    dataset_type VARCHAR(50),     -- ocr, extraction, retrieval, compliance, etc.
    created_at DATETIME
);

CREATE TABLE eval_example (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER REFERENCES eval_dataset(id),
    input TEXT,
    expected_output TEXT,
    source TEXT,
    verification_status VARCHAR(20),
    created_at DATETIME
);
```

---

## 20. Proposed API/Service Boundaries

### 20.1 API Versioning
All new endpoints under `/api/v1/`. Existing endpoints continue working at root level (or moved under versioned routes with redirects).

### 20.2 Endpoint Structure

```
/api/v1/
├── auth/
│   ├── POST /login
│   ├── POST /logout
│   ├── POST /change-password
│   └── GET  /me
│
├── admin/
│   ├── GET    /users
│   ├── POST   /users
│   ├── PUT    /users/{id}/role
│   ├── PUT    /users/{id}/active
│   └── GET    /audit
│
├── projects/
│   ├── GET    /
│   ├── POST   /
│   ├── GET    /{project}
│   ├── PUT    /{project}/discipline
│   ├── GET    /{project}/folders
│   ├── POST   /{project}/folders
│   ├── GET    /{project}/documents
│   ├── POST   /{project}/upload
│   ├── POST   /{project}/rebuild
│   └── DELETE /{project}/docs
│
├── bim/
│   ├── POST   /ingest              # Receive typed entities from viewer
│   ├── GET    /elements            # Query/filter by level/class/guid
│   ├── GET    /elements/{guid}
│   └── GET    /models
│
├── drawings/
│   ├── GET    /                    # List drawings
│   ├── GET    /{id}                # Get drawing metadata
│   └── GET    /{id}/compare        # Compare two revisions
│
├── schedules/
│   ├── GET    /                    # List schedules
│   ├── GET    /{id}                # Get schedule with rows
│   └── POST   /compare             # Deterministic comparison
│
├── standards/
│   ├── GET    /                    # List code documents
│   ├── POST   /upload              # Upload code document
│   ├── GET    /requirements        # Query requirements
│   └── GET    /requirements/{id}
│
├── qa/
│   ├── POST   /run                 # Run QA checks
│   ├── GET    /findings            # List findings
│   ├── GET    /findings/{id}       # Get finding detail
│   ├── PUT    /findings/{id}       # Update finding (verify/reject)
│   └── GET    /rules               # List engineering rules
│
├── graph/
│   └── GET    /{entity}/{id}       # Knowledge graph navigation
│
├── ask/
│   ├── POST   /stream              # Question engine (orchestrator)
│   ├── POST   /model               # Model-grounded Q&A (existing)
│   └── POST   /image               # Vision Q&A (existing)
│
└── reports/
    ├── POST   /generate            # Generate report
    ├── GET    /{id}                # Get report
    └── GET    /{id}/download       # Download report
```

### 20.3 Service Boundaries
| Service | Responsibility | Dependencies |
|---|---|---|
| Orchestrator | Task classification, model routing, evidence assembly | Model Registry, Retrieval, Compliance |
| Model Registry | Model configuration, routing, health | Model clients |
| Retrieval Engine | Hybrid search, reranking | Vector DB, BM25, Metadata |
| Compliance Engine | Deterministic rule checking | Rules, Requirements, Evidence |
| Validation Engine | Finding lifecycle, PASS/FAIL/REVIEW | Compliance, Findings |
| Report Engine | Report generation | Findings, Templates, Evidence |
| Knowledge Hub | Entity storage, graph, provenance | PostgreSQL, Graph |
| Agent Runtime | Controlled agent execution | Tools, Orchestrator, State |

---

## 21. Proposed Model Registry

### 21.1 Model Roles
| Role | Purpose | Current | Target |
|---|---|---|---|
| FAST_LLM | Quick responses, simple queries | — | qwen2.5:7b or similar |
| REASONING_LLM | Complex reasoning, analysis | qwen2.5vl:32b | Configurable |
| VISION_MODEL | Image/drawing analysis | qwen2.5vl:32b | Configurable |
| OCR_MODEL | Text extraction from images | — | PaddleOCR-VL or similar |
| LAYOUT_MODEL | Document layout detection | — | PP-DocLayout or similar |
| EMBEDDING_MODEL | Text embeddings | bge-m3 | Configurable |
| RERANKER_MODEL | Result refinement | — | bge-reranker-v2-m3 or similar |
| CODING_MODEL | Code generation | — | Configurable |

### 21.2 Model Configuration Schema
```python
{
    "role": "REASONING_LLM",
    "name": "qwen2.5vl:32b",
    "provider": "ollama",
    "endpoint": "http://127.0.0.1:11434",
    "version": "latest",
    "quantization": "Q4_K_M",
    "context_length": 32768,
    "capabilities": ["chat", "vision", "reasoning"],
    "gpu_requirements": {"vram_gb": 20},
    "cpu_requireable": true,
    "expected_latency_ms": 500,
    "enabled": true,
    "status": "active",
    "priority": 1
}
```

### 21.3 Provider Abstraction
```python
class ModelProvider(ABC):
    @abstractmethod
    def chat(self, messages, **kwargs) -> str: ...
    
    @abstractmethod
    def stream(self, messages, **kwargs) -> Iterator[str]: ...
    
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]: ...
    
    @abstractmethod
    def vision(self, image: str, prompt: str) -> str: ...
    
    @abstractmethod
    def health(self) -> Tuple[bool, dict]: ...
```

### 21.4 Routing Logic
```python
class ModelRouter:
    def route(self, task_type: str, complexity: str, 
              requires_vision: bool, latency_requirement: str) -> ModelConfig:
        # Select best model based on task requirements
        # Consider: capabilities, latency, GPU availability, enabled status
        ...
```

---

## 22. Proposed Admin Ingestion Workflow

### 22.1 Pipeline
```
UPLOAD
  ↓
FILE VALIDATION (extension, size, content-type, magic bytes)
  ↓
FILE CLASSIFICATION (auto-detect: drawing, schedule, report, model, image)
  ↓
DUPLICATE CHECK (SHA-256 hash → existing document?)
  ↓
SPECIALIZED ENGINE (PDF/Word/Excel/CAD/Image/IFC/Revit)
  ↓
DEEP EXTRACTION (text, tables, entities, requirements)
  ↓
LAYOUT / OCR IF REQUIRED (detected automatically)
  ↓
ENTITY EXTRACTION (typed objects: doors, walls, rooms, specs)
  ↓
REQUIREMENT EXTRACTION (code clauses → structured requirements)
  ↓
RELATIONSHIP EXTRACTION (entity → document → requirement links)
  ↓
QUALITY CHECK (confidence scoring, completeness)
  ↓
PROVENANCE CREATION (source, version, page, confidence)
  ↓
INDEXING (vector + BM25 + entity + metadata)
  ↓
VERSIONING (document version, requirement version)
  ↓
VERIFICATION (human review for low-confidence items)
  ↓
PUBLISH (make available for user queries)
  ↓
READY
```

### 22.2 Document States
```
UPLOADED → PROCESSING → REVIEW_REQUIRED → VERIFIED → PUBLISHED
                                                    ↓
                                                ARCHIVED
                                                    ↓
                                                SUPERSEDED
```

### 22.3 Key Principles
- **Process once, retrieve many** — heavy work at ingestion
- **Never silently overwrite** — new version creates new document record
- **Provenance always** — every extracted fact links to source
- **Human verification for low-confidence** — flag uncertain extractions
- **Indexes rebuildable** — from source + processed data

---

## 23. Proposed User Query Workflow

### 23.1 Simple Query (Text Only)
```
USER: "What is the required corridor width?"
  ↓
QUERY CLASSIFICATION (general_qa)
  ↓
RETRIEVE REQUIREMENT (hybrid: BM25 + vector + reranker)
  ↓
RETRIEVE SOURCE (document + page + clause)
  ↓
RETURN ANSWER + CITATION
```

### 23.2 Compliance Query
```
USER: "Is the door on Level 2 compliant?"
  ↓
QUERY CLASSIFICATION (compliance_check)
  ↓
RETRIEVE REQUIREMENT (code clause for door width)
  ↓
RETRIEVE DRAWING EVIDENCE (door schedule, drawing)
  ↓
MEASURE / COMPARE (deterministic calculation)
  ↓
VALIDATION (PASS / FAIL / REVIEW)
  ↓
ANSWER + SOURCE + EVIDENCE + CALCULATION
```

### 23.3 Image/Screenshot Query
```
USER: [uploads door screenshot] "Is this door compliant?"
  ↓
VISION ANALYSIS (identify door, extract dimensions)
  ↓
IDENTIFY DRAWING / LOCATION / TAG
  ↓
RETRIEVE REQUIREMENT (code clause)
  ↓
RETRIEVE DRAWING EVIDENCE (door schedule, drawing)
  ↓
MEASURE / COMPARE (deterministic)
  ↓
VALIDATION (PASS / FAIL / REVIEW)
  ↓
ANSWER + SOURCE + EVIDENCE
```

### 23.4 BIM Query
```
USER: [in 3D viewer] "How many columns on Level 3?"
  ↓
QUERY CLASSIFICATION (model_qa)
  ↓
RETRIEVE MODEL DATA (from browser-extracted BIM data)
  ↓
DETERMINISTIC ANSWER (count, filter, sum)
  ↓
RETURN ANSWER + MODEL REFERENCE
```

---

## 24. Local Deployment Architecture

### 24.1 Current (Single Machine)
```
┌─────────────────────────────────────────────┐
│                  MACHINE                     │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │  Browser    │    │  Ollama Server   │    │
│  │  (UI)       │    │  - qwen2.5vl:32b │    │
│  │             │    │  - bge-m3        │    │
│  └──────┬──────┘    └────────┬─────────┘    │
│         │                    │               │
│         │    ┌───────────────▼─────────┐    │
│         │    │                         │    │
│         └────│    FastAPI Server       │    │
│              │    (main.py)            │    │
│              │    - API + UI           │    │
│              │    - RAG orchestration  │    │
│              │    - Document processing│    │
│              │                         │    │
│              └───────────┬─────────────┘    │
│                          │                   │
│              ┌───────────▼─────────────┐    │
│              │    SQLite + FAISS       │    │
│              │    (data/)              │    │
│              └─────────────────────────┘    │
│                                              │
└─────────────────────────────────────────────┘
```

### 24.2 Phase 0-2 (Enhanced Single Machine)
```
┌─────────────────────────────────────────────┐
│                  MACHINE                     │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │  Browser    │    │  Ollama Server   │    │
│  │  (UI)       │    │  - qwen2.5vl:32b │    │
│  │             │    │  - bge-m3        │    │
│  │             │    │  - bge-reranker  │    │
│  └──────┬──────┘    └────────┬─────────┘    │
│         │                    │               │
│         │    ┌───────────────▼─────────┐    │
│         └────│    FastAPI Server       │    │
│              │    (multi-worker)       │    │
│              │    - API + UI           │    │
│              │    - AI Orchestrator    │    │
│              │    - Model Router       │    │
│              │    - Compliance Engine  │    │
│              │                         │    │
│              └───────────┬─────────────┘    │
│                          │                   │
│              ┌───────────▼─────────────┐    │
│              │  PostgreSQL + Chroma    │    │
│              │  (data/)                │    │
│              └─────────────────────────┘    │
│                                              │
└─────────────────────────────────────────────┘
```

### 24.3 Configuration
- All paths relative to `EXPO_DATA_DIR`
- All endpoints configurable via environment variables
- No hardcoded machine-specific paths
- No single-process assumptions in new code

---

## 25. Future Private Data Center Architecture

### 25.1 Target State
```
┌─────────────────────────────────────────────────────────────┐
│                    PRIVATE NETWORK                           │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  User 1  │  │  User 2  │  │  User 3  │  │  User N  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │              │              │              │          │
│       └──────────────┴──────────────┴──────────────┘          │
│                          │                                    │
│                   ┌──────▼──────┐                            │
│                   │ API Gateway │                            │
│                   │ (reverse    │                            │
│                   │  proxy +    │                            │
│                   │  load bal.) │                            │
│                   └──────┬──────┘                            │
│                          │                                    │
│       ┌──────────────────┼──────────────────┐                │
│       │                  │                  │                │
│  ┌────▼─────┐     ┌─────▼──────┐    ┌─────▼──────┐         │
│  │ FastAPI  │     │  FastAPI   │    │  FastAPI   │         │
│  │ Worker 1 │     │  Worker 2  │    │  Worker N  │         │
│  │          │     │            │    │            │         │
│  │ - API    │     │ - API      │    │ - API      │         │
│  │ - Orch.  │     │ - Orch.    │    │ - Orch.    │         │
│  │ - RAG    │     │ - RAG      │    │ - RAG      │         │
│  └────┬─────┘     └─────┬──────┘    └─────┬──────┘         │
│       │                  │                  │                │
│       └──────────────────┼──────────────────┘                │
│                          │                                    │
│  ┌───────────────────────▼───────────────────────────────┐   │
│  │              AI ORCHESTRATOR LAYER                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │  │   Model     │  │  Compliance │  │   Agent     │   │   │
│  │  │   Router    │  │   Engine    │  │   Runtime   │   │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │   │
│  └─────────┼────────────────┼────────────────┼──────────┘   │
│            │                │                │               │
│  ┌─────────▼────────────────▼────────────────▼──────────┐   │
│  │           ENGINEERING KNOWLEDGE HUB                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │   │
│  │  │PostgreSQL│  │  Vector  │  │  Object  │           │   │
│  │  │          │  │  DB      │  │  Storage │           │   │
│  │  │- entities│  │(Chroma/  │  │  (S3)    │           │   │
│  │  │- graph   │  │ Qdrant)  │  │          │           │   │
│  │  │- audit   │  │          │  │- docs    │           │   │
│  │  │- rules   │  │- vectors │  │- models  │           │   │
│  │  │- findings│  │- bm25    │  │- renders │           │   │
│  │  └──────────┘  └──────────┘  └──────────┘           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              AI INFRASTRUCTURE                         │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │   │
│  │  │  Ollama  │  │  vLLM    │  │  GPU     │           │   │
│  │  │  Server  │  │  Server  │  │  Nodes   │           │   │
│  │  │          │  │  (future)│  │          │           │   │
│  │  │- LLM     │  │          │  │- A100    │           │   │
│  │  │- Vision  │  │          │  │- H100    │           │   │
│  │  │- Embed   │  │          │  │          │           │   │
│  │  └──────────┘  └──────────┘  └──────────┘           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              JOB QUEUE + WORKERS                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │   │
│  │  │  Redis   │  │  Celery  │  │  Celery  │           │   │
│  │  │  Queue   │  │  Worker  │  │  Worker  │           │   │
│  │  │          │  │  (docs)  │  │  (AI)    │           │   │
│  │  └──────────┘  └──────────┘  └──────────┘           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 25.2 Separation of Concerns
| Layer | Scaling | Technology |
|---|---|---|
| Application | Horizontal | FastAPI + Gunicorn/Uvicorn |
| AI Inference | Horizontal | Ollama/vLLM + GPU nodes |
| Document Processing | Horizontal | Celery workers |
| Database | Vertical → HA | PostgreSQL + read replicas |
| Vector Search | Horizontal | Qdrant cluster |
| Object Storage | Horizontal | S3-compatible (MinIO) |
| Job Queue | Horizontal | Redis cluster |

### 25.3 Network Isolation
- All services on private network
- No outbound internet access
- API Gateway is single entry point
- Internal service-to-service communication only
- All data encrypted at rest and in transit

---

## 26. Technology Recommendations

### 26.1 Keep (Proven, Working)
| Technology | Reason |
|---|---|
| FastAPI | Solid, async, well-known |
| SQLAlchemy | Flexible, supports SQLite → Postgres |
| FAISS | Working, fast, sufficient for current scale |
| Ollama | Working, local, model-agnostic |
| bge-m3 | Good embedding model |
| qwen2.5vl:32b | Working vision + chat |
| ezdxf | Working CAD extraction |
| PyMuPDF | Working PDF extraction |
| web-ifc + three.js | Working IFC viewer |
| PBKDF2 + JWT | Working auth |
| loguru | Good logging |

### 26.2 Add (Phase 0-2)
| Technology | Purpose | Priority |
|---|---|---|
| rank-bm25 | BM25 keyword search | High |
| bge-reranker-v2-m3 | Reranking | High |
| Alembic (authoritative) | Database migrations | High |
| Pydantic-settings | Configuration management | Medium |
| slowapi | Rate limiting | Medium |

### 26.3 Evaluate (Phase 3-5)
| Technology | Purpose | Criteria |
|---|---|---|
| Chroma | Persistent vector DB | Multi-worker safe, project-partitioned |
| Qdrant | Alternative vector DB | Better at scale, more complex |
| PaddleOCR-VL | Dedicated OCR | Accuracy vs. vision model |
| PP-DocLayout | Layout detection | Table/figure/column detection |
| IfcOpenShell | Server-side IFC | Offline wheel availability |
| Redis + Celery | Job queue | Persistent, retry, dead-letter |

### 26.4 Future (Phase 6-10)
| Technology | Purpose |
|---|---|
| PostgreSQL | Production database |
| vLLM | Alternative inference backend |
| MinIO | S3-compatible object storage |
| Kubernetes | Container orchestration |
| Prometheus + Grafana | Observability |
| Keycloak | Enterprise SSO/LDAP |

### 26.5 Avoid (For Now)
| Technology | Reason |
|---|---|
| OpenAI/Anthropic/Google APIs | Violates private AI requirement |
| Fine-tuning | Not until evaluation datasets are mature |
| LangChain agents | Too heavy, use custom orchestrator |
| Heavy frameworks | Keep it simple, proven working |

---

## 27. Risks

### 27.1 Technical Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking working IFC viewer | Low | Critical | Re-host unchanged; keep fallback |
| SQLite → Postgres migration issues | Medium | High | Additive schema; backup; dual-read |
| FAISS → vector DB regressions | Medium | High | Feature-flag; diff top-k before switch |
| Ollama single-model limitation | High | Medium | Gateway + queue; multiple backends |
| Scope creep across 10 phases | High | Medium | One phase at a time; test after each |
| Model accuracy insufficient | Medium | High | Evaluation framework; human review |
| No internet for package installs | Medium | Medium | Pre-staged wheels; air-gapped pack |

### 27.2 Architectural Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| main.py grows too large | High | Medium | Extract routers incrementally |
| In-memory state lost on restart | High | Medium | Move to persistent stores |
| Single point of failure | High | Medium | Multi-worker + shared stores |
| Data loss from failed jobs | Medium | High | Persistent job queue |
| Knowledge graph complexity | Medium | Medium | Start simple; add complexity as needed |

### 27.3 Organizational Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| No version control | High | Critical | Git init immediately |
| Backup file proliferation | High | Medium | Git + proper .gitignore |
| Knowledge loss (bus factor) | Medium | High | Documentation + git |
| Unrealistic timeline expectations | Medium | Medium | Clear phase deliverables |

---

## 28. Testing Strategy

### 28.1 Test Levels
| Level | Scope | Tools |
|---|---|---|
| Unit | Individual functions/modules | pytest |
| Integration | API endpoints + DB + AI | pytest + httpx |
| End-to-End | Full user workflows | Manual + automated UI tests |
| Evaluation | AI accuracy against datasets | Custom eval framework |
| Performance | Load, latency, concurrency | locust or similar |

### 28.2 Test Organization
```
tests/
├── unit/
│   ├── test_orchestrator.py
│   ├── test_model_registry.py
│   ├── test_compliance.py
│   ├── test_retrieval.py
│   └── test_extraction.py
├── integration/
│   ├── test_api.py
│   ├── test_auth.py
│   ├── test_documents.py
│   └── test_bim.py
├── e2e/
│   ├── test_admin_ingestion.py
│   ├── test_user_query.py
│   └── test_compliance_workflow.py
└── evaluation/
    ├── test_ocr_accuracy.py
    ├── test_retrieval_accuracy.py
    └── test_citation_correctness.py
```

### 28.3 Continuous Testing
- Run unit tests on every commit
- Run integration tests before merging
- Run evaluation tests before model changes
- Run E2E tests before releases

---

## 29. Evaluation Strategy

### 29.1 Metrics
| Category | Metric | Target |
|---|---|---|
| OCR | Character accuracy, word accuracy | > 95% |
| Layout | Table detection F1, figure detection F1 | > 90% |
| Extraction | Entity extraction precision/recall | > 85% |
| Retrieval | Hit rate@k, MRR, NDCG | > 80% |
| Citation | Citation correctness | > 95% |
| Compliance | False negative rate | < 5% |
| Response | Answer accuracy (human eval) | > 85% |
| Latency | P50, P95, P99 response time | P95 < 5s |

### 29.2 Evaluation Datasets
| Dataset | Purpose | Status |
|---|---|---|
| Drawing understanding | Test drawing comprehension | To create |
| OCR accuracy | Test text extraction | To create |
| Dimension extraction | Test measurement extraction | To create |
| Code requirement extraction | Test clause extraction | To create |
| Drawing issue classification | Test issue detection | To create |
| BIM QA | Test model queries | To create |
| Compliance findings | Test deterministic checks | To create |

### 29.3 Evaluation Process
1. Create verified test datasets from engineering examples
2. Run evaluation before every model change
3. Compare results against baseline
4. Only deploy if metrics improve or stay equal
5. Track metrics over time

### 29.4 Model Selection Process
1. Define evaluation criteria (accuracy, latency, resource usage)
2. Run evaluation dataset against candidate models
3. Compare results
4. Select best model for each role
5. Document decision and rationale

---

## 30. First Vertical-Slice Implementation Plan

### 30.1 Goal
Prove one complete workflow end-to-end:
```
Admin uploads building code + architectural drawing
  → Document processing
  → Requirement extraction
  → Drawing evidence extraction
  → Knowledge Hub
  → Hybrid retrieval
  → Deterministic compliance rule
  → PASS / FAIL / REVIEW
  → Evidence-backed finding
  → Professional report
```

### 30.2 Scope
**Narrow enough to complete, broad enough to prove the architecture.**

### 30.3 Steps

#### Step 1: Foundation (Phase 0)
- Git init + .gitignore
- Model registry skeleton
- Orchestrator skeleton
- DB schema extension (additive)
- Security hardening

#### Step 2: Structured Extraction (Phase 1-2)
- Extend extract.py to produce typed entities
- Create requirement extraction from code documents
- Create evidence objects with provenance
- Wire into Knowledge Hub tables

#### Step 3: Hybrid Retrieval (Phase 3)
- Add BM25 alongside FAISS
- Implement reciprocal rank fusion
- Add reranker (bge-reranker-v2-m3)
- Wire into retrieval engine

#### Step 4: Deterministic Compliance (Phase 4)
- Implement compliance engine with rule checking
- Create PASS/FAIL/REVIEW pipeline
- Wire findings table to actual checks
- Implement finding lifecycle

#### Step 5: Report Generation (Phase 4)
- Create report templates (Jinja2)
- Implement PDF generation (reportlab or weasyprint)
- Include evidence and source references

#### Step 6: User Query (Phase 3)
- Wire orchestrator into /ask_stream
- Implement query classification
- Implement evidence assembly
- Return structured answer envelope

### 30.4 Deliverables
| Deliverable | Description |
|---|---|
| Working compliance check | Upload code + drawing → get PASS/FAIL/REVIEW |
| Evidence-backed finding | Finding with source, page, calculation, confidence |
| Professional report | PDF report with findings and evidence |
| User query | Ask question → get answer with citation |

### 30.5 Acceptance Criteria
- [ ] Admin can upload DBC PDF and architectural drawing
- [ ] System extracts requirements from DBC
- [ ] System extracts drawing evidence
- [ ] User asks "What is the required corridor width?"
- [ ] System returns answer with citation
- [ ] User asks "Is this corridor compliant?"
- [ ] System runs deterministic check
- [ ] System returns PASS/FAIL/REVIEW with evidence
- [ ] System generates PDF report
- [ ] All existing functionality still works

### 30.6 Timeline Estimate
| Phase | Duration | Dependencies |
|---|---|---|
| Phase 0: Foundation | 1-2 weeks | None |
| Phase 1-2: Structured Extraction | 2-3 weeks | Phase 0 |
| Phase 3: Hybrid Retrieval | 1-2 weeks | Phase 0 |
| Phase 4: Compliance + Reports | 2-3 weeks | Phase 1-3 |
| **Total** | **6-10 weeks** | |

---

## Appendices

### A. File Inventory
| File | Lines | Status |
|---|---|---|
| main.py | ~1,400 | Working, needs splitting |
| db.py | ~690 | Working, needs extension |
| auth.py | ~154 | Working |
| extract.py | ~113 | Working, needs enhancement |
| vision.py | ~97 | Working |
| cad.py | ~186 | Working |
| local_embed.py | ~87 | Working, wrap into model registry |
| local_chat.py | ~139 | Working, wrap into model registry |
| disciplines.py | ~156 | Working (Architecture only) |
| meta_parse.py | ~145 | Working |
| ui/index.html | ~132KB | Working, needs componentization |
| ui/viewer.js | ~30KB | Working, do not touch |

### B. Dependencies (Current)
```
fastapi, uvicorn[standard], python-multipart
sqlalchemy, alembic
langchain, langchain-community, langchain-ollama, langchain-text-splitters, langchain-core
faiss-cpu, chromadb, langchain-chroma
pypdf, pdfplumber, docx2txt, python-docx, openpyxl, unstructured[xlsx], Pillow, pymupdf, ezdxf, matplotlib
pandas, tabulate
pydantic-settings, python-dotenv, httpx, loguru
jinja2, reportlab
passlib, python-jose[cryptography]
```

### C. Environment Variables
```
EXPO_HOST, EXPO_PORT, EXPO_CORS_ORIGINS
EXPO_DATABASE_URL, EXPO_DATA_DIR
EXPO_ADMIN_PASSWORD, EXPO_SECRET, EXPO_TOKEN_HOURS
EXPO_VISION_MODEL, OLLAMA_HOST, EXPO_KEEP_ALIVE, EXPO_VISION_RETRIES
EXPO_EMBED_MODEL, EXPO_EMBED_RETRIES, EXPO_EMBED_TIMEOUT, EXPO_EMBED_BATCH
EXPO_NUM_CTX, EXPO_CHAT_RETRIES
EXPO_ODA_CONVERTER
```

---
