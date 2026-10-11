import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class Project(Base):
    __tablename__ = "project"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ProjectFolder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    relative_path = Column(String(500), nullable=False, unique=True)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ProjectFile(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    filename = Column(String(400), nullable=False)
    relative_path = Column(String(500), nullable=False, unique=True)
    file_type = Column(String(50), nullable=False) # e.g. PDF, RVT, DWG
    source_type = Column(String(50), nullable=False) # e.g. Document, Drawing, Model, Schedule
    status = Column(String(50), default="ready")
    created_at = Column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    discipline = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Drawing(Base):
    __tablename__ = "drawings"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    sheet_number = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Model(Base):
    __tablename__ = "models"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    model_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Specification(Base):
    __tablename__ = "specifications"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Requirement(Base):
    __tablename__ = "requirements"
    id = Column(Integer, primary_key=True)
    specification_id = Column(Integer, ForeignKey("specifications.id"), nullable=True)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class StructuredRecord(Base):
    """Normalized evidence extracted from a source"""
    __tablename__ = "structured_records"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    revision = Column(String(100), nullable=True)
    page_or_sheet = Column(String(100), nullable=True)
    schedule = Column(String(200), nullable=True)
    tower = Column(String(200), nullable=True)
    level = Column(String(200), nullable=True)
    entity = Column(String(200), nullable=False)
    field = Column(String(200), nullable=False)
    raw_value = Column(String(500), nullable=True)
    value = Column(Float, nullable=True)
    unit = Column(String(50), nullable=True)
    extraction_method = Column(String(100), nullable=False)
    confidence = Column(String(50), default="HIGH")
    validation_status = Column(String(50), default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)

class Evidence(Base):
    """Evidence concept explicitly separated"""
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    structured_record_id = Column(Integer, ForeignKey("structured_records.id"), nullable=True)
    description = Column(Text, nullable=False)
    source_authority = Column(String(100), default="AI Extraction") # Native PDF, AI Extraction, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

class Finding(Base):
    """QA/Compliance issue derived from evidence"""
    __tablename__ = "findings"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="OPEN") # OPEN, RESOLVED, CONFLICT
    primary_evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    confirmation_evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Relationship(Base):
    """Graph relationships"""
    __tablename__ = "relationships"
    id = Column(Integer, primary_key=True)
    source_type = Column(String(50), nullable=False) # File, Evidence, Finding, Model Element
    source_id = Column(Integer, nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(Integer, nullable=False)
    relation = Column(String(100), nullable=False) # e.g. "conflicts_with", "derived_from", "verifies"
    created_at = Column(DateTime, default=datetime.utcnow)

class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    engine = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id = Column(Integer, primary_key=True)
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=True)
    result = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Version(Base):
    __tablename__ = "versions"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    version_number = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Cache(Base):
    __tablename__ = "cache"
    id = Column(Integer, primary_key=True)
    key = Column(String(250), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_project_session(project_name: str):
    """
    Resolves the connection boundary explicitly based on project_name.
    Does not allow querying across projects.
    """
    from db import DATA_DIR
    from services.ingestion import contained_upload_path
    contained_upload_path(os.path.join(DATA_DIR,'docs'),project_name,'validation','project.db')
    project_path = os.path.join(DATA_DIR, "docs", project_name)
    db_dir = os.path.join(project_path, ".opencompany")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "project.db")
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
