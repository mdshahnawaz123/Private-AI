# Expo Design AI — Phase 1 Report: Unified Workspace UI

_Date: 2026-09-27 · Scope: front-end only · Backend / DB / RAG / FAISS / coordinate pipeline: unchanged_

## Summary
The app is now a single **Project Intelligence Platform** workspace — top navigation, a LEFT project/documents/KB rail, a CENTER workspace (Chat / 3D Model / Drawings / Reports / Schedules / Documents / Model Review / Automation), and a RIGHT AI Assistant / Element Properties / Evidence panel, with five layout modes and a camera-only 3D navigation gizmo. The existing IFC viewer engine and the local AI backend are untouched and reused.

## Files created
- `ui/index.html` — **new** unified workspace shell (the current app was preserved first; see below). ~1,050 lines, self-contained, uses the same endpoints and the same `expo_token` auth as before.
- `ui/classic.html` — **exact copy** of the previous `index.html` (the full classic console: upload, admin, folders, permission test, deep document management). Reached from the workspace via the **Manage** button and the **Upload / Admin** actions. Nothing in it changed.
- `_checkpoints/phase1-<timestamp>/` — checkpoint backup of `index.html`, `viewer.html`, `viewer.js`, `fonts.css` taken before any edit.
- `ARCHITECTURE_ASSESSMENT.md` — the approved assessment (from the previous step).

## Files changed
- `ui/viewer.js` — **additive only.** Added: (1) the **camera-only navigation gizmo** (TOP/BOTTOM/LEFT/RIGHT/FRONT/BACK + Fit) that moves only the camera; (2) a **postMessage bridge** that reports the selected element to the parent workspace and serves the model context to it. **No change** to IfcLocalPlacement, shared coordinates, origin shift, units, multi-model alignment, Plan North, True North, or any geometry transformation. A timestamped `.bak` was written before editing.

## Files NOT touched (protected)
- `viewer.html` — unchanged; still works standalone as the **fallback route** (`/ui/viewer.html`) and is what the workspace embeds.
- `main.py`, `db.py`, `auth.py`, `local_chat.py`, `local_embed.py`, `extract.py`, `vision.py`, all backend modules, `data/expo.db`, FAISS indexes — **not modified.**

## Architecture changes
- **None in the backend.** `/ui/` still serves `ui/index.html` via the existing StaticFiles mount, so making the workspace the new `index.html` needed **no** `main.py` change. `/` still redirects to `/ui/`. `/ui/classic.html` and `/ui/viewer.html` are served by the same mount.
- **Front-end only:** a new shell that calls the existing endpoints — `/auth/login`, `/auth/me`, `/projects`, `/projects/{p}/documents`, `/kb`, `/ask_stream`, `/ask_model`, `/projects/{p}/file` — with the existing Bearer-token scheme.
- **AI routing:** the RIGHT assistant posts to `/ask_stream` normally and switches to `/ask_model` when the 3D Model tab is active (pulling model context from the embedded viewer over postMessage). The CENTER Chat always uses `/ask_stream`. "Ask AI About Selection" posts the selected element's properties to `/ask_model`.

## What was validated here (static + rendered preview)
Rendered in a headless browser at 1920×1080 with the API responses stubbed (the live backend isn't reachable from this session). Screenshots: `phase1_home.png`, `phase1_3d.png`, `phase1_schedules.png`.
- ✅ `viewer.js` passes `node --check`; workspace JS passes `node --check` (balanced braces, no syntax errors).
- ✅ Shell renders: brand, top nav (9 tabs), mode switch (Split / Chat Focus / 3D Focus / Drawing Focus / Report Focus), project chip, Manage, user, Logout.
- ✅ LEFT rail: projects, documents, and (admin) Knowledge Base populate.
- ✅ CENTER: Home dashboard; 3D Model picker lists IFC files + Load selected + Full page fallback; Drawings/Reports/Schedules show a professional "Coming in Phase N" banner **above the real files** with working Open buttons; Documents lists all files; Model Review / Automation show professional roadmap states.
- ✅ RIGHT: Assistant / Properties / Evidence tabs; assistant context label flips to "3D model + selection" on the 3D tab.
- ✅ Responsive rules for 2560×1440, 1920×1080, and laptop widths; panels collapse.

## Test results — to verify live on your machine
These need the running backend + a loaded model; use the procedure below. Structure/wiring is in place; the checks confirm end-to-end behaviour.

| # | Test | How to check |
|---|---|---|
| 1 | Login | Open `http://127.0.0.1:8090/ui/` → sign in → shell appears |
| 2 | Chat | Chat tab → ask a question → streamed answer |
| 3 | Document upload | Manage (classic) → upload → returns to workspace, file listed |
| 4 | Document retrieval | Chat a question answered from a doc |
| 5 | Citations | After an answer, RIGHT → Evidence shows file + page; click opens original |
| 6 | Project permissions | Log in as a scoped user → only permitted projects/docs appear |
| 7 | IFC loading | 3D Model → tick model → Load selected → model renders |
| 8 | Multiple IFC models | Tick two → Load selected → both load in one world |
| 9 | Model alignment | Model sits square (Plan North default) |
| 10 | Plan North / 11 True North | Align toggle flips view; geometry unchanged |
| 12 | Debug | Debug panel shows the IFC audit |
| 13 | Section | X/Y/Z + slider clip |
| 14 | Measurement | Length/Area readouts |
| 15 | Hide / Isolate / Show All | Visibility controls |
| 16 | Element selection | Click element → highlights |
| 17 | Element properties | Selecting posts to RIGHT → Properties (type, name, GUID, express id, psets) |
| 18 | Ask AI | Viewer's own Ask AI answers; RIGHT assistant answers via `/ask_model` on 3D |
| 19 | Navigation gizmo | Top/Front/etc rotate the **camera only** |
| 20 | Split View | All three regions visible |
| 21 | 3D Focus / Chat Focus | Side panels hide; center maximises |

### Test procedure
1. Restart nothing is required (front-end only), but do a hard refresh (Ctrl+F5) at `http://127.0.0.1:8090/ui/`.
2. Sign in. You land on **Home**.
3. Click **3D Model**, tick the IFC, **Load selected** — confirm the model, gizmo (top-left), Plan/True North, Debug, Section, Measure, Hide/Isolate/Show All.
4. Click an element → confirm **Properties** fills on the right and **Ask AI About Selection** appears; click it.
5. Try **Split / Chat Focus / 3D Focus** modes and the panel collapse arrows.
6. Open **Chat**, ask a document question; confirm the answer streams and **Evidence** lists sources.
7. Open **Drawings / Reports / Schedules** — confirm the "Coming in Phase N" banner and that real files open.
8. Click **Manage** — confirm the classic console (upload/admin) still works.

## Remaining issues / notes
- Live end-to-end verification (items 1–21) is pending on your machine — this session cannot reach your local server/Ollama, so the above was validated by static analysis and a stubbed render.
- Admin/upload/folder management is reached via **Manage** (classic console) rather than reimplemented in the workspace — deliberate for Phase 1 to avoid duplicating working code. It can be folded into the workspace in a later phase if you want.
- Drawings/Reports/Schedules currently list real files by file type as a functional stand-in; **structured** drawing/schedule intelligence is Phases 3–4.
- The embedded viewer keeps its own in-panel Ask AI and Debug; the RIGHT assistant is complementary (project-scoped + selection).

## Rollback instructions
Front-end only, fully reversible. From `C:\3EH\ExpoDesignAI`:
1. Restore the viewer and classic app:
   - `copy _checkpoints\phase1-<timestamp>\viewer.js ui\viewer.js`
   - `copy _checkpoints\phase1-<timestamp>\index.html ui\index.html`  (restores the original app as `/ui/`)
   - delete `ui\classic.html` (optional)
2. Or, to keep the workspace but revert only the viewer gizmo/bridge: restore `ui\viewer.js` from the checkpoint (or the newest `ui\viewer.js.bak-*`).
3. Hard refresh. No backend, database, or migration changes were made, so there is nothing else to undo.

**No Phase 2 work has been started. Awaiting your approval to proceed.**
