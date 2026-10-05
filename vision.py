"""
Local vision extraction via Ollama (Phase 3 - vision).

Engineering-review oriented: the model transcribes VERBATIM, marks anything
unclear as [illegible] (never guesses), and separately describes the drawing.
Runs fully locally against the Ollama server - no internet at runtime. httpx is
imported lazily so the pure helpers below can be unit-tested without it.
"""
import os
import base64

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
VISION_MODEL = os.getenv("EXPO_VISION_MODEL", "qwen2.5vl:7b")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")

# Keep the (large) model resident in Ollama between page calls so it does not
# unload and reload repeatedly -- reload thrash is a common cause of the runner
# briefly refusing connections. Overridable via env.
KEEP_ALIVE = os.getenv("EXPO_KEEP_ALIVE", "5m")
VISION_RETRIES = int(os.getenv("EXPO_VISION_RETRIES", "3"))

# Serialize heavy inferences: only ONE vision call runs at a time across the whole
# app, so concurrent uploads can never stack two 7B inferences and exhaust memory.
import threading
import time as _time
_VISION_LOCK = threading.Lock()

EXTRACTION_PROMPT = (
    "You are transcribing an engineering document image for a compliance review "
    "where every value must be correct.\n"
    "Return two clearly separated sections:\n\n"
    "1) VERBATIM TEXT - reproduce every label, number, dimension, unit, note and "
    "table cell EXACTLY as shown. Preserve units and symbols. For EVERY table, first "
    "write the table's title on its own line, then render the table as a GitHub-style "
    "Markdown pipe table: a header row of column names, a separator row, then one row "
    "per line with cells separated by | . Keep each value in the correct row and "
    "column; put a dash (-) for blank cells. If any character is unclear or unreadable, "
    "write [illegible] in its place - NEVER guess a value.\n\n"
    "2) DRAWING DESCRIPTION - describe the elements, layout, symbols and what the "
    "drawing depicts. Do NOT state any dimension or value that is not visibly "
    "written in the image.\n\n"
    "Do not summarise, omit, or invent anything."
)

def model_base(tag):
    return (tag or "").split(":")[0]

def is_image(path):
    return os.path.splitext(path or "")[-1].lower() in IMAGE_EXTS

def encode_image(path):
    with open(path, "rb") as f:
        data = f.read()
    # Downscale very large page renders; big images can make the local vision
    # server error out. Cap the longest side (default 1600px). No-op without PIL.
    try:
        import io as _io
        from PIL import Image as _Image
        _cap = int(os.getenv("EXPO_VISION_MAX_DIM", "1600"))
        _im = _Image.open(_io.BytesIO(data))
        _w, _h = _im.size
        _m = max(_w, _h)
        if _cap and _m > _cap:
            _sc = _cap / float(_m)
            _im = _im.convert("RGB").resize((max(1, int(_w * _sc)), max(1, int(_h * _sc))))
            _buf = _io.BytesIO(); _im.save(_buf, format="PNG"); data = _buf.getvalue()
    except Exception:
        pass
    return base64.b64encode(data).decode("ascii")

def build_payload(b64, instruction=None, model=None):
    return {
        "model": model or VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": instruction or EXTRACTION_PROMPT,
            "images": [b64],
        }],
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": 3072},   # deterministic, allow full table transcription
    }

def describe_image(path, instruction=None, model=None, timeout=600):
    """Send one image to the local vision model and return its extraction text.

    Serialized (one inference at a time) and retried with backoff so a transient
    refusal while the big model is loading does not fail the page."""
    import httpx
    payload = build_payload(encode_image(path), instruction, model)
    last_err = None
    with _VISION_LOCK:
        for attempt in range(max(1, VISION_RETRIES)):
            try:
                r = httpx.post(OLLAMA_URL + "/api/chat", json=payload, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                return ((data.get("message") or {}).get("content") or "").strip()
            except Exception as e:
                last_err = e
                try:
                    _detail = ""
                    _resp = getattr(e, "response", None)
                    if _resp is not None:
                        try: _detail = _resp.text[:800]
                        except Exception: _detail = ""
                    _lp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vision_error.log")
                    with open(_lp, "w", encoding="utf-8") as _lf:
                        _lf.write("attempt %d\n%r\n%s" % (attempt, e, _detail))
                except Exception:
                    pass
                if attempt < VISION_RETRIES - 1:
                    _time.sleep(min(2 ** attempt * 2, 20))  # 2s, 4s, 8s ... (max 20s)
    raise last_err

def health():
    """(ok, detail): is the configured vision model present in Ollama?"""
    import httpx
    try:
        r = httpx.get(OLLAMA_URL + "/api/tags", timeout=10)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        ok = any(model_base(n) == model_base(VISION_MODEL) for n in names)
        return ok, {"model": VISION_MODEL, "installed": ok, "available": names}
    except Exception as e:
        return False, {"model": VISION_MODEL, "error": str(e)}
