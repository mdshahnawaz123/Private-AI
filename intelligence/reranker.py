"""
Reranker for Expo Design AI (Phase 3).

Cross-encoder reranking to refine retrieval results.
Uses bge-reranker-v2-m3 or similar model via Ollama.
"""
import os
from typing import List, Dict, Any, Optional, Tuple

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class Reranker:
    """
    Cross-encoder reranker for refining retrieval results.
    Falls back to original order if reranker is unavailable.
    """

    def __init__(self):
        self._model_name = os.getenv("EXPO_RERANKER_MODEL", "bge-reranker-v2-m3")
        self._enabled = os.getenv("EXPO_RERANKER_ENABLED", "0") == "1"
        self._endpoint = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    def is_enabled(self) -> bool:
        """Check if reranker is enabled."""
        return self._enabled

    def rerank(self, query: str, documents: List[Dict[str, Any]],
               top_k: int = 8) -> List[Dict[str, Any]]:
        """
        Rerank documents by relevance to query.
        Returns reordered documents with scores.
        """
        if not self._enabled:
            return documents[:top_k]

        if not documents:
            return []

        try:
            # Use Ollama's rerank endpoint if available
            import httpx
            texts = [doc.get("content", "")[:500] for doc in documents]  # Truncate for speed
            payload = {
                "model": self._model_name,
                "query": query,
                "documents": texts,
            }
            r = httpx.post(f"{self._endpoint}/api/rerank", json=payload, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])

            # Reorder documents based on reranker scores
            reranked = []
            for item in results:
                idx = item.get("index", 0)
                score = item.get("relevance_score", 0.0)
                if idx < len(documents):
                    doc = documents[idx].copy()
                    doc["rerank_score"] = score
                    reranked.append(doc)

            logger.info("Reranked {} documents", len(reranked))
            return reranked[:top_k]

        except Exception as e:
            logger.warning("Reranker failed (falling back to original order): {}", e)
            return documents[:top_k]

    def rerank_with_fallback(self, query: str, documents: List[Dict[str, Any]],
                              top_k: int = 8) -> List[Dict[str, Any]]:
        """Rerank with fallback to original order on any failure."""
        try:
            return self.rerank(query, documents, top_k)
        except Exception as e:
            logger.warning("Rerank failed: {}", e)
            return documents[:top_k]


# Singleton instance
_reranker = Reranker()


def get_reranker() -> Reranker:
    """Get the global reranker instance."""
    return _reranker
