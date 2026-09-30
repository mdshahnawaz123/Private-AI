"""
Centralized configuration for Expo Design AI (Phase 0).

Uses pydantic-settings for environment-based configuration.
All paths relative to EXPO_DATA_DIR. No hardcoded machine-specific paths.
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    host: str = "127.0.0.1"
    port: int = 8090
    cors_origins: List[str] = []

    # Database
    database_url: str = ""

    # Data directory
    data_dir: str = "data"

    # Auth
    secret: str = ""
    token_ttl_hours: int = 12
    admin_password: str = "admin"

    # AI models
    vision_model: str = "qwen2.5vl:32b"
    embed_model: str = "bge-m3"
    fast_llm: str = "qwen2.5:7b"
    fast_llm_enabled: bool = False
    reranker_model: str = "bge-reranker-v2-m3"
    reranker_enabled: bool = False

    # Wave 1: Model tiering
    worker_model: str = "qwen3:4b"
    author_model: str = "qwen2.5vl:32b"
    enable_model_tiering: bool = False
    rerank_candidates: int = 20
    rerank_keep: int = 5
    enable_query_expansion: bool = False  # Wave 1.5: expand short/coded queries via worker model
    enable_metadata_prefilter: bool = False  # Wave 1.5: pre-filter candidates by metadata before ranking

    # Phase 2: Structured data
    enable_structured_tables: bool = False  # Phase 2: extract tables/schedules as structured rows
    enable_quantities_store: bool = False  # Phase 2: capture numeric quantities as structured data
    enable_self_check: bool = False  # Phase 2: worker model self-check for answer verification
    not_found_threshold: float = 0.0  # Phase 2 FIX: 0.3 was miscalibrated for bge-reranker-v2-m3 (relevant chunks score ~0.01-0.06), which silently discarded valid retrievals. 0.0 disables the score-gate; honest "not found" is still handled by the answer prompt. Recalibrate later with eval data.

    # Ollama
    ollama_host: str = "http://127.0.0.1:11434"
    keep_alive: str = "5m"
    vision_retries: int = 3
    embed_retries: int = 5
    embed_timeout: int = 120
    embed_batch: int = 48
    num_ctx: int = 16384
    chat_retries: int = 3

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
    max_upload_size_mb: int = 500

    # Logging
    log_level: str = "INFO"
    log_rotation: str = "10 MB"
    log_retention: str = "60 days"

    class Config:
        env_prefix = "EXPO_"
        env_file = ".env"
        env_file_encoding = "utf-8"

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
