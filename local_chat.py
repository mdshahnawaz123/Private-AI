"""Reliable local chat streaming for Expo Design AI.

Talks to Ollama's /api/chat directly (the call vision.py already uses well),
instead of langchain_ollama's ChatOllama. Key robustness:
  * bigger context window (num_ctx) so a report's retrieved context fits,
  * retry on a COLD START: Ollama can answer a first request with an empty
    model-load acknowledgment (done, zero content); we detect zero output and
    retry so the answer is not silently lost,
  * diagnostic logging of every attempt (prompt size, tokens out, done_reason),
  * a .stream(msgs) shaped like ChatOllama's (yields objects with .content),
    so the existing streaming loop in main.py is unchanged.
"""
import os
import json
import time

try:
    from loguru import logger
except Exception:  # logging is best-effort
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
NUM_CTX = int(os.getenv("EXPO_NUM_CTX", "16384"))
CHAT_RETRIES = int(os.getenv("EXPO_CHAT_RETRIES", "3"))
KEEP_ALIVE = os.getenv("EXPO_KEEP_ALIVE", "5m")


class _Chunk:
    __slots__ = ("content",)
    def __init__(self, content):
        self.content = content


def _role(m):
    t = getattr(m, "type", None)
    if t == "human":
        return "user"
    if t == "ai":
        return "assistant"
    if t == "system":
        return "system"
    cn = m.__class__.__name__.lower()
    if "human" in cn:
        return "user"
    if "ai" in cn:
        return "assistant"
    return "system"


def to_ollama_messages(msgs):
    out = []
    for m in msgs:
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(str(p) for p in content)
        out.append({"role": _role(m), "content": content or ""})
    return out


class LocalChatOllama:
    def __init__(self, model, temperature=0.1, num_ctx=NUM_CTX, num_predict=8192,
                 keep_alive=KEEP_ALIVE, fmt=None, url=OLLAMA_URL, timeout=900):
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.keep_alive = keep_alive
        self.fmt = fmt
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _payload(self, ol_msgs):
        p = {
            "model": self.model,
            "messages": ol_msgs,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        if self.fmt:
            p["format"] = self.fmt
        return p

    def stream(self, msgs):
        import httpx
        ol_msgs = to_ollama_messages(msgs)
        _is_q3 = "qwen3" in (self.model or "").lower()
        if _is_q3:
            # qwen3 is a hybrid reasoning model; "/no_think" keeps answers fast and clean
            for _m in reversed(ol_msgs):
                if _m.get("role") == "user" and "/no_think" not in (_m.get("content") or ""):
                    _m["content"] = (_m.get("content") or "") + " /no_think"
                    break
        payload = self._payload(ol_msgs)
        prompt_chars = sum(len(m["content"]) for m in ol_msgs)

        for attempt in range(max(1, CHAT_RETRIES)):
            got = 0
            out_chars = 0
            done_reason = None
            _buf = ""
            try:
                with httpx.stream("POST", self.url + "/api/chat", json=payload,
                                  timeout=self.timeout) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if obj.get("error"):
                            raise RuntimeError(str(obj.get("error")))
                        tok = (obj.get("message") or {}).get("content") or ""
                        if tok:
                            if _is_q3:
                                _buf += tok
                                while "<think>" in _buf and "</think>" in _buf:
                                    _buf = _buf[:_buf.index("<think>")] + _buf[_buf.index("</think>") + len("</think>"):]
                                if "<think>" in _buf:
                                    _emit = _buf[:_buf.index("<think>")]; _buf = _buf[_buf.index("<think>"):]
                                else:
                                    _emit = _buf; _buf = ""
                                if _emit:
                                    got += 1; out_chars += len(_emit); yield _Chunk(_emit)
                            else:
                                got += 1
                                out_chars += len(tok)
                                yield _Chunk(tok)
                        if obj.get("done"):
                            done_reason = obj.get("done_reason")
                            if _is_q3 and _buf and "<think>" not in _buf:
                                got += 1; out_chars += len(_buf); yield _Chunk(_buf); _buf = ""
                            break
                logger.info("chat attempt {}/{}: model={} promptChars={} tokens={} outChars={} done_reason={}",
                            attempt + 1, CHAT_RETRIES, self.model, prompt_chars, got, out_chars, done_reason)
                if got > 0:
                    return
                # Zero content but a clean finish -> almost always a cold model-load
                # acknowledgment. Retry (model is warm now) instead of losing the answer.
                if attempt < CHAT_RETRIES - 1:
                    time.sleep(2)
                    continue
                logger.warning("chat produced no tokens after {} attempts (done_reason={})",
                               CHAT_RETRIES, done_reason)
                return
            except Exception as e:
                logger.exception("chat attempt {}/{} failed: {}", attempt + 1, CHAT_RETRIES, e)
                if got > 0 or attempt >= CHAT_RETRIES - 1:
                    raise
                time.sleep(min(2 ** attempt * 2, 12))
        return


# ── Wave 1: Model Tiering ───────────────────────────────────

def _get_model_config():
    """Get model configuration from settings."""
    try:
        from config import get_settings
        s = get_settings()
        return {
            "worker_model": s.worker_model,
            "author_model": s.author_model,
            "enable_model_tiering": s.enable_model_tiering,
        }
    except Exception:
        return {
            "worker_model": "qwen3:4b",
            "author_model": "qwen2.5vl:32b",
            "enable_model_tiering": False,
        }


def chat_worker(msgs, **kwargs):
    """
    Worker model call — uses worker model when tiering enabled,
    falls back to author model when disabled (preserves current behavior).

    Worker handles: intent classification, query expansion, retrieval judging,
    reranking, self-check.
    """
    cfg = _get_model_config()
    model = cfg["worker_model"] if cfg["enable_model_tiering"] else cfg["author_model"]
    role = "worker" if cfg["enable_model_tiering"] else "author"

    logger.info("MODEL_ROLE={} MODEL_NAME={}", role, model)

    llm = LocalChatOllama(model=model, **kwargs)
    return llm.stream(msgs)


def chat_author(msgs, **kwargs):
    """
    Author model call — always uses the author model.

    Author handles: final answer synthesis, difficult vision,
    drawing interpretation, final engineering explanation.
    """
    cfg = _get_model_config()
    model = cfg["author_model"]

    logger.info("MODEL_ROLE=author MODEL_NAME={}", model)

    llm = LocalChatOllama(model=model, **kwargs)
    return llm.stream(msgs)


# ── Wave 1/2: non-streaming worker helper (first real consumer of the worker model) ──

def _msg(role, content):
    return type("_M", (), {"type": role, "content": content})()


def worker_complete(system, user=None, num_predict=192, temperature=0.0, timeout=120):
    """Collect a short worker-model completion into a string.
    Uses the worker model when tiering is enabled, else the author model
    (via chat_worker). Returns '' on ANY failure so callers degrade gracefully."""
    try:
        # Accept worker_complete(prompt) as well as worker_complete(system, user):
        # with one argument, treat it as the user message.
        if user is None:
            user, system = system, "You are a precise construction-review assistant."
        msgs = [_msg("system", system), _msg("human", user)]
        out = []
        for chunk in chat_worker(msgs, temperature=temperature,
                                 num_predict=num_predict, timeout=timeout):
            c = getattr(chunk, "content", "")
            if c:
                out.append(c)
        return "".join(out).strip()
    except Exception:
        return ""
