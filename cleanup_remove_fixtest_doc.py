# -*- coding: utf-8 -*-
"""
One-off cleanup script (2026-10-07).

ROOT CAUSE: leftover test-fixture files from earlier audit/testing work were
left sitting inside LIVE project folders instead of a scratch/test location,
got ingested into the real index AND the real structured-data tables
(structured_records / schedule_rows / page_records / image_records), and
started competing with the real documents for retrieval on real user
questions. Server logs confirm user "Sh" was repeatedly served
AUDIT_FIXTEST_C3085_AREA_SCHEDULE.pdf as the top-retrieved document for real
questions on 2026-10-07 -- it is internally a DIFFERENT document revision
(C3085-SCH-3EH6105-AR-0000003(4)) than the project's real area schedule
(C3085-SCH-3EH6105-AR-0000001(5).pdf), which explains wrong answers.

A sweep of the database found two more fixtures of the same kind sitting in a
second real project (C3045 - Expo Valley Views), not yet proven to have
caused a wrong answer for anyone but the exact same bug -- cleaned up here
too rather than leaving it to bite later.

This script removes every trace of each listed file from its project (DB rows
across documents / doc_meta / schedule_rows / quantities / structured_records
/ page_records / image_records, plus its chunks in the live FAISS index) and
moves the physical file + its sidecar artifacts out of the project folder
into _archive/removed-test-fixtures/, so nothing can re-ingest it later. It
touches ONLY rows/chunks tied to these specific filenames -- every other
document in each project is untouched.

HOW TO RUN:
  1. Stop the running app first (Ctrl+C the server window, or close it) so
     there is only one writer to the database/index at a time.
  2. Open a terminal in this project folder and run:
         python cleanup_remove_fixtest_doc.py
  3. Start the app again (start.bat or restart.bat).
"""
import sys, os, json, shutil, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import db
import main as app_main  # safe to import: main.py guards uvicorn.run() behind `if __name__ == "__main__"`

# (project name, fixture filename) pairs confirmed to be test fixtures living
# inside real project folders, found by searching the DB for "FIXTEST".
TARGETS = [
    ("C3085 - 3EH -Expo Hills", "AUDIT_FIXTEST_C3085_AREA_SCHEDULE.pdf"),
    ("C3045 - Expo Valley Views", "AUDIT_FIXTEST_C3045_PROJECT_DATA_SHEET.pdf"),
    ("C3045 - Expo Valley Views", "AUDIT_FIXTEST2_C3045_PROJECT_DATA_SHEET.pdf"),
]


def clean_one(project, fixture_filename):
    print(f"\n=== {project} :: {fixture_filename} ===")
    doc_path = None
    doc_id = None

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(name=project).first()
        if not proj:
            print(f"Project not found: {project!r} -- skipping.")
            return

        doc = (s.query(db.Document)
                 .filter_by(project_id=proj.id, filename=fixture_filename)
                 .first())
        if not doc:
            print(f"No document row found for {fixture_filename!r} -- it may "
                  "already have been removed. Checking structured tables/index anyway.")
        else:
            doc_path = doc.path
            doc_id = doc.id
            print(f"Found document row id={doc.id} path={doc_path!r}")

        sched_removed = (s.query(db.ScheduleRow)
                           .filter_by(project_id=proj.id, doc=fixture_filename)
                           .delete())
        qty_removed = (s.query(db.Quantity)
                         .filter_by(project_id=proj.id, source_doc=fixture_filename)
                         .delete())
        sr_removed = (s.query(db.StructuredRecord)
                        .filter_by(project_id=proj.id, doc=fixture_filename)
                        .delete())
        pr_removed = (s.query(db.PageRecord)
                        .filter_by(project_id=proj.id, document_filename=fixture_filename)
                        .delete())
        ir_removed = (s.query(db.ImageRecord)
                        .filter_by(project_id=proj.id, document_filename=fixture_filename)
                        .delete())
        print(f"Removed: {sched_removed} ScheduleRow, {qty_removed} Quantity, "
              f"{sr_removed} StructuredRecord, {pr_removed} PageRecord, "
              f"{ir_removed} ImageRecord row(s) citing this file.")

        if doc_id is not None:
            dm_removed = s.query(db.DocMeta).filter_by(document_id=doc_id).delete()
            print(f"Removed {dm_removed} DocMeta row(s).")
            s.delete(doc)
            print("Removed Document row.")

        s.commit()

    try:
        vs = app_main.get_vectorstore(project)
        if vs is not None:
            obsolete = [k for k, v in vs.docstore._dict.items()
                        if v.metadata.get('source') == fixture_filename]
            if obsolete:
                vs.delete(obsolete)
                app_main._persist_index_generation(project, vs)
                app_main.vectorstores[project] = vs
                print(f"Removed {len(obsolete)} FAISS chunk(s) for this source and re-saved the index.")
            else:
                print("No FAISS chunks found for this source in the loaded index.")
        else:
            print("No vectorstore currently loaded/persisted for this project.")
    except Exception as e:
        print("WARNING: could not purge FAISS chunks automatically:", repr(e))
        print("If search results still mention this file after restarting, "
              "click 'Rebuild Index' in the Documents panel for this project.")

    if doc_path and os.path.isfile(doc_path):
        archive_dir = os.path.join(HERE, "_archive", "removed-test-fixtures")
        os.makedirs(archive_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        moved = 0
        candidates = [
            doc_path,
            doc_path + ".extracted.txt",
            doc_path + ".index.json",
            doc_path + "_images",
            doc_path + "_inspection",
            doc_path + "_pages",
            doc_path + "_page_ocr",
        ]
        for c in candidates:
            if os.path.exists(c):
                dest = os.path.join(archive_dir, f"{stamp}-{os.path.basename(c)}")
                shutil.move(c, dest)
                moved += 1
        print(f"Moved {moved} file(s)/folder(s) to {archive_dir}")
    else:
        print("Physical file not found at the recorded path -- nothing to move "
              "(it may have already been moved/deleted).")


def run():
    for project, fixture_filename in TARGETS:
        clean_one(project, fixture_filename)
    print("\nAll done. Start the app again (start.bat / restart.bat) so the "
          "in-memory document list and any cached state refresh with the clean data.")


if __name__ == "__main__":
    run()
