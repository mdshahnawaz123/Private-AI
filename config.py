"""
Centralized configuration for Expo Design AI (Phase 0).

Uses pydantic-settings for environment-based configuration.
All paths relative to EXPO_DATA_DIR. No hardcoded machine-specific paths.
"""
import os
from typing import List, Optional, Annotated
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    host: str = "127.0.0.1"
    port: int = 8090
    cors_origins: Annotated[List[str], NoDecode] = []

    # Database
    database_url: str = ""

    # Data directory
    data_dir: str = "data"

    # Auth
    secret: str = ""
    token_ttl_hours: int = 12
    admin_password: str = "admin"

    # AI models
    vision_model: str = "qwen2.5vl:7b"
    embed_model: str = "bge-m3"
    fast_llm: str = "qwen2.5:7b"
    fast_llm_enabled: bool = False
    reranker_model: str = "bge-reranker-v2-m3"
    # Re-enabled (was False): with it off, /ask_stream falls back to raw
    # vector+BM25 top-k (main.py ~line 2090, docs = permitted[:k]) with no
    # cross-encoder pass. Confirmed via live C3085 testing that this makes any
    # document with repeated near-identical sections (multiple towers/
    # buildings/typical floors) effectively blind past the first section: a
    # bi-encoder + BM25 RRF can't reliably tell 'Tower 2 Floor GFA' from
    # 'Tower 1 Floor GFA' when the surrounding table boilerplate is near-
    # identical, so the wrong (or no) row lands in the top-k and the answer
    # guard correctly refuses rather than publish an uncited number. A cross-
    # encoder reads query+passage jointly and is specifically good at this
    # kind of fine discrimination. Falls back to unreranked order automatically
    # (reranker.py _load_model) if sentence-transformers or the model weights
    # are not available -- never a hard failure.
    reranker_enabled: bool = True

    # Wave 1: Model tiering
    worker_model: str = "qwen2.5vl:7b"
    author_model: str = "qwen2.5vl:7b"
    chat_model: str = "qwen3.5:9b"  # Installed text model; vision uses vision_model separately.
    enable_model_tiering: bool = False
    rerank_candidates: int = 20
    rerank_keep: int = 5
    enable_query_expansion: bool = False  # Wave 1.5: expand short/coded queries via worker model
    enable_hybrid_bm25: bool = True  # fuse BM25 keyword search with vector search (RRF) in the main RAG path
    enable_metadata_prefilter: bool = False  # Wave 1.5: pre-filter candidates by metadata before ranking

    # V2 UI (professional Design Workspace redesign) — additive, reversible
    enable_ui_v2: bool = False  # serve the V2 UI (ui/app.html) at "/" ; False keeps the current ui/index.html
    enable_clash_action: bool = False  # show the Copilot "Check for clashes" action (no clash engine yet — keep off)

    # Phase 2: Structured data
    enable_structured_tables: bool = True  # extract EVERY table (area/parking/lift/unit-mix) as structured rows for exact lookup
    enable_quantities_store: bool = True  # capture numeric quantities as structured data
    enable_self_check: bool = False  # Phase 2: worker model self-check for answer verification
    enable_legacy_schedule_context: bool = False  # Legacy flat grids can lose column/entity alignment.
    enable_document_memory: bool = True  # Phase 1 validation run (2026-10-08): on, scoped to the two benchmark documents only via the allowlist below
    document_memory_doc_allowlist: Annotated[List[str], NoDecode] = [
        "C3085-RPT-3EH6105-FP-0000001(5).pdf",
        "260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf",
    ]  # Phase 1 scope guard: memory build only runs for filenames in this list, regardless of enable_document_memory
    document_memory_model: str = "qwen3.5:9b"  # REASONING_LLM; qwen2.5:7b only if latency requires it
    not_found_threshold: float = 0.0  # Phase 2 FIX: 0.3 was miscalibrated for bge-reranker-v2-m3 (relevant chunks score ~0.01-0.06), which silently discarded valid retrievals. 0.0 disables the score-gate; honest "not found" is still handled by the answer prompt. Recalibrate later with eval data.

    # Accurate extraction: run the vision model (qwen2.5vl:7b) on EVERY PDF page
    # at upload, not only image-only pages, so dense multi-table data sheets keep
    # their row/column structure. Heavy but accurate; set False to revert to the
    # fast "smart" mode (vision only on image-only pages).
    pdf_vision_all: bool = False  # geometry engine handles text-layer tables fast; vision only for scans
    vision_max_pages: int = 300  # safety cap on pages vision-read per PDF at upload

    # Ollama
    ollama_host: str = "http://127.0.0.1:11434"
    # Pilot architecture blueprint Sec 6.2: vision and chat/text roles can point
    # at two separate Ollama processes/ports so the heavy image-bearing upload
    # workload (admin-side) never contends with the concurrent user-facing chat
    # workload. Empty = both ride ollama_host (today's single-process behavior,
    # unchanged). Set EXPO_VISION_OLLAMA_HOST / EXPO_CHAT_OLLAMA_HOST to split
    # them later with no other code change.
    vision_ollama_host: str = ""
    chat_ollama_host: str = ""
    keep_alive: str = "5m"
    vision_retries: int = 3
    embed_retries: int = 5
    embed_timeout: int = 120
    embed_batch: int = 48
    num_ctx: int = 16384
    chat_retries: int = 3

    # 3D Render & Diffusion Model (Configurable: Qwen-Image-2.1-Turbo, FLUX.2-klein-4B, etc.)
    render_model: str = "FLUX.2-klein-4B"
    render_provider: str = "local"  # 'local' (offline ComfyUI / Diffusers / Ollama endpoint) or 'cloud'
    render_host: str = "http://127.0.0.1:8188"  # local endpoint (e.g. ComfyUI / Diffusers / SD-WebUI)
    render_api_key: str = ""  # optional cloud API key if using cloud provider (e.g. DashScope, Replicate, BFL)

    # CAD
    oda_converter: str = ""

    # Processing
    chunk_size: int = 800
    chunk_overlap: int = 80
    retrieval_k: int = 8
    max_pages: int = 1000
    min_chars_for_vision: int = 40

    # Security
    force_password_change: bool = True
    # Raised from 500 to 2000 (2026-10-09): 3D models (.ifc) for this project
    # run up to ~770MB on disk, well over the original 500MB cap, which was
    # sized for PDFs/drawings, not full IFC exports. Still a hard cap (not
    # unlimited) to keep the disk-fill-DoS protection in save_upload_capped()
    # meaningful -- raise further via EXPO_MAX_UPLOAD_SIZE_MB in .env if a
    # future model exceeds this instead of editing this default again.
    max_upload_size_mb: int = 2000

    # Logging
    log_level: str = "INFO"
    log_rotation: str = "10 MB"
    log_retention: str = "60 days"

    model_config = SettingsConfigDict(env_prefix='EXPO_',env_file='.env',env_file_encoding='utf-8',extra='ignore')

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_origins(cls,value):
        if isinstance(value,str):
            import json
            return json.loads(value) if value.strip().startswith('[') else [v.strip() for v in value.split(',') if v.strip()]
        return value

    @field_validator('chat_model','vision_model','worker_model','author_model','fast_llm')
    @classmethod
    def permitted_model(cls,value):
        if value not in {'qwen2.5:7b','qwen2.5vl:7b','qwen3.5:9b'}:
            raise ValueError('Only Qwen 2.5 7B and Qwen 3.5 9B are enabled')
        return value

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set defaults that depend on other fields
        if not self.database_url:
            self.database_url = f"sqlite:///{os.path.join(self.data_dir, 'expo.db')}"
        if not self.cors_origins:
            self.cors_origins = [
                f"http://127.0.0.1:{self.port}",
                f"http://localhost:{self.port}",
            ]


# Singleton instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# -- Model-serving role resolution (Pilot architecture blueprint Sec 6.1) --
# Every model call site should resolve {model, base_url} through this function
# instead of reading a settings.*_model / settings.ollama_host field directly,
# so a future split onto separate processes/ports (Sec 6.2) or a swap to a
# different serving stack only ever requires a config change here.
_MODEL_ROLES = ("vision", "chat", "worker", "author", "embed", "render")

def resolve_role(role: str) -> dict:
    """Resolve a model role to {'model': <name>, 'base_url': <endpoint>}."""
    if role not in _MODEL_ROLES:
        raise ValueError(f"Unknown model role: {role!r} (expected one of {_MODEL_ROLES})")
    s = get_settings()
    if role == "render":
        return {
            "model": s.render_model,
            "provider": s.render_provider,
            "base_url": s.render_host.rstrip("/"),
            "api_key": s.render_api_key
        }
    model = {
        "vision": s.vision_model,
        "chat": s.chat_model,
        "worker": s.worker_model if s.enable_model_tiering else s.author_model,
        "author": s.author_model,
        "embed": s.embed_model,
    }[role]
    if role == "vision":
        base_url = s.vision_ollama_host or s.ollama_host
    elif role in ("chat", "worker", "author"):
        base_url = s.chat_ollama_host or s.ollama_host
    else:
        base_url = s.ollama_host
    return {"model": model, "base_url": base_url.rstrip("/")}
