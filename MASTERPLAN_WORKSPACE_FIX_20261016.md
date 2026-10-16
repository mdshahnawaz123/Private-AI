# Masterplan workspace and highlighting corrections

## Observed evidence

Read-only inspection of data/masterplan.db shows the deleted 25-6963 masterplan absent from mp_files. Remaining sources are the 25-6963 Excel register (340 imported plots) and C3085-DWG-3EH6110-AR-2B10101(5) (1).dwg (0 imported plots). mp_plots still contains 34 Mixed Use entries, among other categories, and geometry persisted on register rows. This establishes leftover geometry, not that each polygon's source can be proved: geometry lacks per-file lineage.

## Root causes and changes

- Deleting CAD while Excel remained left plot geometry intact. Future CAD deletion conservatively nulls project plot geometry while retaining register attributes; deletion also invalidates in-memory CAD drawing cache. Existing ambiguous geometry is not rewritten in production by this task.
- Workspace previously always loaded the newest CAD. Added CAD source selector and register-only view; API accepts an optional project-scoped file ID and rejects unknown/deleted IDs. Loading clears previous linework. UI suppresses plot geometry when the selected CAD has zero extracted plots, preventing old masterplan boundaries appearing over the unrelated remaining CAD.
- "mixed type" and "mixed-use" were not recognized as Mixed Use. Added aliases. The deterministic land-use result was also discarded in favour of a model response; land-use and density results now return directly from database tools. Removed the 25-record aggregation truncation.
- API had no requested highlight color. Added optional color, passed through both chat UI paths, with a strict six-digit hex check. Highlight color now takes precedence over the selected-plot blue.
- Found hard-coded CAD entity/compliance statistics. Removed that response and return explicitly unverified audit status without invoking model reasoning for that request.

## Validation actually executed

Python 3.12: `python -B -m unittest discover -s tests -p test_masterplan_workspace_regression.py`: **4 passed**. Tests extract actual methods with AST to avoid startup/global database side effects. Synthetic plots and temporary SQLite verify all 34 highlight IDs and yellow, selected-file API behaviour and deleted ID rejection, CAD geometry invalidation with Excel retention, and refusal to claim fabricated CAD compliance. No live Ollama call or live browser interaction occurred.

`node --check ui/mpd.js` and `node --check ui/app.js`: passed. Initial test run had a Windows SQLite handle cleanup error in the fixture; explicit connection closing fixed it and the rerun passed.

## Remaining limits

The current CAD's zero extracted plots means the 34 register entries cannot be reliably drawn on it. They need verified CAD parcel extraction and reconciliation first. Do not manufacture coordinates or restore the deleted masterplan to satisfy a color request. File switching currently selects CAD drawing linework; the plot register remains project-wide, not an independently selected Excel dataset. No full agentic-system approval, live model evaluation, security audit or full suite is claimed. Existing physical deletion silently ignores filesystem errors and derived disk cache cleanup remains a separate hardening gap.

## Files and rollback

Changed services/masterplan/{agent.py,api.py,db.py,models.py}, ui/mpd.js, ui/app.js; added tests/test_masterplan_workspace_regression.py. No production database migration, model, dependency or production data modification. Rollback only this task's diff hunks; avoid blanket resets. Restart the server and refresh the UI to load code changes. Geometry invalidation after future CAD deletions requires reimport/reconciliation to reconstruct; register values remain.
