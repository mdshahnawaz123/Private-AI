"""Keep the test suite away from the LIVE data directory.

db.py reads EXPO_DATA_DIR once, at import time, and defaults to ./data -- the
same folder the running server uses. Before this file existed, most tests
imported db/main without overriding it, so every pytest run:
  * created throwaway projects/users in the live SQLite DB
    (reason_proj_*, test_proj_*, user_xxxxxx ...),
  * started main.py's startup hook via TestClient, which takes over the
    durable ingestion queue for the live data dir, claims a real user's
    queued document job, and then exits mid-run -- the next server start sees
    that job as "interrupted" and marks the real document error/0 chunks,
    which removes it from retrieval (answers become "not found").

This runs before any test module is imported, so db.DATA_DIR points at a
per-session temporary folder unless a caller has already chosen one
explicitly (e.g. a test or CI job that sets EXPO_DATA_DIR itself).
"""
import os
import tempfile

if not os.environ.get("EXPO_DATA_DIR"):
    _tmp = tempfile.mkdtemp(prefix="expo-test-data-")
    os.makedirs(os.path.join(_tmp, "docs"), exist_ok=True)
    os.environ["EXPO_DATA_DIR"] = _tmp
