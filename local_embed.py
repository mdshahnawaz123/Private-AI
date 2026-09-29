"""Reliable local embeddings for Expo Design AI.

langchain_ollama's OllamaEmbeddings uses the ollama python client, which routes
through a model *runner* port and does not retry. On a cold model start that
first request can race the runner and fail with "connection refused"
(/tokenize on a dynamic port) -- exactly the intermittent indexing failure seen
in the field. A direct call to Ollama's stable /api/embeddings endpoint on the
main port works reliably, so we use that, with retry/backoff to ride out a cold
start. Drop-in replacement: implements embed_documents / embed_query.
"""
import os
import time

try:
    from langchain_core.embeddings import Embeddings as _Base
except Exception:  # keep importable even if langchain isn't present
    class _Base:  # type: ignore
        pass

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("EXPO_EMBED_MODEL", "bge-m3")
EMBED_RETRIES = int(os.getenv("EXPO_EMBED_RETRIES", "5"))
EMBED_TIMEOUT = int(os.getenv("EXPO_EMBED_TIMEOUT", "120"))


class LocalOllamaEmbeddings(_Base):
    def __init__(self, model=EMBED_MODEL, url=OLLAMA_URL, timeout=EMBED_TIMEOUT):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _embed_one(self, text):
        import httpx
        payload = {"model": self.model, "prompt": text if (text and text.strip()) else " "}
        last = None
        for attempt in range(max(1, EMBED_RETRIES)):
            try:
                r = httpx.post(self.url + "/api/embeddings", json=payload, timeout=self.timeout)
                r.raise_for_status()
                emb = (r.json() or {}).get("embedding")
                if not emb:
                    raise ValueError("empty embedding from Ollama")
                return emb
            except Exception as e:
                last = e
                if attempt < EMBED_RETRIES - 1:
                    time.sleep(min(2 ** attempt, 10))  # 1,2,4,8,10... ride out cold start
        raise last

    def _embed_batch(self, batch):
        """Embed a list of texts in ONE call via Ollama /api/embed (fast). Falls
        back to per-item /api/embeddings if the batch endpoint misbehaves."""
        import httpx
        inputs = [t if (t and t.strip()) else " " for t in batch]
        payload = {"model": self.model, "input": inputs}
        last = None
        for attempt in range(max(1, EMBED_RETRIES)):
            try:
                r = httpx.post(self.url + "/api/embed", json=payload, timeout=self.timeout)
                r.raise_for_status()
                embs = (r.json() or {}).get("embeddings")
                if embs and len(embs) == len(batch):
                    return embs
                raise ValueError("batch embed returned %s vectors for %s inputs"
                                 % (len(embs) if embs else 0, len(batch)))
            except Exception as e:
                last = e
                if attempt < EMBED_RETRIES - 1:
                    time.sleep(min(2 ** attempt, 8))
        # Fallback: per-item (older endpoint), still correct just slower.
        try:
            return [self._embed_one(t) for t in batch]
        except Exception:
            raise last

    def embed_documents(self, texts):
        if not texts:
            return []
        out = []
        B = max(1, int(os.getenv("EXPO_EMBED_BATCH", "48")))
        for i in range(0, len(texts), B):
            out.extend(self._embed_batch(texts[i:i + B]))
        return out

    def embed_query(self, text):
        return self._embed_one(text)
