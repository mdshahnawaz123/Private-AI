"""Durable local ingestion queue. One runner owns the OS lock per data directory.

Jobs survive process termination. An interrupted job is replayed through the same
source-replacing pipeline; immutable source hashes prevent indexing a newer upload
under an older job. SQLite commits before enqueue returns.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager


def source_hash(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class JobQueue:
    def __init__(self, data_dir, handlers=None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "ingestion-jobs.sqlite3")
        self.lock_path = os.path.join(data_dir, "ingestion-runner.lock")
        self.handlers = handlers or {}
        self.failure_handlers = {}
        self.stop_event = threading.Event()
        self.thread = None
        self.lock_file = None
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
                sha256 TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, error TEXT)
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(state,available)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def active(self, source):
        with self.connect() as conn:
            return conn.execute("SELECT id FROM jobs WHERE source=? AND state IN ('queued','running','retry')", (os.path.realpath(source),)).fetchone() is not None

    def enqueue(self, kind, source, payload):
        source = os.path.realpath(source)
        from services.project_cleanup import assert_job_source_active
        assert_job_source_active(self.data_dir, source, payload)
        digest = source_hash(source)
        now = time.time()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Recheck under the queue write lock: a purge may have started
            # after the first preflight while this enqueue waited for the lock.
            assert_job_source_active(self.data_dir, source, payload)
            existing = conn.execute("SELECT id,sha256 FROM jobs WHERE source=? AND state IN ('queued','running','retry')", (source,)).fetchone()
            if existing:
                if existing['sha256'] != digest:
                    raise ValueError("A different source version is already processing")
                return existing['id']
            job_id = uuid.uuid4().hex
            conn.execute("INSERT INTO jobs(id,kind,source,sha256,payload,state,available,created,updated) VALUES(?,?,?,?,?,'queued',?,?,?)", (job_id, kind, source, digest, json.dumps(payload), now, now, now))
        return job_id

    def enqueue_stranded(self,kind,source,payload):
        """Recover an uncommitted intake, never reset a terminal job's budget."""
        canonical=os.path.realpath(source)
        digest=source_hash(canonical)
        with self.connect() as conn:
            existing=conn.execute('SELECT state FROM jobs WHERE source=? AND sha256=? ORDER BY created DESC LIMIT 1',(canonical,digest)).fetchone()
        if existing and existing['state'] in ('completed','failed'):
            return None
        return self.enqueue(kind,canonical,payload)

    def claim(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE state IN ('queued','retry') AND available<=? ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE jobs SET state='running',attempts=attempts+1,updated=? WHERE id=?", (time.time(), row['id']))
            result = dict(row)
            result['attempts'] += 1
            return result

    def run_one(self):
        job = self.claim()
        if not job:
            return False
        try:
            from services.project_cleanup import assert_job_source_active
            assert_job_source_active(self.data_dir, job['source'], json.loads(job['payload']))
            if source_hash(job['source']) != job['sha256']:
                raise ValueError("Source changed after enqueue; upload again to process the new version")
            handler = self.handlers[job['kind']]
            handler(json.loads(job['payload']))
            if source_hash(job['source']) != job['sha256']:
                raise ValueError('Source changed during processing')
            state, error, delay = 'completed', None, 0
        except Exception as exc:
            state = 'failed' if isinstance(exc, (ValueError, KeyError)) or job['attempts'] >= 3 else 'retry'
            error, delay = str(exc)[:2000], min(300, 10 * 2 ** job['attempts'])
            failed=self.failure_handlers.get(job['kind'])
            if failed:
                try:failed(json.loads(job['payload']),error)
                except Exception as invalidate_error:
                    error=(error+'; readiness invalidation failed: '+str(invalidate_error))[:2000]
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET state=?,error=?,available=?,updated=? WHERE id=?", (state,error,time.time()+delay,time.time(),job['id']))
        return True

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.lock_file = open(self.lock_path, 'a+b')
        self.lock_file.seek(0)
        if os.name == 'nt':
            import msvcrt
            if os.path.getsize(self.lock_path) == 0:
                self.lock_file.write(b'0')
                self.lock_file.flush()
            self.lock_file.seek(0)
            try:
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.lock_file.close()
                raise RuntimeError("An ingestion runner already owns this data directory; use one application worker")
        else:
            import fcntl
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_file.close()
                raise RuntimeError("An ingestion runner already owns this data directory")
        # Exclusive OS ownership proves no previous runner can still be working.
        # Invalidate published readiness before replay or terminal failure. A
        # crash can occur after a handler's READY commit but before queue commit.
        # If invalidation fails, do not start serving work under a false state.
        try:
            with self.connect() as conn:
                interrupted=conn.execute("SELECT * FROM jobs WHERE state='running'").fetchall()
            for job in interrupted:
                invalidate=self.failure_handlers.get(job['kind'])
                if invalidate:
                    invalidate(json.loads(job['payload']), 'Interrupted; readiness requires revalidation')
        except Exception:
            self.lock_file.close()
            self.lock_file=None
            raise
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET state='failed',updated=?,error='Interrupted; retry limit exhausted' WHERE state='running' AND attempts>=3", (time.time(),))
            conn.execute("UPDATE jobs SET state='retry',available=?,updated=?,error='Interrupted; replaying' WHERE state='running' AND attempts<3", (time.time(),time.time()))
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='durable-ingestion', daemon=True)
        self.thread.start()

    def _run(self):
        from loguru import logger
        while not self.stop_event.is_set():
            try:
                if self.run_one():
                    continue
            except Exception:
                logger.exception("Ingestion queue polling failed")
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        # Keep ownership while a long model request drains. Process exit releases
        # the OS lock; the next process safely replays the interrupted job.
        if self.lock_file and (not self.thread or not self.thread.is_alive()):
            self.lock_file.close()

    def status(self):
        with self.connect() as conn:
            return {row['state']:row['n'] for row in conn.execute("SELECT state,COUNT(*) n FROM jobs GROUP BY state")}

    def list_recent(self, limit=100):
        """Most recent jobs for admin/diagnostic display (Pilot architecture
        blueprint Sec 6.3: callers outside this class should never write their
        own SQL against the `jobs` table -- a future backend swap (Celery/RQ)
        only has to implement this method, not be grepped-for by every caller)."""
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT id,kind,state,attempts,created,updated,error FROM jobs ORDER BY created DESC LIMIT ?',
                (limit,)).fetchall()
            return [dict(row) for row in rows]
