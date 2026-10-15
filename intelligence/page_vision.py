"""Look at the page itself when the text pipeline can't answer (2026-10-14).

Closer to how a person (or Claude) reads a PDF: retrieval finds the most
relevant page(s); if the text-based answer was withheld, came back "not
found", or the question is about a figure/drawing/map, the rendered page IMAGE
is shown to the local vision model with the question. Its answer is published
clearly labelled as read from the page image (not text-verified) with the page
citation, never silently mixed with text-verified answers.
"""
import os
import re

FIGURE_Q = re.compile(r"\b(figure|fig\.?|diagram|map|drawing|image|photo(?:graph)?|chart|graph|plot|legend|colou?r(?:ed)?|shown in (?:blue|green|red))\b", re.I)
WEAK_ANSWER = re.compile(
    r"^\W*(?:I could not (?:verify|find)|I (?:can ?not|did not) find|The cited evidence is ambiguous|"
    r"(?:Based on the provided documents, )?I could not|"
    r"The (?:provided |uploaded |available )?(?:document(?:s)?(?: context)?|context|evidence|excerpts?)[^.]{0,80}?"
    r"(?:does not|do not|doesn't|don't) (?:contain|include|specify|state|show))", re.I)
NOT_ON_PAGE = "NOT_ON_PAGE"


def needs_page_vision(question, answer, withheld):
    return bool(withheld or WEAK_ANSWER.match(answer or "") or FIGURE_Q.search(question or ""))


def _explicit_pages(meta_pages, question):
    """Pages whose text carries the caption the question names ("Figure 2", "Table 11")."""
    out = []
    for kind, num in re.findall(r"\b(Figure|Fig\.?|Table)\s*(\d+)\b", question or "", re.I):
        label = "Figure" if kind.lower().startswith("fig") else "Table"
        pat = re.compile(r"\b" + label + r"\s*" + num + r"\b(?!\s*[-–]?\s*\d)", re.I)
        for p in meta_pages:
            text = " ".join(str(p.get(k) or "") for k in ("text", "vision"))
            ocr = (p.get("ocr") or {}).get("text") if isinstance(p.get("ocr"), dict) else ""
            if pat.search(text) or pat.search(ocr or ""):
                out.append(p["page"])
    return out


def candidate_pages(pdf_path, srcs, question, limit=2):
    import json
    pages = []
    try:
        with open(pdf_path + ".index.json", encoding="utf-8") as handle:
            pages = _explicit_pages(json.load(handle).get("pages", []), question)
    except Exception:
        pass
    name = os.path.basename(pdf_path)
    for s in srcs or []:
        if isinstance(s, dict) and str(s.get("source") or s.get("filename") or "").endswith(name):
            try:
                pages.append(int(s.get("page")))
            except (TypeError, ValueError):
                pass
    seen, ordered = set(), []
    for p in pages:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered[:limit]


def render_page(pdf_path, page_number, max_side=1600):
    import fitz
    from services.pdf_text_quality import page_text_rotation
    out_dir = pdf_path + "_qa_pages"
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"p{page_number}.png")
    if os.path.isfile(out):
        return out
    with fitz.open(pdf_path) as doc:
        page = doc[page_number - 1]
        zoom = max_side / max(page.rect.width, page.rect.height)
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(page_text_rotation(page)),
                        alpha=False).save(out)
    return out


def page_vision_model():
    """Model for page-image answering. EXPO_PAGE_VISION_MODEL lets you try a
    different (e.g. bigger) vision model for Q&A without changing the model
    used during document ingestion; defaults to the ingestion vision model."""
    import vision
    return os.getenv("EXPO_PAGE_VISION_MODEL") or vision.VISION_MODEL


def _ask_vision(image, prompt, timeout):
    import httpx
    import vision
    model = page_vision_model()
    payload = vision.build_payload(vision.encode_image(image), prompt, model)
    if "qwen3" in model.lower():
        payload["think"] = False  # hybrid reasoning models: answer directly
    r = httpx.post(vision.VISION_OLLAMA_URL + "/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "")


def answer_from_pages(question, pdf_path, pages, timeout=180):
    """Return (page, answer) from the first page image that answers, else (None, None)."""
    for page in pages:
        try:
            image = render_page(pdf_path, page)
            prompt = (
                f"This image is page {page} of an engineering document. Answer the question using ONLY what "
                "is visible on this page: printed text, tables, figures, legends and colours. Quote values, "
                "units, labels and names exactly as printed. If the answer depends on a table, read along the "
                "correct row and column. If this page does not contain the answer, reply exactly "
                f"{NOT_ON_PAGE}. Never guess a value, name or location that is not printed on the page.\n\n"
                f"Question: {question}")
            answer = _ask_vision(image, prompt, timeout).strip()
        except Exception:
            continue
        if answer and NOT_ON_PAGE not in answer[:40].upper() and len(answer) > 3:
            return page, answer
    return None, None


def answer_from_image(question, image_path, timeout=180, max_side=1600):
    """Answer from an uploaded image file (photo, scan, screenshot, drawing)."""
    import base64
    import io
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            image = image_path + ".qa.png"
            im.save(image, format="PNG")
        prompt = ("Answer the question using ONLY what is visible in this image: printed text, tables, "
                  "labels, legends and colours. Quote values and names exactly as shown. If the image does "
                  f"not contain the answer, reply exactly {NOT_ON_PAGE}. Never guess.\n\nQuestion: {question}")
        answer = _ask_vision(image, prompt, timeout).strip()
    except Exception:
        return None
    if answer and NOT_ON_PAGE not in answer[:40].upper() and len(answer) > 3:
        return answer
    return None
