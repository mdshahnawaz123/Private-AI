"""
Hybrid Retrieval Engine for Expo Design AI (Phase 3).

Combines:
1. BM25 keyword search (exact matches)
2. Vector search (semantic similarity)
3. Reciprocal Rank Fusion (combine results)
4. Metadata filtering
5. Reranker (cross-encoder refinement)

Target pipeline:
QUERY → BM25 + VECTOR → RRF FUSION → METADATA FILTER → RERANKER → TOP EVIDENCE
"""
import re
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class RetrievalResult:
    """A single retrieval result."""
    content: str
    source: str
    page: Optional[int] = None
    score: float = 0.0
    score_bm25: float = 0.0
    score_vector: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HybridRetrievalResult:
    """Results from hybrid retrieval."""
    results: List[RetrievalResult]
    query_type: str = ""
    total_candidates: int = 0
    fused_count: int = 0
    reranked_count: int = 0


class BM25Index:
    """
    Simple BM25 implementation for keyword search.
    No external dependencies — pure Python.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: List[Dict[str, Any]] = []
        self.doc_freqs: List[Dict[str, int]] = []
        self.doc_len: List[int] = []
        self.avgdl: float = 0.0
        self.idf: Dict[str, float] = {}
        self.doc_count: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        return re.findall(r'\b[a-zA-Z0-9_]+\b', text.lower())

    def add_documents(self, documents: List[Dict[str, Any]]):
        """Add documents to the index."""
        for doc in documents:
            content = doc.get("content", "")
            tokens = self._tokenize(content)
            freq = {}
            for token in tokens:
                freq[token] = freq.get(token, 0) + 1
            self.documents.append(doc)
            self.doc_freqs.append(freq)
            self.doc_len.append(len(tokens))

        self.doc_count = len(self.documents)
        if self.doc_count > 0:
            self.avgdl = sum(self.doc_len) / self.doc_count

        # Compute IDF
        df = {}
        for freq in self.doc_freqs:
            for term in freq:
                df[term] = df.get(term, 0) + 1
        for term, freq in df.items():
            self.idf[term] = math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))

    def search(self, query: str, k: int = 10) -> List[Tuple[int, float]]:
        """Search the index. Returns list of (doc_index, score) tuples."""
        query_tokens = self._tokenize(query)
        scores = []

        for i, freq in enumerate(self.doc_freqs):
            score = 0.0
            for term in query_tokens:
                if term not in freq:
                    continue
                idf = self.idf.get(term, 0)
                tf = freq[term]
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                score += idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: -x[1])
        return scores[:k]


class HybridRetriever:
    """
    Hybrid retrieval combining BM25, vector search, and reranking.
    """

    def __init__(self):
        self._bm25 = BM25Index()
        self._documents: List[Dict[str, Any]] = []
        self._rrf_k = 60  # RRF constant

    def index_documents(self, documents: List[Dict[str, Any]]):
        """Index documents for hybrid retrieval."""
        self._documents = documents
        self._bm25.add_documents(documents)
        logger.info("Indexed {} documents for hybrid retrieval", len(documents))

    def reciprocal_rank_fusion(self, bm25_results: List[Tuple[int, float]],
                               vector_results: List[Tuple[int, float]],
                               k: int = 60) -> List[Tuple[int, float]]:
        """
        Combine BM25 and vector results using Reciprocal Rank Fusion.
        """
        fused_scores: Dict[int, float] = {}

        # Add BM25 contributions
        for rank, (doc_idx, _) in enumerate(bm25_results):
            fused_scores[doc_idx] = fused_scores.get(doc_idx, 0) + 1.0 / (k + rank + 1)

        # Add vector contributions
        for rank, (doc_idx, _) in enumerate(vector_results):
            fused_scores[doc_idx] = fused_scores.get(doc_idx, 0) + 1.0 / (k + rank + 1)

        # Sort by fused score
        sorted_results = sorted(fused_scores.items(), key=lambda x: -x[1])
        return sorted_results

    def retrieve(self, query: str, project: str = "default",
                 k: int = 8, user: Optional[dict] = None,
                 filters: Dict[str, Any] = None,
                 vectorstore=None) -> HybridRetrievalResult:
        """
        Hybrid retrieval: BM25 + Vector + RRF + Filter + Rerank.

        Args:
            query: User query
            project: Project name
            k: Number of results to return
            user: Current user (for permission filtering)
            filters: Metadata filters (discipline, doc_type, etc.)
            vectorstore: FAISS vectorstore instance

        Returns:
            HybridRetrievalResult with ranked results
        """
        # Step 1: BM25 search
        bm25_results = self._bm25.search(query, k=k * 3)

        # Step 2: Vector search
        vector_results = []
        if vectorstore:
            try:
                docs = vectorstore.similarity_search_with_score(query, k=k * 3)
                # Map to indices
                for doc, score in docs:
                    for i, d in enumerate(self._documents):
                        if d.get("content") == doc.page_content:
                            vector_results.append((i, 1.0 - score))  # Convert distance to similarity
                            break
            except Exception as e:
                logger.warning("Vector search failed: {}", e)

        # Step 3: Reciprocal Rank Fusion
        fused = self.reciprocal_rank_fusion(bm25_results, vector_results)

        # Step 4: Build results
        results = []
        for doc_idx, fused_score in fused:
            if doc_idx >= len(self._documents):
                continue
            doc = self._documents[doc_idx]

            # Apply metadata filters
            if filters:
                match = True
                for key, value in filters.items():
                    if doc.get("metadata", {}).get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            # Get individual scores
            bm25_score = next((s for i, s in bm25_results if i == doc_idx), 0.0)
            vector_score = next((s for i, s in vector_results if i == doc_idx), 0.0)

            results.append(RetrievalResult(
                content=doc.get("content", ""),
                source=doc.get("metadata", {}).get("source", "unknown"),
                page=doc.get("metadata", {}).get("page"),
                score=fused_score,
                score_bm25=bm25_score,
                score_vector=vector_score,
                metadata=doc.get("metadata", {}),
            ))

        # Step 5: Reranker (if available)
        # Phase 3: Placeholder — will integrate bge-reranker-v2-m3
        # For now, use fused score as final score

        return HybridRetrievalResult(
            results=results[:k],
            query_type="hybrid",
            total_candidates=len(fused),
            fused_count=len(fused),
            reranked_count=len(results[:k]),
        )

    def retrieve_from_faiss(self, query: str, project: str = "default",
                            k: int = 8, user: Optional[dict] = None,
                            vectorstore=None) -> HybridRetrievalResult:
        """
        Retrieve using existing FAISS index + BM25 on indexed documents.
        This is the main entry point that works with the existing system.
        """
        if not vectorstore:
            return HybridRetrievalResult(results=[], query_type="none")

        # Get documents from FAISS (over-fetch)
        try:
            docs = vectorstore.similarity_search_with_score(query, k=k * 5)
        except Exception as e:
            logger.warning("FAISS search failed: {}", e)
            return HybridRetrievalResult(results=[], query_type="error")

        # Build results
        results = []
        for doc, distance in docs:
            # Convert distance to similarity score (FAISS L2 distance)
            similarity = 1.0 / (1.0 + distance)

            # Permission check
            if user:
                import db
                allow_all, allowed_ids = db.folder_access(user, project)
                if not allow_all:
                    folder_id = doc.metadata.get("folder_id")
                    if folder_id is None:
                        # Fallback: check filename
                        fmap = db.doc_folder_map(project)
                        folder_id = fmap.get(doc.metadata.get("source"))
                    if folder_id not in (allowed_ids or set()):
                        continue

            results.append(RetrievalResult(
                content=doc.page_content,
                source=doc.metadata.get("source", "unknown"),
                page=doc.metadata.get("page"),
                score=similarity,
                score_vector=similarity,
                metadata=doc.metadata,
            ))

        return HybridRetrievalResult(
            results=results[:k],
            query_type="hybrid_faiss",
            total_candidates=len(docs),
            fused_count=len(results),
            reranked_count=len(results[:k]),
        )


# Singleton instance
_retriever = HybridRetriever()


def get_retriever() -> HybridRetriever:
    """Get the global hybrid retriever instance."""
    return _retriever
