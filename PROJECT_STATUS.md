# Expo Design AI — Project Status & Handover

_Last updated: 2026-09-25_

A company-owned, **100% offline** AI platform for daily engineering design reviews.
Runs entirely on the local machine via **Ollama** — no project data ever leaves the
organisation. Multi-user, project-scoped, role-based, and auditable.

Disciplines targeted: **Structural · Architecture · MEP · Landscape · BIM · Cost/VE**
(Architecture is fully built against **DBC 2021 + IBC 2021**; the others are scaffolded.)

---

## 1. Tech stack

| Layer | Technology |
|---|---|
| API / server | FastAPI + Uvicorn (`main.py`), served on **port 8090** |
| Database | SQLite via SQLAlchemy (`data/expo.db`); Alembic scaffold present |
| Vector search | FAISS (per-project + shared code KB) |
| Local AI | Ollama — LLM `qwen3.8:27b`, embeddings `bge-m3`, vision `qwen2.5vl:7b` |
| Auth | Local accounts, PBKDF2-SHA256 hashing, JWT tokens |
| Frontend | Single file `ui/index.html` (served by the backend at `/ui/`) |

### Code modules
- `main.py` — API, endpoints, upload/processing orchestration, access guards
- `db.py` — SQLAlchemy models + helpers (users, projects, chats, documents, findings, audit, membership)
- `auth.py` — password hashing, JWT, role/project guards, admin seeding
- `disciplines.py` — discipline registry + Architecture checklist + reviewer prompts
- `vision.py` — local vision-model calls (image/drawing reading)
- `cad.py` — DWG/DXF extraction (ezdxf + ODA) and matplotlib rendering
- `extract.py` — deep extraction (PyMuPDF per-page + vision, Excel, Word) → structured JSON
- `ui/index.html` — the whole web UI

### Data layout (`data/`)
```
data/
  expo.db                     SQLite (users, projects, chats, documents, audit_log, ...)
  secret.key                  JWT signing secret (auto-generated)
  logs/expo.log               structured audit + app log (loguru)
  faiss_index/<project>/      per-project vector index
  faiss_index/__codes__/      shared DBC/IBC code knowledge base
  docs/<project>/Drawings/    original uploads, filed by category
             /3D-Models/
             /Schedules/
             /Reports/
             /Images/
             /Other/
  docs/<project>/<file>.index.json    structured extraction per document
  workspace/<project>/        sandboxed area for the "cowork" file tool
  projects/                   legacy JSON chats (migrated into DB on first run)
```

---

## 2. What has been built

### Phase 1 — Security hardening (no login yet)
- **Sandboxed** the "cowork" file tool (was able to read/write anywhere on disk → now confined to `data/workspace/<project>/`).
- CORS locked to the served origin (was wildcard `*`).
- UI now served by the backend; launchers open `http://127.0.0.1:8090/ui/`.
- Env-based config (`EXPO_PORT`, `EXPO_HOST`, `EXPO_CORS_ORIGINS`).

### Phase 2 — Database + immutable audit trail
- SQLAlchemy models: `users`, `projects`, `chats`, `documents`, `findings`, `audit_log`.
- Loose JSON chats **auto-migrated** into the DB on first run.
- **Immutable audit log** (SQLite triggers block UPDATE/DELETE) — who did what, when.
- `loguru` structured logging; Alembic scaffold (`alembic/`). App uses `create_all` today.

### Phase 3 — Disciplines + code knowledge base (Architecture)
- Architecture reviewer grounded in **DBC 2021 + IBC 2021** with a **25-item checklist**
  across Means of Egress, Accessibility, Occupancy/Area/Height, Fire-resistance/Finish.
- Checklist gives *structure only* — real clause requirements come from the uploaded codes via RAG.
- **Shared code knowledge base** (`__codes__`) for DBC/IBC PDFs, retrieved alongside project docs.
- Reviewer prompt enforces a **no-fabrication rule** (never invents clause numbers; marks "not found").
- UI discipline dropdown; other disciplines scaffolded ("coming soon").
- _Chroma migration deferred — still on FAISS._

### Vision + CAD
- Local **vision model** reads images and drawings (verbatim transcription, marks `[illegible]`, temperature 0).
- **DWG/DXF**: ezdxf pulls text/layers/blocks/dimensions; matplotlib renders sheets → read by vision. DWG needs the free **ODA File Converter**; DXF works directly.

### Phase 5 — Login, roles, access control
- **Local accounts** (username + PBKDF2 hash), **JWT** login, tokens in browser storage.
- Roles: **admin** (everything), **lead** (upload + manage own projects), **user** (query only).
- **Project membership** — users only see/query projects assigned to them; admin sees all.
- All endpoints access-controlled; audit records the acting user.
- **Admin panel**: create users, assign users to projects (dropdowns), user list with role pills.
- Login gate + logout; default first admin is **`admin` / `admin`** (change it!).

### Document library + deep extraction
- **Categorised storage** on disk (Drawings / 3D-Models / Schedules / Reports / Images / Other).
- Clear **Upload** button (separate from chat) + **Documents** tab + **sidebar Knowledge Base list (admin-only)**.
- **Deep extraction** (background job, non-blocking): every PDF page rendered + vision-read; Excel sheets/rows; Word paragraphs/tables; images/DWG via vision. Output stored as **structured JSON** per file.
- **Live status + progress** ("Processing 34/151") → **AI-indexed** when ready.
- **Multi-format preview**: PDF/image native inline; Excel as tables; Word as text; DWG as rendered images; everything else via its JSON. **Open original** always pulls the real file.
- Retrieval widened to **k = 8** context chunks per question.

### UI polish
- Claude-style composer: multi-file attach chips, drag-and-drop, **paste a screenshot**.
- Message headers with **sender + timestamp** (live + streaming).
- Modern admin panel; `.env` now actually loaded (via python-dotenv).

---

## 3. How to run

1. Install [Ollama](https://ollama.com) and Python 3.10+.
2. Double-click **`start.bat`** — it installs `requirements.txt`, pulls the three models
   (`qwen3.8:27b`, `bge-m3`, `qwen2.5vl:7b`), starts the backend on **8090**, and opens the UI.
3. Sign in as **`admin` / `admin`** → **change the password**.
4. Create a project → **Upload files** (drawings/schedules/reports) → wait for **AI-indexed**.
5. **Admin** → create users → assign them to projects. Users log in and chat, scoped to their projects.

**For DWG**: install the free **ODA File Converter** (set `EXPO_ODA_CONVERTER` if not auto-found).

### Config (`.env`, copy from `.env.example`)
`EXPO_PORT` · `EXPO_HOST` · `EXPO_CORS_ORIGINS` · `EXPO_DATABASE_URL` · `EXPO_ADMIN_PASSWORD`
`EXPO_SECRET` · `EXPO_VISION_MODEL` · `OLLAMA_HOST` · `EXPO_ODA_CONVERTER` · `EXPO_DATA_DIR`

### Tests (run on the machine, deps installed)
`python test_phase2.py` · `test_phase3.py` · `test_phase5.py` · `test_extract.py` · `test_cad.py`

---

## 4. Known limitations / caveats

- **Deep PDF vision is slow** on large drawing sets (runs in background; watch the progress badge).
- **3D models** are stored + downloadable but **not parsed** and have **no in-browser viewer**.
- Still on **FAISS**; **Chroma** migration not done. `chromadb`/`langchain-chroma` are installed but unused.
- Retrieval is top-k (k=8), **not** a full-document map-reduce — very broad "review everything" questions still see only the most relevant chunks.
- **Timestamps** show render time; they are **not persisted** per message yet.
- **Only Architecture** is fully built; Structural/MEP/Landscape/BIM/Cost-VE are placeholders.
- **Report generation** (`reportlab`/`jinja2`) is **not built** yet (Phase 4 of the original plan).
- **No per-file delete** in the UI (only "clear all docs" per project).
- **No change-password button** in the UI yet (endpoint exists: `POST /auth/change-password`).
- Vision accuracy = the local model's accuracy; critical values should be **verified against the source**.
- Offline: Excel `unstructured` loader and Google-Fonts calls were flagged; not all hardened.

---

## 5. Required for the next stage (roadmap)

**A. Review workflows & reporting (original Phase 4)**
- Structured **findings** table populated from reviews (schema already exists).
- Generate a **Word/PDF review report** per project/discipline (reportlab / python-docx / weasyprint).
- Revision tracking (compare a project's document versions).

**B. Retrieval quality**
- Migrate FAISS → **Chroma** (persistent, per-collection) — deps already present.
- Add a **whole-document review mode** (map-reduce over all chunks) for "review the entire set" questions.
- Tune chunking + k per document type.

**C. More disciplines**
- Build **Structural, MEP, Landscape, Cost/VE** checklists + reviewer prompts (mirror Architecture).
- Wire the relevant codes into the shared knowledge base per discipline.

**D. BIM integration**
- Connect the existing **Revit** and **Navisworks** MCP servers to read `.rvt`/`.nwd` element data directly (far richer than DWG).
- Optional **in-browser 3D/IFC viewer** (IFC.js / glTF) for model preview.

**E. Admin / UX polish**
- **Change-password** button in the top bar.
- **Per-file delete** + per-project **member list with remove** in the Admin panel.
- **Persist per-message timestamps** (store time with each saved message).
- **AD/LDAP or SSO** login option for larger rollout (currently local accounts only).

**F. Offline hardening / deployment**
- Vendor fonts locally; switch Excel loader to the pure openpyxl path.
- **ODA File Converter** auto-install/bundling for DWG out-of-the-box.
- Air-gapped install pack (pre-staged wheels + models) for machines with no internet.
- Consider **Postgres** (`EXPO_DATABASE_URL`) for a multi-user server deployment.

---

_This platform was built incrementally; every change kept the app runnable. Backups of every
edited file are saved next to the originals as `<file>.bak-YYYYMMDD-HHMMSS`._
