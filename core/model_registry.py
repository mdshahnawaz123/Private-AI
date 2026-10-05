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
        result = client.chat(messages, **kwargs)
        return result

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
            model_base = self.config.name.split(":")[0]
            ok = any(n.split(":")[0] == model_base for n in names)
            return ok, {"model": self.config.name, "installed": ok, "available": names}
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
        """Load default model configurations from environment or defaults."""
        ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        vision_model = os.getenv("EXPO_VISION_MODEL", "qwen2.5vl:7b")
        embed_model = os.getenv("EXPO_EMBED_MODEL", "bge-m3")

        # Reasoning / chat model
        self.register(ModelConfig(
            role=ModelRole.REASONING_LLM,
            name=vision_model,
            provider="ollama",
            endpoint=ollama_host,
            context_length=int(os.getenv("EXPO_NUM_CTX", "16384")),
            capabilities=["chat", "vision", "reasoning"],
            priority=1,
        ))

        # Vision model (same as reasoning for now — one large model)
        self.register(ModelConfig(
            role=ModelRole.VISION_MODEL,
            name=vision_model,
            provider="ollama",
            endpoint=ollama_host,
            context_length=int(os.getenv("EXPO_NUM_CTX", "16384")),
            capabilities=["vision", "chat"],
            priority=1,
        ))

        # Embedding model
        self.register(ModelConfig(
            role=ModelRole.EMBEDDING_MODEL,
            name=embed_model,
            provider="ollama",
            endpoint=ollama_host,
            capabilities=["embedding"],
            priority=1,
        ))

        # Fast LLM (lighter model for simple queries)
        self.register(ModelConfig(
            role=ModelRole.FAST_LLM,
            name=os.getenv("EXPO_FAST_LLM", "qwen2.5:7b"),
            provider="ollama",
            endpoint=ollama_host,
            context_length=8192,
            capabilities=["chat"],
            priority=2,
            enabled=os.getenv("EXPO_FAST_LLM_ENABLED", "0") == "1",
        ))

        # Reranker
        self.register(ModelConfig(
            role=ModelRole.RERANKER_MODEL,
            name=os.getenv("EXPO_RERANKER_MODEL", "bge-reranker-v2-m3"),
            provider="ollama",
            endpoint=ollama_host,
            capabilities=["reranking"],
            priority=2,
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
