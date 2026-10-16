"""
Expo Design AI — data layer (Phase 2).

SQLAlchemy models, a portable engine (SQLite by default, Postgres via
EXPO_DATABASE_URL), an immutable audit trail, and the high-level helpers the
API calls. Designed multi-user from the start: every row that represents an
action carries a user id, defaulting to the seeded 'system' user until real
login lands in Phase 5.
"""
import os
import json
import datetime
import uuid
from typing import Optional, List, Dict, Any

from sqlalchemy import (create_engine, event, Column, Integer, String, Text,
                        DateTime, ForeignKey, JSON, UniqueConstraint, Float, Index)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from loguru import logger

# ── paths / config ─────────────────────────────────────────
DATA_DIR = os.getenv("EXPO_DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)

logger.add(
    os.path.join(DATA_DIR, "logs", "expo.log"),
    rotation="10 MB", retention="60 days", enqueue=True,
    backtrace=False, diagnose=False,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}",
)

DATABASE_URL = os.getenv(
    "EXPO_DATABASE_URL",
    "sqlite:///" + os.path.join(DATA_DIR, "expo.db"),
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA busy_timeout=30000;")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
Base = declarative_base()

SYSTEM_USER = {"id": 1, "username": "system"}

def _utcnow():
    return datetime.datetime.utcnow()

# ── models ─────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False)
    full_name = Column(String(200), default="")
    email = Column(String(200), default="")
    role = Column(String(40), default="reviewer")        # reviewer | lead | admin
    password_hash = Column(String(255), nullable=True)   # set when login lands (Phase 5)
    auth_version = Column(Integer, default=0, nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=_utcnow)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    discipline = Column(String(40), nullable=True)       # Phase 3: Structural/Architecture/MEP/...
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    # Recycle bin (2026-10-07): same soft-delete pattern as Document.deleted_at
    # below -- see soft_delete_project() / restore_project() /
    # purge_expired_deleted_projects(). NULL = not deleted.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(120), nullable=False)        # client-supplied id
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String(400), default="")
    messages = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    project = relationship("Project", back_populates="chats")
    __table_args__ = (UniqueConstraint("project_id", "chat_id", name="uq_chat_project_chatid"),)

class Annotation(Base):
    __tablename__ = "annotations"
    id = Column(String, primary_key=True)
    document_id = Column(String, index=True)
    drawing = Column(String)
    annotation_type = Column(String)
    x = Column(Float)
    y = Column(Float)
    width = Column(Float)
    height = Column(Float)
    page_number = Column(Integer)
    author = Column(String)
    timestamp = Column(Float)
    comment_text = Column(String)
    status = Column(String, default="OPEN")
    revision = Column(String)
    created_at = Column(Float)
    updated_at = Column(Float)
    
class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(400), nullable=False)
    path = Column(Text, default="")
    chunks = Column(Integer, default=0)
    discipline = Column(String(40), nullable=True)
    status = Column(String(20), default="ready")
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=_utcnow)
    # Recycle bin (2026-10-07): soft-delete instead of a hard DELETE, so an
    # admin mistake is recoverable. See soft_delete_document() / restore_document()
    # / purge_expired_deleted_documents() below. NULL = not deleted (the normal
    # state); list_documents() filters these out by default so deleted files
    # vanish from the app immediately, while the row (and the file, moved to
    # data/recycle_bin/) stays recoverable for RECYCLE_BIN_RETENTION_DAYS days.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    project = relationship("Project", back_populates="documents")

class Finding(Base):
    """Structured review finding. Schema now; populated in Phase 4."""
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    chat_id = Column(String(120), nullable=True)
    discipline = Column(String(40), nullable=True)
    code = Column(String(120), default="")               # clause / check id
    status = Column(String(40), default="open")          # open | pass | fail | na
    severity = Column(String(40), default="")
    comment = Column(Text, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

class AuditLog(Base):
    """Append-only. Updates/deletes are blocked by DB triggers on SQLite."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=_utcnow, index=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(120), default="system")
    action = Column(String(80), nullable=False)
    project = Column(String(200), nullable=True)
    target = Column(String(400), nullable=True)
    detail = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)


class JobProgress(Base):
    """Shared, cross-process ingestion progress (replaces the old in-memory
    PROGRESS dict in main.py). Keyed by "<project>||<filename>" so multiple
    app server processes -- or workers behind a future queue/Postgres
    deployment -- all see the same progress for a document being processed.
    One row per in-flight document; the row is deleted when processing ends
    (success or failure), matching the old dict's pop-on-completion behavior.
    """
    __tablename__ = "job_progress"
    key = Column(String(600), primary_key=True)
    stage = Column(String(120), nullable=False)
    done = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


def set_progress(key, stage, done, total):
    """Upsert the progress row for `key`. Safe to call from any process --
    all state lives in the DB, not in process memory."""
    with SessionLocal() as s:
        row = s.get(JobProgress, key)
        if row is None:
            row = JobProgress(key=key, stage=stage, done=done, total=total)
            s.add(row)
        else:
            row.stage = stage
            row.done = done
            row.total = total
            row.updated_at = _utcnow()
        s.commit()


def get_progress(key):
    """Return {"stage":..., "done":..., "total":...} or None if no job is
    in flight for this key (matches the old PROGRESS.get(key) contract)."""
    with SessionLocal() as s:
        row = s.get(JobProgress, key)
        if row is None:
            return None
        return {"stage": row.stage, "done": row.done, "total": row.total}


def clear_progress(key):
    """Remove the progress row once processing finishes (success or failure),
    matching the old PROGRESS.pop(key, None) behavior."""
    with SessionLocal() as s:
        row = s.get(JobProgress, key)
        if row is not None:
            s.delete(row)
            s.commit()

# ── init / migration ───────────────────────────────────────
def init_db():
    # NOTE (Pilot architecture blueprint Sec 6.3): create_all() plus the
    # hand-rolled ALTER-TABLE-if-missing blocks below are how this schema has
    # evolved so far. Alembic is now set up (see alembic/README) specifically
    # to replace this pattern going forward -- any NEW column/table should be
    # added via `alembic revision --autogenerate` + `alembic upgrade head`,
    # not another try/except ALTER TABLE block here. The blocks below are left
    # as-is (already deployed, working, and idempotent) rather than migrated
    # retroactively, to avoid any risk to the running pilot.
    Base.metadata.create_all(engine)
    from sqlalchemy import inspect
    if 'auth_version' not in {column['name'] for column in inspect(engine).get_columns('users')}:
        with engine.begin() as conn:
            conn.exec_driver_sql('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE documents ADD COLUMN status VARCHAR(20) DEFAULT 'ready'")
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE documents ADD COLUMN folder_id INTEGER")
    except Exception:
        pass
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;")
            conn.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;")
    with SessionLocal() as s:
        if not s.get(User, 1):
            s.add(User(id=1, username="system", full_name="System", role="admin", is_active=1))
            s.commit()
    _migrate_json_projects()
    # Phase 0: Initialize Knowledge Hub tables
    init_knowledge_tables()
    logger.info("DB ready at {}", DATABASE_URL)

def _get_or_create_project(s, name, user_id=1):
    proj = s.query(Project).filter_by(name=name).first()
    from services.project_cleanup import project_is_retired
    if (proj and proj.deleted_at is not None) or project_is_retired(DATA_DIR, name):
        raise ValueError("Project is deleted; restore it or explicitly create a new project")
    if not proj:
        proj = Project(name=name, created_by=user_id)
        s.add(proj)
        s.flush()
    return proj

def _migrate_json_projects():
    """One-time, idempotent import of legacy data/projects/*/*.json into the DB."""
    pdir = os.path.join(DATA_DIR, "projects")
    if not os.path.isdir(pdir):
        return
    imported = 0
    with SessionLocal() as s:
        for name in sorted(os.listdir(pdir)):
            ppath = os.path.join(pdir, name)
            if not os.path.isdir(ppath):
                continue
            try:
                proj = _get_or_create_project(s, name)
            except ValueError:
                continue
            for fn in os.listdir(ppath):
                if not fn.endswith(".json"):
                    continue
                cid = fn[:-5]
                if s.query(Chat).filter_by(project_id=proj.id, chat_id=cid).first():
                    continue
                try:
                    with open(os.path.join(ppath, fn), encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
                s.add(Chat(chat_id=cid, project_id=proj.id,
                           title=data.get("title", ""), messages=data.get("messages", []),
                           created_by=1))
                imported += 1
        s.commit()
    if imported:
        logger.info("Migrated {} legacy chat(s) from JSON into DB", imported)

# ── audit ──────────────────────────────────────────────────
def audit(action, project=None, target=None, detail=None, user=None, ip=None):
    u = user or SYSTEM_USER
    try:
        with SessionLocal() as s:
            s.add(AuditLog(action=action, project=project,
                           target=(str(target) if target is not None else None),
                           detail=detail, ip=ip,
                           user_id=u["id"], username=u["username"]))
            s.commit()
    except Exception as e:
        logger.error("audit write failed: {}", e)
    logger.info("AUDIT {} user={} project={} target={} detail={}",
                action, u["username"], project, target, detail)

def recent_audit(limit=200, project=None):
    with SessionLocal() as s:
        q = s.query(AuditLog).order_by(AuditLog.id.desc())
        if project:
            q = q.filter(AuditLog.project == project)
        rows = q.limit(max(1, min(limit, 2000))).all()
        return [{"id": r.id, "ts": r.ts.isoformat() if r.ts else None,
                 "user": r.username, "action": r.action, "project": r.project,
                 "target": r.target, "detail": r.detail, "ip": r.ip} for r in rows]

# ── project / chat helpers (used by the API) ───────────────
def projects_with_chats(user=None):
    allowed = None
    if user and user.get("role") != "admin":
        allowed = set(user_projects(user["id"]))
    out = {}
    with SessionLocal() as s:
        for proj in (s.query(Project).filter(Project.deleted_at.is_(None))
                      .order_by(Project.name).all()):
            if proj.name.startswith("__"):
                continue
            if allowed is not None and proj.name not in allowed:
                continue
            chats = (s.query(Chat).filter_by(project_id=proj.id)
                     .order_by(Chat.updated_at.desc()).all())
            out[proj.name] = [c.chat_id for c in chats]
    if not out and (user is None or user.get("role") == "admin"):
        out["default"] = []
    return out


# ============================================================
# Recycle bin -- projects (2026-10-07). Same pattern as the per-document one
# above: soft-delete hides the project everywhere immediately (auth.require_project
# excludes deleted_at IS NOT NULL too, so even an admin can't use it normally
# until restored); the physical docs/ and faiss_index/ folders move to
# data/recycle_bin/_projects/<project>/ (main.py's delete_project endpoint does
# that, these helpers only manage DB rows); the project is recoverable for
# RECYCLE_BIN_RETENTION_DAYS days, then the daily sweep purges it for good.
# ============================================================
# Historical inventory retained for compatibility. Actual purge resolves all
# project-owned tables from FK-sorted metadata at call time.
_PROJECT_CHILD_TABLE_NAMES = (
    "Finding", "ProjectMember", "Folder", "Requirement", "Evidence", "SourcePrecedence",
    "GraphEdge", "EngineeringRule", "QAFinding", "BimModel", "BimElement", "Drawing",
    "Schedule", "StructuredRecord", "ScheduleRow", "Quantity", "UserUpload",
    "PageRecord", "ImageRecord", "Chat", "Document",
)

def soft_delete_project(name, user=None, ip=None):
    """Mark a project deleted. Returns {id, name} or None if no such
    (non-deleted) project exists."""
    with SessionLocal() as s:
        proj = (s.query(Project).filter_by(name=name)
                 .filter(Project.deleted_at.is_(None)).first())
        if not proj:
            return None
        proj.deleted_at = _utcnow()
        proj.deleted_by = (user or {}).get("id") if user else None
        s.commit()
        info = {"id": proj.id, "name": proj.name}
    audit("project.delete", project=name,
          detail={"recycle_bin_days": RECYCLE_BIN_RETENTION_DAYS}, user=user or SYSTEM_USER, ip=ip)
    return info

def restore_project(name, user=None, ip=None):
    """Undo soft_delete_project() within the retention window."""
    from services.project_cleanup import project_is_retired
    if project_is_retired(DATA_DIR, name):
        raise ValueError('Permanent cleanup has started; retry cleanup instead of restoring')
    with SessionLocal() as s:
        proj = (s.query(Project).filter_by(name=name)
                 .filter(Project.deleted_at.isnot(None)).first())
        if not proj:
            return None
        proj.deleted_at = None
        proj.deleted_by = None
        s.commit()
        info = {"id": proj.id, "name": proj.name}
    audit("project.restore", project=name, user=user or SYSTEM_USER, ip=ip)
    return info

def list_deleted_projects():
    """Recycle-bin listing: soft-deleted projects, newest-deleted first, with
    days_remaining before purge_expired_deleted_projects() removes them for good."""
    with SessionLocal() as s:
        rows = (s.query(Project).filter(Project.deleted_at.isnot(None))
                 .order_by(Project.deleted_at.desc()).all())
        out = []
        now = _utcnow()
        for p in rows:
            age_days = (now - p.deleted_at).days if p.deleted_at else 0
            out.append({
                "id": p.id, "name": p.name,
                "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None,
                "deleted_by": p.deleted_by,
                "days_remaining": max(0, RECYCLE_BIN_RETENTION_DAYS - age_days),
            })
        return out

def _purge_project_row(s, proj):
    """Delete owned rows in reverse FK order; caller owns session/commit.

    Files and durable jobs require services.project_cleanup.purge_project.
    """
    doc_ids = [d.id for d in s.query(Document.id).filter_by(project_id=proj.id).all()]
    doc_paths = [d.path for d in s.query(Document).filter_by(project_id=proj.id).all() if d.path]
    folder_ids = [f.id for f in s.query(Folder.id).filter_by(project_id=proj.id).all()]
    # Numeric document identities and full stored paths are unambiguous. A
    # basename alone is not ownership evidence across projects.
    keys = [str(i) for i in doc_ids] + doc_paths
    if keys:
        s.query(Annotation).filter(Annotation.document_id.in_(keys)).delete(synchronize_session=False)
    s.query(JobProgress).filter(JobProgress.key.startswith(proj.name + '||', autoescape=True)).delete(synchronize_session=False)
    # Reverse FK order: document dependents before documents, then folders.
    # Resolve metadata at call time so newly defined project-owned tables are
    # included instead of silently being missed by an old class-name list.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == Project.__tablename__:
            continue
        if table.name == 'image_outputs':
            job_ids = [j.id for j in s.query(ImageJob.id).filter_by(project_id=proj.id).all()]
            if job_ids:
                s.execute(table.delete().where(table.c.job_id.in_(job_ids)))
        elif 'project_id' in table.c:
            s.execute(table.delete().where(table.c.project_id == proj.id))
        elif table.name == DocMeta.__tablename__ and doc_ids:
            s.execute(table.delete().where(table.c.document_id.in_(doc_ids)))
        elif table.name == FolderMember.__tablename__ and folder_ids:
            s.execute(table.delete().where(table.c.folder_id.in_(folder_ids)))
    s.delete(proj)

def purge_one_deleted_project(name):
    """Database-only helper, not a verified application cleanup operation.

    Application callers must use services.project_cleanup.purge_project.
    """
    with SessionLocal() as s:
        proj = (s.query(Project).filter_by(name=name)
                 .filter(Project.deleted_at.isnot(None)).first())
        if not proj:
            return None
        result = {"name": proj.name}
        _purge_project_row(s, proj)
        s.commit()
    audit("project.purge_now", project=name, user=SYSTEM_USER)
    return result

def purge_expired_deleted_projects(retention_days=None):
    """Permanently remove projects (and everything in them) that have been in
    the recycle bin longer than retention_days (default RECYCLE_BIN_RETENTION_DAYS).
    Returns a list of {name} for the caller to also delete recycle-bin folders for."""
    retention_days = RECYCLE_BIN_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = _utcnow() - datetime.timedelta(days=retention_days)
    purged = []
    with SessionLocal() as s:
        rows = (s.query(Project)
                 .filter(Project.deleted_at.isnot(None), Project.deleted_at < cutoff).all())
        for proj in rows:
            purged.append({"name": proj.name})
            _purge_project_row(s, proj)
        s.commit()
    if purged:
        audit("project.purge_expired", detail={"count": len(purged)}, user=SYSTEM_USER)
    return purged


def save_chat(project, chat_id, title, messages, user=None, ip=None):
    u = user or SYSTEM_USER
    created_project = False
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            proj = Project(name=project, created_by=u["id"])
            s.add(proj); s.flush(); created_project = True
        chat = s.query(Chat).filter_by(project_id=proj.id, chat_id=chat_id).first()
        if chat:
            chat.title = title
            chat.messages = messages
        else:
            chat = Chat(chat_id=chat_id, project_id=proj.id, title=title,
                        messages=messages, created_by=u["id"])
            s.add(chat)
        proj.updated_at = _utcnow()
        s.commit()
    if created_project:
        audit("project.create", project=project, user=u, ip=ip)
    audit("chat.save", project=project, target=chat_id,
          detail={"title": title, "messages": len(messages or [])}, user=u, ip=ip)

def load_chat(project, chat_id):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        chat = s.query(Chat).filter_by(project_id=proj.id, chat_id=chat_id).first()
        if not chat:
            return None
        return {"title": chat.title, "messages": chat.messages or [],
                "updated": chat.updated_at.timestamp() if chat.updated_at else None}

def delete_chat(project, chat_id, user=None, ip=None):
    removed = False
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if proj:
            chat = s.query(Chat).filter_by(project_id=proj.id, chat_id=chat_id).first()
            if chat:
                s.delete(chat); s.commit(); removed = True
    if removed:
        audit("chat.delete", project=project, target=chat_id, user=user or SYSTEM_USER, ip=ip)
    return removed

def record_document(project, filename, path, chunks, discipline=None, status="ready", folder_id=None, user=None, ip=None):
    u = user or SYSTEM_USER
    with SessionLocal() as s:
        # Serialize identity lookup and registration across concurrent uploads.
        s.connection().exec_driver_sql('BEGIN IMMEDIATE')
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            proj = Project(name=project, created_by=u["id"])
            s.add(proj); s.flush()
        existing=(s.query(Document).filter_by(project_id=proj.id,filename=filename,
                    folder_id=folder_id,path=path).filter(Document.deleted_at.is_(None))
                    .order_by(Document.id.desc()).first())
        if existing:
            existing.chunks=chunks;existing.discipline=discipline;existing.status=status
            existing.uploaded_by=u['id'];existing.uploaded_at=_utcnow()
        else:
            s.add(Document(project_id=proj.id, filename=filename, path=path,
                           chunks=chunks, discipline=discipline, status=status,
                           folder_id=folder_id, uploaded_by=u["id"]))
        proj.updated_at = _utcnow()
        s.commit()
    audit("document.upload", project=project, target=filename,
          detail={"chunks": chunks}, user=u, ip=ip)

def clear_docs(project, user=None, ip=None):
    removed = 0
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if proj:
            removed = s.query(Document).filter_by(project_id=proj.id).delete()
            s.commit()
    audit("document.clear", project=project, detail={"removed": removed},
          user=user or SYSTEM_USER, ip=ip)
    return removed


def set_project_discipline(project, discipline, user=None, ip=None):
    with SessionLocal() as sess:
        proj = sess.query(Project).filter_by(name=project).first()
        if not proj:
            proj = Project(name=project, created_by=(user or SYSTEM_USER)["id"])
            sess.add(proj); sess.flush()
        proj.discipline = discipline
        proj.updated_at = _utcnow()
        sess.commit()
    audit("project.discipline", project=project, detail={"discipline": discipline},
          user=user or SYSTEM_USER, ip=ip)

def document_folder_id_for_path(project, abs_path):
    """Return the folder_id of the Document in `project` whose stored path
    resolves to `abs_path`, or None if no matching record exists.

    Used by the file-serving routes (/projects/{project}/file and .../document)
    to enforce folder-level access on a DIRECT path fetch, the same way
    list_documents() already enforces it for listings. Without this, a
    restricted user who knows (or guesses) a relative path could fetch a file
    from a folder they are not assigned to, bypassing folder RBAC entirely.
    """
    with SessionLocal() as sess:
        proj = sess.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        for d in sess.query(Document).filter_by(project_id=proj.id).all():
            if d.path and os.path.abspath(d.path) == abs_path:
                return d.folder_id
        return None


def list_documents(project, user=None, include_deleted=False):
    """List documents in a project. If `user` is given and is NOT full-access
    (admin, or lead who is a project member), only documents in folders the user
    is assigned to are returned (strict: unassigned users see nothing).
    Soft-deleted documents (recycle bin) are excluded unless include_deleted=True
    -- see soft_delete_document() below."""
    with SessionLocal() as sess:
        proj = sess.query(Project).filter_by(name=project).first()
        if not proj:
            return []
        fnames = {f.id: f.name for f in sess.query(Folder).filter_by(project_id=proj.id).all()}
        q = sess.query(Document).filter_by(project_id=proj.id)
        if not include_deleted:
            q = q.filter(Document.deleted_at.is_(None))
        if user is not None:
            allow_all, ids = _folder_access(sess, user, proj)
            if not allow_all:
                if not ids:
                    return []
                q = q.filter(Document.folder_id.in_(list(ids)))
        rows = q.order_by(Document.uploaded_at.desc()).all()
        return [{"id": r.id, "filename": r.filename, "chunks": r.chunks,
                 "discipline": r.discipline, "path": r.path,
                 "status": getattr(r, "status", "ready"),
                 "folder_id": getattr(r, "folder_id", None),
                 "folder": fnames.get(getattr(r, "folder_id", None)),
                 "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None}
                for r in rows]


# ============================================================
# Recycle bin (2026-10-07): soft-delete a document instead of hard-deleting it.
# main.py's delete endpoint moves the physical file(s) to data/recycle_bin/ and
# purges the document's chunks from the live FAISS index; these helpers only
# manage the DB row and the structured-data rows that cite it.
# ============================================================
RECYCLE_BIN_RETENTION_DAYS = 15

def soft_delete_document(project, filename, user=None, ip=None):
    """Mark a document deleted. Returns {id, filename, path, folder_id} for the
    caller to act on (moving files, purging FAISS chunks), or None if no such
    (non-deleted) document exists."""
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        doc = (s.query(Document)
                .filter_by(project_id=proj.id, filename=filename)
                .filter(Document.deleted_at.is_(None)).first())
        if not doc:
            return None
        doc.deleted_at = _utcnow()
        doc.deleted_by = (user or {}).get("id") if user else None
        s.commit()
        info = {"id": doc.id, "filename": doc.filename, "path": doc.path, "folder_id": doc.folder_id}
    audit("document.delete", project=project, target=filename,
          detail={"recycle_bin_days": RECYCLE_BIN_RETENTION_DAYS}, user=user or SYSTEM_USER, ip=ip)
    return info

def restore_document(project, filename, user=None, ip=None):
    """Undo soft_delete_document() within the retention window. Returns
    {id, filename, path, folder_id}, or None if no deleted document matches."""
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        doc = (s.query(Document)
                .filter_by(project_id=proj.id, filename=filename)
                .filter(Document.deleted_at.isnot(None)).first())
        if not doc:
            return None
        doc.deleted_at = None
        doc.deleted_by = None
        s.commit()
        info = {"id": doc.id, "filename": doc.filename, "path": doc.path, "folder_id": doc.folder_id}
    audit("document.restore", project=project, target=filename, user=user or SYSTEM_USER, ip=ip)
    return info

def list_deleted_documents(project=None):
    """Recycle-bin listing: soft-deleted documents, newest-deleted first, with
    days_remaining before purge_expired_deleted_documents() removes them for good."""
    with SessionLocal() as s:
        q = (s.query(Document, Project.name)
              .join(Project, Document.project_id == Project.id)
              .filter(Document.deleted_at.isnot(None)))
        if project:
            q = q.filter(Project.name == project)
        rows = q.order_by(Document.deleted_at.desc()).all()
        out = []
        now = _utcnow()
        for d, proj_name in rows:
            age_days = (now - d.deleted_at).days if d.deleted_at else 0
            out.append({
                "id": d.id, "project": proj_name, "filename": d.filename,
                "path": d.path, "folder_id": d.folder_id,
                "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
                "deleted_by": d.deleted_by,
                "days_remaining": max(0, RECYCLE_BIN_RETENTION_DAYS - age_days),
            })
        return out

def purge_one_deleted_document(project, filename):
    """Admin override: permanently purge exactly one recycle-bin document now,
    instead of waiting out the retention window. Returns {project, filename, path}
    if a matching soft-deleted document was found and purged, else None. Unlike
    purge_expired_deleted_documents(), this never touches any other document."""
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        d = (s.query(Document)
              .filter_by(project_id=proj.id, filename=filename)
              .filter(Document.deleted_at.isnot(None)).first())
        if not d:
            return None
        result = {"project": project, "filename": d.filename, "path": d.path}
        s.query(ScheduleRow).filter_by(project_id=d.project_id, doc=d.filename).delete()
        s.query(Quantity).filter_by(project_id=d.project_id, source_doc=d.filename).delete()
        s.query(StructuredRecord).filter_by(project_id=d.project_id, doc=d.filename).delete()
        s.query(PageRecord).filter_by(project_id=d.project_id, document_filename=d.filename).delete()
        s.query(ImageRecord).filter_by(project_id=d.project_id, document_filename=d.filename).delete()
        s.query(DocMeta).filter_by(document_id=d.id).delete()
        s.query(Annotation).filter(Annotation.document_id.in_([str(d.id), d.path])).delete(synchronize_session=False)
        s.delete(d)
        s.commit()
    audit("document.purge_now", project=project, target=filename, user=SYSTEM_USER)
    return result

def purge_expired_deleted_documents(retention_days=None):
    """Permanently remove documents (and the structured-data rows that cite
    them) that have been in the recycle bin longer than retention_days
    (default RECYCLE_BIN_RETENTION_DAYS). Returns a list of
    {project, filename, path} for the caller to also delete the recycle-bin
    files for from disk. Does NOT touch the live FAISS index -- the document's
    chunks were already purged from it at soft-delete time."""
    retention_days = RECYCLE_BIN_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = _utcnow() - datetime.timedelta(days=retention_days)
    purged = []
    with SessionLocal() as s:
        rows = (s.query(Document, Project.name)
                 .join(Project, Document.project_id == Project.id)
                 .filter(Project.deleted_at.is_(None), Document.deleted_at.isnot(None), Document.deleted_at < cutoff).all())
        for d, proj_name in rows:
            purged.append({"project": proj_name, "filename": d.filename, "path": d.path})
            s.query(ScheduleRow).filter_by(project_id=d.project_id, doc=d.filename).delete()
            s.query(Quantity).filter_by(project_id=d.project_id, source_doc=d.filename).delete()
            s.query(StructuredRecord).filter_by(project_id=d.project_id, doc=d.filename).delete()
            s.query(PageRecord).filter_by(project_id=d.project_id, document_filename=d.filename).delete()
            s.query(ImageRecord).filter_by(project_id=d.project_id, document_filename=d.filename).delete()
            s.query(DocMeta).filter_by(document_id=d.id).delete()
            s.query(Annotation).filter(Annotation.document_id.in_([str(d.id), d.path])).delete(synchronize_session=False)
            s.delete(d)
        s.commit()
    if purged:
        audit("document.purge_expired", detail={"count": len(purged)}, user=SYSTEM_USER)
    return purged


# ============================================================
# Phase 5: users, roles, project membership
# ============================================================
ROLES = ("admin", "lead", "user")

class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    added_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_member_project_user"),)

def _user_dict(u):
    return {"id": u.id, "username": u.username, "full_name": u.full_name or "",
            "email": u.email or "", "role": u.role, "is_active": bool(u.is_active), 'auth_version':u.auth_version or 0,
            "created_at": u.created_at.isoformat() if u.created_at else None}

def get_user_by_username(username):
    with SessionLocal() as s:
        u = s.query(User).filter(User.username == username).first()
        if not u:
            return None
        d = _user_dict(u)
        d["password_hash"] = u.password_hash
        return d

def get_user(uid):
    with SessionLocal() as s:
        u = s.get(User, uid)
        return _user_dict(u) if u else None

def list_users():
    with SessionLocal() as s:
        return [_user_dict(u) for u in s.query(User).order_by(User.username).all()]

def create_user(username, password_hash, role="user", full_name="", email="", by=None):
    role = role if role in ROLES else "user"
    with SessionLocal() as s:
        if s.query(User).filter(User.username == username).first():
            raise ValueError("username already exists")
        u = User(username=username, password_hash=password_hash, role=role,
                 full_name=full_name, email=email, is_active=1)
        s.add(u); s.commit(); uid = u.id
    audit("user.create", target=username, detail={"role": role}, user=by or SYSTEM_USER)
    return get_user(uid)

def set_user_password(uid, password_hash, by=None):
    with SessionLocal() as s:
        u = s.get(User, uid)
        if not u:
            return False
        u.password_hash = password_hash
        u.auth_version = (u.auth_version or 0) + 1
        s.commit(); un = u.username
    audit("user.password", target=un, user=by or SYSTEM_USER)
    return True

def update_user_profile(uid, new_username=None, full_name=None, email=None, new_password_hash=None, by=None):
    """Update user credentials / profile: username, full_name, email, and/or password.
    Increments auth_version if username or password changes so old tokens are superseded.
    """
    from sqlalchemy import func
    import re

    with SessionLocal() as s:
        u = s.get(User, uid)
        if not u:
            return None
        old_username = u.username
        credentials_changed = False

        if new_username is not None:
            clean_name = new_username.strip()
            if not clean_name:
                raise ValueError("Username cannot be empty")
            if len(clean_name) < 3 or len(clean_name) > 50:
                raise ValueError("Username must be between 3 and 50 characters")
            if not re.match(r'^[A-Za-z0-9_.-]+$', clean_name):
                raise ValueError("Username may only contain letters, numbers, hyphens, underscores, and periods")
            if clean_name.lower() != old_username.lower():
                existing = s.query(User).filter(func.lower(User.username) == clean_name.lower(), User.id != uid).first()
                if existing:
                    raise ValueError(f"Username '{clean_name}' is already taken")
                u.username = clean_name
                credentials_changed = True
            elif clean_name != old_username:
                u.username = clean_name
                credentials_changed = True

        if new_password_hash:
            u.password_hash = new_password_hash
            credentials_changed = True

        if full_name is not None:
            u.full_name = full_name.strip()
        if email is not None:
            u.email = email.strip()

        if credentials_changed:
            u.auth_version = (u.auth_version or 0) + 1

        s.commit()
        un = u.username

    if new_username and new_username != old_username:
        audit("user.rename", target=un, detail={"old": old_username, "new": un}, user=by or SYSTEM_USER)
    if new_password_hash:
        audit("user.password", target=un, user=by or SYSTEM_USER)
    if not (new_username and new_username != old_username) and not new_password_hash:
        audit("user.update_profile", target=un, user=by or SYSTEM_USER)

    return get_user(uid)

def set_user_role(uid, role, by=None):
    if role not in ROLES:
        raise ValueError("bad role")
    with SessionLocal() as s:
        u = s.get(User, uid)
        if not u:
            return False
        u.role = role; s.commit(); un = u.username
    audit("user.role", target=un, detail={"role": role}, user=by or SYSTEM_USER)
    return True

def set_user_active(uid, active, by=None):
    with SessionLocal() as s:
        u = s.get(User, uid)
        if not u:
            return False
        u.is_active = 1 if active else 0; s.commit(); un = u.username
    audit("user.active", target=un, detail={"active": bool(active)}, user=by or SYSTEM_USER)
    return True

def create_project(name, by, discipline=None):
    by = by or SYSTEM_USER
    with SessionLocal() as s:
        if s.query(Project).filter_by(name=name).first():
            raise ValueError("project already exists")
        from services.project_cleanup import allow_explicit_recreation
        allow_explicit_recreation(DATA_DIR, name)
        proj = Project(name=name, discipline=discipline, created_by=by["id"])
        s.add(proj); s.flush()
        s.add(ProjectMember(project_id=proj.id, user_id=by["id"], added_by=by["id"]))
        s.commit()
    allow_explicit_recreation(DATA_DIR, name, remove=True)
    audit("project.create", project=name, detail={"discipline": discipline}, user=by)
    return True

def assign_member(project, user_id, by=None):
    by = by or SYSTEM_USER
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            proj = Project(name=project, created_by=by["id"]); s.add(proj); s.flush()
        if not s.query(ProjectMember).filter_by(project_id=proj.id, user_id=user_id).first():
            s.add(ProjectMember(project_id=proj.id, user_id=user_id, added_by=by["id"]))
        s.commit()
    audit("member.add", project=project, target=user_id, user=by)
    return True

def remove_member(project, user_id, by=None):
    removed = False
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if proj:
            m = s.query(ProjectMember).filter_by(project_id=proj.id, user_id=user_id).first()
            if m:
                s.delete(m); s.commit(); removed = True
    if removed:
        audit("member.remove", project=project, target=user_id, user=by or SYSTEM_USER)
    return removed

def project_members(project):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return []
        rows = (s.query(ProjectMember, User)
                .join(User, ProjectMember.user_id == User.id)
                .filter(ProjectMember.project_id == proj.id).all())
        return [{"user_id": u.id, "username": u.username, "role": u.role,
                 "full_name": u.full_name or ""} for (m, u) in rows]

def user_projects(user_id):
    with SessionLocal() as s:
        rows = (s.query(Project.name)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .filter(ProjectMember.user_id == user_id)
                .order_by(Project.name).all())
        return [r[0] for r in rows if not r[0].startswith("__")]

def user_can_access(user, project):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return False
        return s.query(ProjectMember).filter_by(
            project_id=proj.id, user_id=user["id"]).first() is not None


# ============================================================
# Folders + folder-level permissions (flat, admin-created)
# ============================================================
class Folder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_folder_project_name"),)

class FolderMember(Base):
    __tablename__ = "folder_members"
    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    added_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("folder_id", "user_id", name="uq_foldermember"),)

def _folder_access(sess, user, proj):
    """(allow_all, folder_ids). allow_all=True means every folder in the project
    (admin, or lead who is a project member). Otherwise folder_ids is the exact
    set the user may access (a regular member sees ONLY assigned folders; a
    non-member sees nothing)."""
    role = (user or {}).get("role")
    if role == "admin":
        return True, None
    is_member = sess.query(ProjectMember).filter_by(
        project_id=proj.id, user_id=user["id"]).first() is not None
    if role == "lead" and is_member:
        return True, None
    if not is_member:
        return False, set()
    rows = (sess.query(FolderMember.folder_id)
            .join(Folder, Folder.id == FolderMember.folder_id)
            .filter(Folder.project_id == proj.id,
                    FolderMember.user_id == user["id"]).all())
    return False, {r[0] for r in rows}

def folder_access(user, project):
    """Public: (allow_all, folder_ids_set). folder_ids is a set (possibly empty)
    when not allow_all. Used by RAG retrieval to enforce access."""
    if not user:
        return False, set()
    with SessionLocal() as sess:
        proj = sess.query(Project).filter_by(name=project).first()
        if not proj:
            return (user.get("role") == "admin"), set()
        allow_all, ids = _folder_access(sess, user, proj)
        return allow_all, (None if allow_all else set(ids or set()))

def create_folder(project, name, by=None):
    by = by or SYSTEM_USER
    name = (name or "").strip()
    if not name:
        raise ValueError("folder name required")
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            proj = Project(name=project, created_by=by["id"]); s.add(proj); s.flush()
        if s.query(Folder).filter_by(project_id=proj.id, name=name).first():
            raise ValueError("folder already exists")
        f = Folder(project_id=proj.id, name=name, created_by=by["id"])
        s.add(f); s.commit(); fid = f.id
    audit("folder.create", project=project, target=name, user=by)
    return {"id": fid, "name": name}

def list_folders(project):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return []
        out = []
        for f in s.query(Folder).filter_by(project_id=proj.id).order_by(Folder.name).all():
            cnt = s.query(Document).filter_by(project_id=proj.id, folder_id=f.id).count()
            mem = s.query(FolderMember).filter_by(folder_id=f.id).count()
            out.append({"id": f.id, "name": f.name, "doc_count": cnt, "member_count": mem})
        return out

def get_folder(project, name):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return None
        f = s.query(Folder).filter_by(project_id=proj.id, name=name).first()
        return {"id": f.id, "name": f.name} if f else None

def get_folder_by_id(folder_id):
    with SessionLocal() as s:
        f = s.get(Folder, folder_id)
        return {"id": f.id, "name": f.name, "project_id": f.project_id} if f else None

def rename_folder(folder_id, name, by=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    with SessionLocal() as s:
        f = s.get(Folder, folder_id)
        if not f:
            return False
        if s.query(Folder).filter(Folder.project_id == f.project_id,
                                  Folder.name == name, Folder.id != folder_id).first():
            raise ValueError("folder name already exists")
        f.name = name; s.commit()
    audit("folder.rename", target=name, user=by or SYSTEM_USER)
    return True

def delete_folder(folder_id, by=None):
    with SessionLocal() as s:
        f = s.get(Folder, folder_id)
        if not f:
            return False
        s.query(Document).filter_by(folder_id=folder_id).update({Document.folder_id: None})
        s.query(FolderMember).filter_by(folder_id=folder_id).delete()
        nm = f.name; s.delete(f); s.commit()
    audit("folder.delete", target=nm, user=by or SYSTEM_USER)
    return True

def assign_folder_member(folder_id, user_id, by=None):
    with SessionLocal() as s:
        if not s.get(Folder, folder_id):
            return False
        if not s.query(FolderMember).filter_by(folder_id=folder_id, user_id=user_id).first():
            s.add(FolderMember(folder_id=folder_id, user_id=user_id,
                               added_by=(by or SYSTEM_USER)["id"]))
            s.commit()
    audit("folder.member.add", target=str(folder_id), detail={"user_id": user_id},
          user=by or SYSTEM_USER)
    return True

def remove_folder_member(folder_id, user_id, by=None):
    removed = False
    with SessionLocal() as s:
        m = s.query(FolderMember).filter_by(folder_id=folder_id, user_id=user_id).first()
        if m:
            s.delete(m); s.commit(); removed = True
    if removed:
        audit("folder.member.remove", target=str(folder_id), detail={"user_id": user_id},
              user=by or SYSTEM_USER)
    return removed

def folder_members(folder_id):
    with SessionLocal() as s:
        rows = (s.query(FolderMember, User).join(User, FolderMember.user_id == User.id)
                .filter(FolderMember.folder_id == folder_id).all())
        return [{"user_id": u.id, "username": u.username, "role": u.role,
                 "full_name": u.full_name or ""} for (m, u) in rows]

def user_folder_ids_for(user, project):
    """Folder ids a user may access in a project; None means all (full access)."""
    allow_all, ids = folder_access(user, project)
    return None if allow_all else ids

def set_document_folder(project, filename, folder_id, by=None):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return False
        d = s.query(Document).filter_by(project_id=proj.id, filename=filename).first()
        if not d:
            return False
        d.folder_id = folder_id; s.commit()
    audit("document.move", project=project, target=filename,
          detail={"folder_id": folder_id}, user=by or SYSTEM_USER)
    return True

def doc_folder_map(project):
    """filename -> folder_id for every doc in the project (RAG enforcement fallback)."""
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return {}
        return {d.filename: d.folder_id
                for d in s.query(Document).filter_by(project_id=proj.id).all()}


def update_document_status(project, filename, chunks, status):
    with SessionLocal() as sess:
        proj = sess.query(Project).filter_by(name=project).first()
        if not proj:
            return False
        d = (sess.query(Document).filter_by(project_id=proj.id, filename=filename)
             .order_by(Document.id.desc()).first())
        if not d:
            return False
        d.chunks = chunks
        d.status = status
        sess.commit()
    return True


# ============================================================
# Phase 0: Knowledge Hub tables (additive — existing tables untouched)
# ============================================================

class DocMeta(Base):
    """Extended document metadata for provenance and authority."""
    __tablename__ = "doc_meta"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    doc_number = Column(String(200), default="")
    revision = Column(String(50), default="")
    section = Column(String(200), default="")
    discipline = Column(String(40), nullable=True)
    doc_date = Column(String(50), nullable=True)
    status = Column(String(20), default="draft")
    authority_level = Column(Integer, default=0)
    jurisdiction = Column(String(100), default="")
    effective_date = Column(String(50), nullable=True)
    applicable_scope = Column(Text, default="")


class Requirement(Base):
    """Extracted code requirements with full provenance."""
    __tablename__ = "requirements"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    req_id = Column(String(100), nullable=False)
    title = Column(Text, default="")
    description = Column(Text, default="")
    value = Column(Text, default="")
    unit = Column(String(50), default="")
    source_type = Column(String(50), default="")
    source_doc = Column(String(400), default="")
    source_page = Column(Integer, nullable=True)
    source_clause = Column(String(200), default="")
    evidence = Column(Text, default="")
    confidence = Column(String(20), default="medium")
    status = Column(String(20), default="draft")
    version = Column(String(50), default="")
    authority_rank = Column(Integer, default=0)
    discipline = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("project_id", "req_id", name="uq_requirement_project_reqid"),)


class Evidence(Base):
    """Typed evidence objects with provenance."""
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    evidence_id = Column(String(100), nullable=False)
    evidence_type = Column(String(50), default="")
    content = Column(Text, default="")
    source_doc = Column(String(400), default="")
    source_page = Column(Integer, nullable=True)
    bounding_box = Column(JSON, nullable=True)
    confidence = Column(Float, default=0.0)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("project_id", "evidence_id", name="uq_evidence_project_id"),)


class SourcePrecedence(Base):
    """Configurable source authority/precedence per project/discipline."""
    __tablename__ = "source_precedence"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    discipline = Column(String(40), nullable=True)
    rank = Column(Integer, default=0)
    source_type = Column(String(50), default="")
    source_doc_pattern = Column(String(400), default="")
    effective_date = Column(String(50), nullable=True)
    notes = Column(Text, default="")


class GraphEdge(Base):
    """Knowledge graph relationships between entities."""
    __tablename__ = "graph_edges"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    src_type = Column(String(50), default="")
    src_id = Column(String(100), default="")
    relation = Column(String(100), default="")
    dst_type = Column(String(50), default="")
    dst_id = Column(String(100), default="")
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class EngineeringRule(Base):
    """Version-controlled engineering rules (deterministic, independent from LLMs)."""
    __tablename__ = "engineering_rules"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    rule_id = Column(String(100), nullable=False)
    discipline = Column(String(40), nullable=True)
    category = Column(String(100), default="")
    title = Column(Text, default="")
    description = Column(Text, default="")
    rule_type = Column(String(50), default="deterministic")
    rule_definition = Column(JSON, nullable=True)
    version = Column(String(50), default="1.0")
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("project_id", "rule_id", name="uq_rule_project_id"),)


class QAFinding(Base):
    """QA findings with lifecycle (replaces unused findings table)."""
    __tablename__ = "qa_findings"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    finding_id = Column(String(100), nullable=False)
    discipline = Column(String(40), nullable=True)
    severity = Column(String(20), default="medium")
    status = Column(String(20), default="open")
    check_id = Column(String(100), default="")
    issue = Column(Text, default="")
    required_value = Column(Text, default="")
    actual_value = Column(Text, default="")
    difference = Column(Text, default="")
    calculation = Column(Text, default="")
    rule_id = Column(String(100), default="")
    evidence = Column(Text, default="")
    source_doc = Column(String(400), default="")
    source_page = Column(Integer, nullable=True)
    confidence = Column(Float, default=0.0)
    recommendation = Column(Text, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    revision = Column(String(50), default="")
    __table_args__ = (UniqueConstraint("project_id", "finding_id", name="uq_finding_project_id"),)


class BimModel(Base):
    """IFC/Revit model registry."""
    __tablename__ = "bim_models"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    filename = Column(String(400), default="")
    ifc_schema = Column(String(50), default="")
    length_unit = Column(String(20), default="")
    true_north_deg = Column(Float, nullable=True)
    site_origin = Column(JSON, nullable=True)
    coordination_matrix = Column(JSON, nullable=True)
    element_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)


class BimElement(Base):
    """Typed BIM elements (GUID is the stable cross-domain key)."""
    __tablename__ = "bim_elements"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    bim_model_id = Column(Integer, ForeignKey("bim_models.id"), nullable=True)
    guid = Column(String(100), default="")
    ifc_class = Column(String(100), default="")
    type_name = Column(String(200), default="")
    name = Column(String(400), default="")
    level = Column(String(200), default="")
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    thickness = Column(Float, nullable=True)
    area = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    material = Column(String(200), default="")
    system = Column(String(200), default="")
    classification = Column(String(200), default="")
    psets = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Drawing(Base):
    """Drawing metadata."""
    __tablename__ = "drawings"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    number = Column(String(200), default="")
    title = Column(Text, default="")
    revision = Column(String(50), default="")
    discipline = Column(String(40), nullable=True)
    level = Column(String(100), default="")
    sheet = Column(String(100), default="")
    sheet_date = Column(String(50), nullable=True)
    status = Column(String(20), default="draft")
    file_path = Column(Text, default="")
    page = Column(Integer, nullable=True)
    source = Column(String(200), default="")


class Schedule(Base):
    """Schedule registry."""
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    schedule_type = Column(String(100), default="")
    source_sheet = Column(String(200), default="")
    created_at = Column(DateTime, default=_utcnow)



class StructuredRecord(Base):
    __tablename__ = "structured_records"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    doc = Column(String, index=True)
    revision = Column(String)
    page = Column(Integer)
    schedule = Column(String)
    tower = Column(String, index=True)
    level = Column(String, index=True)
    field = Column(String, index=True)
    raw_value = Column(String)
    value = Column(Float)
    unit = Column(String)
    row_idx = Column(Integer)
    col_idx = Column(Integer)
    source_bbox = Column(String)
    # Phase 5A: Additive visual extraction
    entity = Column(String)
    row_label = Column(String)
    column_label = Column(String)
    confidence = Column(String, default="HIGH")
    extraction_method = Column(String, default="DIGITAL")
    source_type = Column(String, default="PDF_TEXT")

class ScheduleRow(Base):
    """Individual schedule rows with typed fields."""
    __tablename__ = "schedule_rows"
    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    mark = Column(String(100), default="")
    guid = Column(String(100), default="")
    fields = Column(JSON, nullable=True)
    # Phase 2: Structured table extraction
    doc = Column(String(400), default="")  # Source document filename
    page = Column(Integer, nullable=True)  # Page number
    table_name = Column(String(200), default="")  # Table/schedule/legend name
    row_key = Column(String(200), default="")  # Searchable row key (e.g., "LX-PT", "TOS Tower 1")
    row_values = Column(JSON, nullable=True)  # Full row data as JSON
    revision = Column(String(50), default="")  # Document revision
    created_at = Column(DateTime, default=_utcnow)


class DocumentMemory(Base):
    """Phase 1 (2026-10-08): AI Document Memory layer. One row per fact an
    LLM identified while reading a whole document end-to-end, relationship-
    aware (section/table/entity/parent_context) rather than a flat fact
    store. Additive to StructuredRecord/Quantity (which capture table cells
    mechanically) -- this captures prose facts, defined terms and
    cross-references no cell-level extractor produces, plus a second,
    independent extraction path for table facts that is not subject to the
    same parsing-bug classes as table_evidence.table_row_units().

    evidence_state values: PENDING (never left set after ingestion commits;
    present only transiently) | VERIFIED (evidence_quote confirmed verbatim
    in the source page text) | REVIEW_REQUIRED (a real candidate fact whose
    evidence_quote did not verify -- persisted, NOT discarded, with
    review_reason explaining why) | REJECTED (structurally degenerate model
    output -- empty/near-empty quote, exact duplicate -- not a real
    candidate, kept only for audit) | SUPERSEDED (superseded_at set on
    re-upload/re-extraction; row kept for history, never deleted).

    Only VERIFIED rows are eligible to answer a question directly at query
    time (Phase 2+); REVIEW_REQUIRED/REJECTED/SUPERSEDED rows exist for
    audit and reviewer visibility, never as a trusted answer source.
    """
    __tablename__ = "document_memory"
    id = Column(Integer, primary_key=True)

    # --- identity / provenance ---
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    doc = Column(String(400), nullable=False, index=True)  # denormalized filename, for display/debug without a join
    revision = Column(String(40), default="")
    source_sha256 = Column(String(64), nullable=False, index=True)  # invalidate memory if file content changes

    # --- structural location ---
    page = Column(Integer, nullable=True, index=True)
    section = Column(String(300), default="", index=True)   # narrative heading, e.g. "Means of Egress"
    table = Column(String(300), default="", index=True)     # specific schedule/table, e.g. "AREA STATEMENT SUMMARY"
    entity = Column(String(120), default="", index=True)    # e.g. "TOWER 2" -- matches StructuredRecord.entity convention
    parent_context = Column(String(300), default="")        # qualification ("applies only if sprinklered") or parent row
                                                             # ("sub-row of RESIDENTIAL UNIT BREAKDOWN > 2BR-Type 3")

    # --- the fact itself ---
    property = Column(String(300), nullable=False)          # short matching key, e.g. "Plot Area"
    claim = Column(Text, nullable=False)                     # full sentence, human-readable
    value = Column(String(200), default="")
    unit = Column(String(50), default="")
    topic_tags = Column(JSON, default=list)

    # --- evidence & trust ---
    evidence_quote = Column(Text, nullable=False)            # verbatim substring of the source page's stored text/tables
    evidence_source = Column(String(40), default="")        # "text" | "table_row" | "vision"
    evidence_state = Column(String(20), nullable=False, default="PENDING", index=True)
    review_reason = Column(Text, default="")                # set only when evidence_state == REVIEW_REQUIRED
    confidence = Column(String(20), default="HIGH")          # model's own stated confidence -- independent of evidence_state

    # --- bookkeeping ---
    built_by_model = Column(String(80), default="")
    created_at = Column(DateTime, default=_utcnow)
    superseded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_memory_project_entity_property", "project_id", "entity", "property"),
        Index("ix_memory_project_state", "project_id", "evidence_state"),
    )


class EvalDataset(Base):
    """Evaluation datasets for AI quality measurement."""
    __tablename__ = "eval_datasets"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    dataset_type = Column(String(50), default="")
    created_at = Column(DateTime, default=_utcnow)


class Quantity(Base):
    """Phase 2: Structured numeric quantities (TOS/TOPR levels, areas, dimensions)."""
    __tablename__ = "quantities"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    building = Column(String(200), default="")  # Building/tower name
    metric = Column(String(100), default="")  # e.g., TOS, TOPR, GFA, dimension
    value = Column(String(100), default="")  # Numeric value as string
    unit = Column(String(50), default="")  # e.g., m, mm, m2
    source_doc = Column(String(400), default="")
    source_page = Column(Integer, nullable=True)
    revision = Column(String(50), default="")
    created_at = Column(DateTime, default=_utcnow)


class EvalExample(Base):
    """Individual evaluation examples."""
    __tablename__ = "eval_examples"
    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("eval_datasets.id"), nullable=True)
    input = Column(Text, default="")
    expected_output = Column(Text, default="")
    source = Column(String(400), default="")
    verification_status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=_utcnow)


class UserUpload(Base):
    """A document a user attaches directly in the AI chat (the "+" button),
    separate from the shared, admin/lead-managed project document corpus.
    Private to the uploading user (and visible to admins for oversight only);
    it is NEVER added to the project's folders/documents list, FAISS index,
    or ScheduleRow table — grounding for it is injected ad hoc per question,
    the same way focus_doc works for a project document."""
    __tablename__ = "user_uploads"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String(400), nullable=False)
    path = Column(Text, default="")
    status = Column(String(20), default="processing")  # processing | ready | error
    size = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)


def create_user_upload(user_id, project, filename, path, size=0):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            raise ValueError("project not found")
        row = UserUpload(user_id=user_id, project_id=proj.id, filename=filename,
                         path=path, status="processing", size=size)
        s.add(row); s.commit()
        return {"id": row.id, "filename": row.filename, "status": row.status,
                "size": row.size, "created_at": row.created_at.isoformat()}

def update_user_upload_status(upload_id, status):
    with SessionLocal() as s:
        row = s.query(UserUpload).filter_by(id=upload_id).first()
        if row:
            row.status = status
            s.commit()

def get_user_upload(upload_id):
    with SessionLocal() as s:
        row = s.query(UserUpload).filter_by(id=upload_id).first()
        if not row:
            return None
        proj = s.query(Project).filter_by(id=row.project_id).first()
        return {"id": row.id, "user_id": row.user_id, "project": proj.name if proj else None,
                "filename": row.filename, "path": row.path, "status": row.status,
                "size": row.size, "created_at": row.created_at.isoformat()}

def list_user_uploads(user_id, project):
    with SessionLocal() as s:
        proj = s.query(Project).filter_by(name=project).first()
        if not proj:
            return []
        rows = (s.query(UserUpload)
                .filter_by(user_id=user_id, project_id=proj.id)
                .order_by(UserUpload.created_at.desc()).all())
        return [{"id": r.id, "filename": r.filename, "status": r.status,
                 "size": r.size, "created_at": r.created_at.isoformat()} for r in rows]

def delete_user_upload(upload_id):
    with SessionLocal() as s:
        row = s.query(UserUpload).filter_by(id=upload_id).first()
        if not row:
            return False
        path = row.path
        s.delete(row); s.commit()
    try:
        if path and os.path.isfile(path):
            os.remove(path)
        if path and os.path.isfile(path + ".extracted.txt"):
            os.remove(path + ".extracted.txt")
    except Exception:
        pass
    return True

def list_all_user_uploads(project=None):
    """Admin oversight only — never merged into any project's shared document
    listing. Read-only: who uploaded what, where, and when."""
    with SessionLocal() as s:
        q = (s.query(UserUpload, User.username, Project.name)
             .join(User, User.id == UserUpload.user_id)
             .join(Project, Project.id == UserUpload.project_id)
             .order_by(UserUpload.created_at.desc()))
        if project:
            q = q.filter(Project.name == project)
        out = []
        for row, username, project_name in q.limit(2000).all():
            out.append({"id": row.id, "username": username, "project": project_name,
                        "filename": row.filename, "status": row.status, "size": row.size,
                        "created_at": row.created_at.isoformat()})
        return out


def init_knowledge_tables():
    """Create Phase 0 Knowledge Hub tables. Idempotent."""
    Base.metadata.create_all(engine)
    logger.info("Knowledge Hub tables initialized")

class PageRecord(Base):
    __tablename__ = "page_records"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_filename = Column(String, index=True)
    page_number = Column(Integer, index=True)
    page_status = Column(String, default="PENDING")
    text_extracted = Column(Integer, default=0)
    native_table_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    ocr_status = Column(String, default="PENDING")
    vision_status = Column(String, default="PENDING")
    structured_record_count = Column(Integer, default=0)
    rag_chunk_count = Column(Integer, default=0)
    processing_started = Column(DateTime)
    processing_completed = Column(DateTime)
    processing_error = Column(String)

class ImageRecord(Base):
    __tablename__ = "image_records"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_filename = Column(String, index=True)
    page_number = Column(Integer, index=True)
    image_id = Column(String, index=True)
    image_index = Column(Integer)
    image_path = Column(String)
    width = Column(Integer)
    height = Column(Integer)
    image_type = Column(String, default="UNKNOWN")
    ocr_text = Column(String)
    visual_description = Column(String)
    ocr_status = Column(String, default="PENDING")
    vision_status = Column(String, default="PENDING")
    structured_extraction_status = Column(String, default="PENDING")
    confidence = Column(Float)
    processing_error = Column(String)
    created_at = Column(DateTime)


def _generate_job_id() -> str:
    return f"imgjob-{uuid.uuid4().hex[:12]}"


def _generate_output_id() -> str:
    return f"out-{uuid.uuid4().hex[:12]}"


class ImageJob(Base):
    """Persistent tracking for local ComfyUI image-generation jobs."""
    __tablename__ = "image_jobs"
    id = Column(String(64), primary_key=True, default=_generate_job_id)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    workflow_id = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="queued", index=True)
    comfy_prompt_id = Column(String(100), nullable=True)
    input_params = Column(JSON, nullable=False)
    progress = Column(Integer, default=0)
    current_step = Column(Integer, nullable=True)
    total_steps = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime, nullable=True)
    outputs = relationship("ImageOutput", back_populates="job", cascade="all, delete-orphan")


class ImageOutput(Base):
    """Persisted reference to a generated image file and thumbnail."""
    __tablename__ = "image_outputs"
    id = Column(String(64), primary_key=True, default=_generate_output_id)
    job_id = Column(String(64), ForeignKey("image_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    thumbnail_path = Column(Text, nullable=True)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=True)
    output_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    job = relationship("ImageJob", back_populates="outputs")


def create_image_job(job_id: str, project_id: int, user_id: int, workflow_id: str, input_params: dict) -> dict:
    """Create a new image generation job record in queued state."""
    with SessionLocal() as s:
        job = ImageJob(
            id=job_id,
            project_id=project_id,
            user_id=user_id,
            workflow_id=workflow_id,
            status="queued",
            input_params=input_params,
            progress=0,
            created_at=_utcnow(),
        )
        s.add(job)
        s.commit()
        return {
            "id": job.id,
            "project_id": job.project_id,
            "user_id": job.user_id,
            "workflow_id": job.workflow_id,
            "status": job.status,
            "progress": job.progress,
            "created_at": job.created_at.isoformat(),
        }


def update_image_job(job_id: str, **kwargs) -> Optional[dict]:
    """Update fields on an existing image generation job."""
    with SessionLocal() as s:
        job = s.query(ImageJob).filter_by(id=job_id).first()
        if not job:
            return None
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = _utcnow()
        s.commit()
        return {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "total_steps": job.total_steps,
            "error_message": job.error_message,
            "comfy_prompt_id": job.comfy_prompt_id,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }


def get_image_job(job_id: str) -> Optional[dict]:
    """Retrieve an image job with its output records."""
    with SessionLocal() as s:
        job = s.query(ImageJob).filter_by(id=job_id).first()
        if not job:
            return None
        outputs = []
        for out in job.outputs:
            outputs.append({
                "id": out.id,
                "filename": out.filename,
                "file_path": out.file_path,
                "thumbnail_path": out.thumbnail_path,
                "width": out.width,
                "height": out.height,
                "seed": out.seed,
                "metadata": out.output_metadata or {},
                "created_at": out.created_at.isoformat() if out.created_at else None,
            })
        return {
            "id": job.id,
            "project_id": job.project_id,
            "user_id": job.user_id,
            "workflow_id": job.workflow_id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "total_steps": job.total_steps,
            "input_params": job.input_params,
            "error_message": job.error_message,
            "comfy_prompt_id": job.comfy_prompt_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "outputs": outputs,
        }


def list_image_jobs(project_id: int, user_id: Optional[int] = None, limit: int = 50) -> list:
    """List most recent image jobs for a project."""
    with SessionLocal() as s:
        q = s.query(ImageJob).filter_by(project_id=project_id)
        if user_id is not None:
            q = q.filter_by(user_id=user_id)
        rows = q.order_by(ImageJob.created_at.desc()).limit(limit).all()
        results = []
        for job in rows:
            results.append({
                "id": job.id,
                "project_id": job.project_id,
                "user_id": job.user_id,
                "workflow_id": job.workflow_id,
                "status": job.status,
                "progress": job.progress,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "output_count": len(job.outputs),
            })
        return results


def add_image_output(
    output_id: str,
    job_id: str,
    filename: str,
    file_path: str,
    thumbnail_path: Optional[str],
    width: int,
    height: int,
    seed: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Record a generated output image attached to an ImageJob."""
    with SessionLocal() as s:
        out = ImageOutput(
            id=output_id,
            job_id=job_id,
            filename=filename,
            file_path=file_path,
            thumbnail_path=thumbnail_path,
            width=width,
            height=height,
            seed=seed,
            output_metadata=metadata or {},
            created_at=_utcnow(),
        )
        s.add(out)
        s.commit()
        return {
            "id": out.id,
            "job_id": out.job_id,
            "filename": out.filename,
            "file_path": out.file_path,
            "thumbnail_path": out.thumbnail_path,
            "width": out.width,
            "height": out.height,
            "seed": out.seed,
        }


def get_image_output(output_id: str) -> Optional[dict]:
    """Get single image output record by ID."""
    with SessionLocal() as s:
        out = s.query(ImageOutput).filter_by(id=output_id).first()
        if not out:
            return None
        return {
            "id": out.id,
            "job_id": out.job_id,
            "filename": out.filename,
            "file_path": out.file_path,
            "thumbnail_path": out.thumbnail_path,
            "width": out.width,
            "height": out.height,
            "seed": out.seed,
            "metadata": out.output_metadata or {},
        }
