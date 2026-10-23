"""
Model Registry for Expo Design AI (Phase 0).

Configuration-driven model management. Defines model roles, provider abstraction,
and routing logic. Wraps existing local_chat.py and local_embed.py as default
providers — no breaking changes to existing code.

Model roles:
    FAST_LLM, REASONING_LLM, VISION_MODEL, OCR_MODEL,
    LAYOUT_MODEL, EMBEDDING_MODEL, RERANKER_MODEL, CODING_MODEL
"""
import os
import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Iterator, Dict, Any

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


# ── Model roles ─────────────────────────────────────────────
class ModelRole:
    FAST_LLM = "FAST_LLM"
    REASONING_LLM = "REASONING_LLM"
    VISION_MODEL = "VISION_MODEL"
    OCR_MODEL = "OCR_MODEL"
    LAYOUT_MODEL = "LAYOUT_MODEL"
    EMBEDDING_MODEL = "EMBEDDING_MODEL"
    RERANKER_MODEL = "RERANKER_MODEL"
    CODING_MODEL = "CODING_MODEL"


# ── Model configuration ─────────────────────────────────────
@dataclass
class ModelConfig:
    role: str
    name: str
    provider: str = "ollama"
    endpoint: str = "http://127.0.0.1:11434"
    version: str = "latest"
    quantization: str = ""
    context_length: int = 32768
    capabilities: List[str] = field(default_factory=list)
    gpu_requirements: Dict[str, Any] = field(default_factory=dict)
    cpu_capable: bool = True
    expected_latency_ms: int = 500
    enabled: bool = True
    status: str = "active"
    priority: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)
    modalities: List[str] = field(default_factory=lambda: ["text"])
    license: str = ""
    sha256: str = ""
    is_local: bool = True
    fallback_roles: List[str] = field(default_factory=list)


# ── Provider abstraction ────────────────────────────────────
class ModelProvider(ABC):
    """Abstract base class for AI model providers."""

    @abstractmethod
    def chat(self, messages: List[dict], **kwargs) -> str:
        ...

    @abstractmethod
    def stream(self, messages: List[dict], **kwargs) -> Iterator[str]:
        ...

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        ...

    @abstractmethod
    def vision(self, image_path: str, prompt: str) -> str:
        ...

    @abstractmethod
    def health(self) -> Tuple[bool, dict]:
        ...


# ── Ollama provider (wraps existing clients) ───────────────
class OllamaProvider(ModelProvider):
    """Ollama model provider — wraps local_chat and local_embed."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self._chat_client = None
        self._embed_client = None

    def _get_chat_client(self):
        if self._chat_client is None:
            import local_chat
            self._chat_client = local_chat.LocalChatOllama(
                model=self.config.name,
                temperature=0.1,
                num_ctx=self.config.context_length,
                keep_alive="5m",
                url=self.config.endpoint,
            )
        return self._chat_client

    def _get_embed_client(self):
        if self._embed_client is None:
            import local_embed
            self._embed_client = local_embed.LocalOllamaEmbeddings(
                model=self.config.name,
            )
        return self._embed_client

    def chat(self, messages: List[dict], **kwargs) -> str:
        client = self._get_chat_client()
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        types = {'user':HumanMessage, 'system':SystemMessage, 'assistant':AIMessage}
        typed = [types.get(m.get('role'),HumanMessage)(content=m.get('content','')) if isinstance(m,dict) else m for m in messages]
        return ''.join(chunk.content for chunk in client.stream(typed))

    def stream(self, messages: List[dict], **kwargs) -> Iterator[str]:
        client = self._get_chat_client()
        for chunk in client.stream(messages):
            yield chunk

    def embed(self, texts: List[str]) -> List[List[float]]:
        client = self._get_embed_client()
        return client.embed_documents(texts)

    def vision(self, image_path: str, prompt: str) -> str:
        import vision
        return vision.describe_image(image_path, instruction=prompt)

    def health(self) -> Tuple[bool, dict]:
        import httpx
        try:
            r = httpx.get(self.config.endpoint + "/api/tags", timeout=10)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            exact = self.config.name if ':' in self.config.name else self.config.name + ':latest'
            ok = exact in names
            return ok, {"model": self.config.name, "installed": ok, "available": names}
        except Exception as e:
            return False, {"model": self.config.name, "error": str(e)}


class PaddleOCRProvider(ModelProvider):
    """PaddleOCR model provider for high-speed local OCR and table extraction."""

    def __init__(self, config: ModelConfig):
        self.config = config

    def chat(self, messages: List[dict], **kwargs) -> str:
        raise NotImplementedError("PaddleOCR does not support chat")

    def stream(self, messages: List[dict], **kwargs) -> Iterator[str]:
        raise NotImplementedError("PaddleOCR does not support chat streaming")

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("PaddleOCR does not support embedding")

    def vision(self, image_path: str, prompt: str = "") -> str:
        from services.vision_adapter import PaddleOCRExtractor
        res = PaddleOCRExtractor().extract(image_path)
        return res.get("raw_text", "")

    def health(self) -> Tuple[bool, dict]:
        try:
            import paddleocr
            return True, {"model": self.config.name, "installed": True, "backend": "paddleocr"}
        except Exception as e:
            return False, {"model": self.config.name, "error": str(e)}


# ── Model Registry ──────────────────────────────────────────
class ModelRegistry:
    """
    Central registry for all AI models. Configuration-driven, not hardcoded.
    Supports multiple providers, model roles, and routing.
    """

    def __init__(self):
        self._models: Dict[str, ModelConfig] = {}
        self._providers: Dict[str, ModelProvider] = {}
        self._lock = threading.Lock()
        self._load_defaults()

    def _load_defaults(self):
        """Load default model configurations.

        Pilot architecture blueprint Sec 6.1: sourced from config.resolve_role
        wherever a role exists there, instead of this registry's own,
        previously-independent OLLAMA_HOST/EXPO_VISION_MODEL/EXPO_EMBED_MODEL
        env-var reads -- those had drifted from what the live app actually
        uses (this registry is diagnostic-only: /models and one /health
        endpoint, never the live chat/ingestion path) and would silently
        report the wrong model/endpoint once vision and chat are split
        across two Ollama processes (Sec 6.2). FAST_LLM and RERANKER_MODEL
        have no equivalent role in resolve_role, so they keep reading their
        own env vars.
        """
        try:
            from config import resolve_role
            chat_role = resolve_role("chat")
            vision_role = resolve_role("vision")
            embed_role = resolve_role("embed")
        except Exception:
            # Fall back to the old independent defaults if config isn't
            # importable for some reason (e.g. this module used standalone).
            _host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
            chat_role = {"model": os.getenv("EXPO_CHAT_MODEL", "qwen3.5:9b"), "base_url": _host}
            vision_role = {"model": os.getenv("EXPO_VISION_MODEL", "paddleocr"), "base_url": _host}
            embed_role = {"model": os.getenv("EXPO_EMBED_MODEL", "bge-m3"), "base_url": _host}
        ollama_host = chat_role["base_url"]

        # Reasoning / chat model -- the actual answer-synthesis model (Sec 6.1
        # 'chat' role), not vision_model: this used to report vision_model
        # here even though main.py's real /ask_stream path uses settings.chat_model
        # directly, which was exactly the documentation/reality drift flagged
        # in the offline/model-swap audit.
        self.register(ModelConfig(
            role=ModelRole.REASONING_LLM,
            name=chat_role["model"],
            provider="ollama",
            endpoint=chat_role["base_url"],
            context_length=int(os.getenv("EXPO_NUM_CTX", "16384")),
            capabilities=["chat", "reasoning", "structured_outputs"],
            modalities=["text"],
            priority=1,
            is_local=True,
            fallback_roles=[ModelRole.FAST_LLM],
        ))

        # Vision model -- paddleocr for fast accurate extraction, or vision model
        is_paddle = vision_role["model"] == "paddleocr"
        self.register(ModelConfig(
            role=ModelRole.VISION_MODEL,
            name=vision_role["model"],
            provider="paddleocr" if is_paddle else "ollama",
            endpoint="local" if is_paddle else vision_role["base_url"],
            context_length=int(os.getenv("EXPO_NUM_CTX", "16384")),
            capabilities=["vision", "ocr"],
            modalities=["text", "image"],
            priority=1,
            is_local=True,
            fallback_roles=[ModelRole.REASONING_LLM],
        ))

        # OCR Model
        self.register(ModelConfig(
            role=ModelRole.OCR_MODEL,
            name="paddleocr",
            provider="paddleocr",
            endpoint="local",
            capabilities=["ocr"],
            modalities=["image"],
            priority=1,
            is_local=True,
        ))

        # Embedding model
        self.register(ModelConfig(
            role=ModelRole.EMBEDDING_MODEL,
            name=embed_role["model"],
            provider="ollama",
            endpoint=embed_role["base_url"],
            capabilities=["embedding"],
            modalities=["text"],
            priority=1,
            is_local=True,
        ))

        # Fast LLM (lighter model for simple queries) -- no resolve_role role for
        # this yet, keeps reading its own env var.
        self.register(ModelConfig(
            role=ModelRole.FAST_LLM,
            name=os.getenv("EXPO_FAST_LLM", "qwen2.5:7b"),
            provider="ollama",
            endpoint=ollama_host,
            context_length=8192,
            capabilities=["chat"],
            modalities=["text"],
            priority=2,
            is_local=True,
            enabled=os.getenv("EXPO_FAST_LLM_ENABLED", "0") == "1",
        ))

        # Reranker -- not an Ollama model at all (sentence-transformers,
        # intelligence/reranker.py); no resolve_role role for this either.
        self.register(ModelConfig(
            role=ModelRole.RERANKER_MODEL,
            name=os.getenv("EXPO_RERANKER_MODEL", "bge-reranker-v2-m3"),
            provider="ollama",
            endpoint=ollama_host,
            capabilities=["reranking"],
            modalities=["text"],
            priority=2,
            is_local=True,
            enabled=os.getenv("EXPO_RERANKER_ENABLED", "0") == "1",
        ))

    def register(self, config: ModelConfig):
        """Register a model configuration."""
        with self._lock:
            self._models[config.role] = config
            self._providers[config.role] = self._create_provider(config)
        logger.info("Registered model: role={} name={} provider={}",
                    config.role, config.name, config.provider)

    def _create_provider(self, config: ModelConfig) -> ModelProvider:
        """Create a provider instance for a model config."""
        if config.provider == "ollama":
            return OllamaProvider(config)
        elif config.provider == "paddleocr":
            return PaddleOCRProvider(config)
        raise ValueError(f"Unknown provider: {config.provider}")

    def get(self, role: str) -> Optional[ModelConfig]:
        """Get model configuration by role."""
        return self._models.get(role)

    def get_provider(self, role: str) -> Optional[ModelProvider]:
        """Get provider instance by role."""
        return self._providers.get(role)

    def list_models(self) -> List[dict]:
        """List all registered models."""
        return [
            {
                "role": m.role,
                "name": m.name,
                "provider": m.provider,
                "endpoint": m.endpoint,
                "enabled": m.enabled,
                "status": m.status,
                "capabilities": m.capabilities,
                "context_length": m.context_length,
                "modalities": m.modalities,
                "is_local": m.is_local,
                "fallback_roles": m.fallback_roles,
            }
            for m in self._models.values()
        ]

    def health_check(self) -> dict:
        """Check health of all enabled models."""
        results = {}
        for role, config in self._models.items():
            if not config.enabled:
                results[role] = {"status": "disabled"}
                continue
            provider = self._providers.get(role)
            if provider:
                try:
                    ok, detail = provider.health()
                    results[role] = {"status": "healthy" if ok else "unhealthy", **detail}
                except Exception as e:
                    results[role] = {"status": "error", "error": str(e)}
            else:
                results[role] = {"status": "no_provider"}
        return results

    def route(self, task_type: str, complexity: str = "medium",
              requires_vision: bool = False,
              latency_requirement: str = "normal") -> Optional[ModelConfig]:
        """
        Select best model based on task requirements.

        Args:
            task_type: Type of task (chat, embedding, vision, reranking)
            complexity: low, medium, high
            requires_vision: Whether the task requires vision capability
            latency_requirement: fast, normal, relaxed

        Returns:
            Best matching ModelConfig or None
        """
        candidates = []
        for role, config in self._models.items():
            if not config.enabled:
                continue
            if requires_vision and "vision" not in config.capabilities:
                continue
            if task_type == "embedding" and "embedding" not in config.capabilities:
                continue
            if task_type == "reranking" and "reranking" not in config.capabilities:
                continue
            if task_type == "chat" and "chat" not in config.capabilities:
                continue
            candidates.append(config)

        if not candidates:
            return None

        # Sort by priority (lower is better)
        candidates.sort(key=lambda c: c.priority)

        # For fast latency, prefer FAST_LLM if available
        if latency_requirement == "fast":
            for c in candidates:
                if c.role == ModelRole.FAST_LLM:
                    return c

        # For high complexity, prefer REASONING_LLM
        if complexity == "high":
            for c in candidates:
                if c.role == ModelRole.REASONING_LLM:
                    return c

        return candidates[0]


# ── Singleton instance ──────────────────────────────────────
_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    """Get the global model registry instance."""
    return _registry
