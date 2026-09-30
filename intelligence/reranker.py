"""
Reranker for Expo Design AI (Wave 1.5, Task A).

In-process cross-encoder reranking using sentence-transformers.
Model: BAAI/bge-reranker-v2-m3 (CPU-only to protect VRAM for AutoCAD/D5).

Setup (one-time, requires internet):
    python -m sentence_transformers.download BAAI/bge-reranker-v2-m3

After setup, runs fully offline.
"""
import os
from typing import List, Dict, Any, Optional

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class Reranker:
    """
    In-process cross-encoder reranker.
    Lazy-loads the model on first use (not at import).
    CPU-only to protect VRAM for AutoCAD/D5 Render.
    """

    def __init__(self):
        try:
            from config import get_settings as _gs
            _s = _gs()
            _cfg_model = getattr(_s, "reranker_model", "bge-reranker-v2-m3")
            _cfg_enabled = bool(getattr(_s, "reranker_enabled", False))
        except Exception:
            _cfg_model, _cfg_enabled = "bge-reranker-v2-m3", False
        # Use full BAAI/ prefix — CrossEncoder needs the exact repo ID
        _model = os.getenv("EXPO_RERANKER_MODEL", _cfg_model)
        if not _model.startswith("BAAI/"):
            _model = "BAAI/" + _model
        self._model_name = _model
        self._enabled = os.getenv("EXPO_RERANKER_ENABLED", "1" if _cfg_enabled else "0") == "1"
        self._model = None  # Lazy-loaded on first use
        self._load_attempted = False

    def is_enabled(self) -> bool:
        """Check if reranker is enabled."""
        return self._enabled

    def _load_model(self):
        """Lazy-load the cross-encoder model on first use. CPU-only."""
        if self._load_attempted:
            return self._model is not None
        self._load_attempted = True

        try:
            from sentence_transformers import CrossEncoder
            logger.info("Loading reranker model: {} (CPU)", self._model_name)
            self._model = CrossEncoder(self._model_name, device="cpu")
            logger.info("Reranker model loaded successfully")
            return True
        except Exception as e:
            logger.warning("Reranker model load failed (falling back to original order): {}", e)
            self._model = None
            return False

    def rerank(self, query: str, documents: List[Dict[str, Any]],
               top_k: int = 8) -> List[Dict[str, Any]]:
        """
        Rerank documents by relevance to query using in-process cross-encoder.
        Returns reordered documents with rerank_score added.
        """
        if not self._enabled:
            return documents[:top_k]

        if not documents:
            return []

        # Lazy-load model
        if not self._load_model():
            return documents[:top_k]

        try:
            # Prepare pairs for cross-encoder
            texts = [doc.get("content", "")[:500] for doc in documents]
            pairs = [(query, text) for text in texts]

            # Get relevance scores
            scores = self._model.predict(pairs)

            # Attach scores to documents
            scored_docs = []
            for i, doc in enumerate(documents):
                d = doc.copy()
                d["rerank_score"] = float(scores[i])
                scored_docs.append(d)

            # Sort by score (descending)
            scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

            logger.info("Reranked {} documents (top score: {:.4f})",
                        len(scored_docs), scored_docs[0]["rerank_score"] if scored_docs else 0)
            return scored_docs[:top_k]

        except Exception as e:
            logger.warning("Rerank failed (falling back to original order): {}", e)
            return documents[:top_k]

    def rerank_with_fallback(self, query: str, documents: List[Dict[str, Any]],
                              top_k: int = 8) -> List[Dict[str, Any]]:
        """Rerank with fallback to original order on any failure."""
        try:
            return self.rerank(query, documents, top_k)
        except Exception as e:
            logger.warning("Rerank failed: {}", e)
            return documents[:top_k]

    def self_test(self) -> bool:
        """
        Self-test: verify the reranker reorders correctly.
        Returns True if the right passage moves to the top.
        """
        if not self._enabled:
            logger.info("Reranker disabled — self-test skipped")
            return True

        if not self._load_model():
            logger.warning("Reranker model not available — self-test skipped")
            return False

        query = "What is the minimum door width?"
        documents = [
            {"content": "The building has 8 floors and a basement parking area."},
            {"content": "Minimum clear door width is 800mm per DBC requirements."},
            {"content": "The corridor width is 1200mm for egress."},
        ]

        try:
            results = self.rerank(query, documents, top_k=3)
            top_content = results[0].get("content", "")
            if "door width" in top_content.lower():
                logger.info("Self-test PASSED: correct passage ranked first")
                return True
            else:
                logger.warning("Self-test FAILED: expected door width passage first, got: {}", top_content[:50])
                return False
        except Exception as e:
            logger.warning("Self-test FAILED with exception: {}", e)
            return False


# Singleton instance
_reranker = Reranker()


def get_reranker() -> Reranker:
    """Get the global reranker instance."""
    return _reranker
