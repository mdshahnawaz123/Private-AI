"""General-question answering with internal self-verification (2026-10-21).

Questions that do not need the project's documents (general engineering
knowledge, explanations, writing, maths, code, small talk) are answered by the
local model in three internal steps, like a careful assistant:

  1. DRAFT   - the model reasons (think mode) and writes an answer.
  2. VERIFY  - a second pass checks the draft against the question: wrong
               facts, arithmetic errors, invented specifics, missing parts.
               Arithmetic found in the draft is re-computed in code.
  3. REVISE  - if problems were found, a corrected answer replaces the draft.

The answer is labelled as general knowledge so it is never confused with a
document-verified answer. Project-specific facts are never invented: if the
question needs the user's documents, the classifier routes it to the
document agent instead.
"""
import ast
import json
import operator
import os
import re

import httpx
from loguru import logger

DOC_HINT = re.compile(
    r"\b(this|our|the|my)\s+(project|document|doc|drawing|report|spec|specification|sheet|file|pdf|excel|model|plan|schedule|table|page)s?\b"
    r"|\b(page|sheet|table|figure|clause|section)\s+\d+|\buploaded\b|\battached\b|\bin (the|this) (pdf|file|document|drawing)\b"
    r"|\bproject\b.*\b(value|area|gfa|far|bua|units?|parking|height|cost)\b"
    r"|\b(documents?|drawings?|workbook|spreadsheet|datasheet|data sheet|pdf|excel|report|spec(?:ification)?s?|schedule|ifc|bim model|model file)\b", re.I)
SMALL_TALK = re.compile(r"^\s*(hi|hello|hey|salam|assalam\w*|good (morning|afternoon|evening)|thanks?|thank you|ok(ay)?|who are you|what can you do|help)\b[\s!?.]*$", re.I)

LABEL = ("\n\n---\n_General answer from the local AI model's own knowledge, checked internally - "
         "not taken from your project documents. Confirm codes, standards and figures against the "
         "current official source before using them for design decisions._")

SYSTEM = (
    "You are Expo Design AI, a careful senior assistant for architecture, engineering and construction (AEC) teams, "
    "running fully offline. Answer ANY kind of question helpfully: explanations, design/engineering knowledge, codes and "
    "standards in general terms, calculations, writing, summaries, planning, code, and everyday questions.\n"
    "Rules:\n"
    "- Be correct first. Think step by step internally; show working for calculations.\n"
    "- Never invent project-specific facts (this user's project values, drawings, documents, names, dates). "
    "If the question needs their documents, say so and ask them to upload or select the document.\n"
    "- For codes/standards, give the generally known requirement, name the code and edition if you know it, and say "
    "when values vary by jurisdiction or edition. If you are not sure, say so plainly instead of guessing.\n"
    "- Use clear structure (short paragraphs, bullets or a table when it helps). Use SI units unless asked otherwise.\n"
    "- Reply in the same language as the user."
)

VERIFY = (
    "You are a strict reviewer. Check the DRAFT answer to the QUESTION.\n"
    "Look for: factual errors, wrong numbers or units, arithmetic mistakes (see COMPUTED CHECKS), claims stated with "
    "false certainty, invented specifics (fake project data, made-up citations/clause numbers), unsafe advice, and parts "
    "of the question left unanswered.\n"
    "Reply with JSON only: {\"ok\": true|false, \"issues\": [\"...\"], \"revised\": \"full corrected answer, or empty if ok\"}.\n"
    "If ok is false, 'revised' must be the complete improved answer (not a diff), in the same language and style."
)

CLASSIFY = (
    "Decide how to answer the user's message in an AEC document assistant. Reply with JSON only: "
    "{\"route\": \"documents\" | \"general\"}.\n"
    "documents = the answer depends on the user's own project files (values, drawings, specs, reports, schedules, BIM "
    "model, anything 'in our project/this document'), or the message is about content that is likely in the listed files.\n"
    "general = general knowledge, explanations, definitions, how-to, writing, maths, coding, small talk, or questions "
    "that do not need the user's files.\n"
    "Writing tasks (emails, letters), explanations and definitions are general unless they ask about content of the files."
)

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}


def _safe_eval(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 10:
                raise ValueError("power too large")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("unsupported")
    return ev(ast.parse(expr, mode="eval"))


def arithmetic_checks(text):
    """Re-compute simple 'a op b ... = c' statements found in the draft."""
    out = []
    norm = text.replace("×", "*").replace("÷", "/").replace("−", "-").replace(",", "")
    for m in re.finditer(r"((?:\d+(?:\.\d+)?\s*[-+*/x^]\s*)+\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", norm):
        expr, claimed = m.group(1).replace("x", "*").replace("^", "**"), float(m.group(2))
        try:
            real = float(_safe_eval(expr))
        except Exception:
            continue
        tol = max(0.01, abs(real) * 0.005)
        status = "correct" if abs(real - claimed) <= tol else "WRONG (correct value %s)" % round(real, 6)
        out.append("%s = %s -> %s" % (m.group(1), m.group(2), status))
        if len(out) >= 12:
            break
    return out


def _chat(url, model, messages, think=False, temperature=0.3, num_predict=2048, fmt=None, timeout=240):
    body = {"model": model, "messages": messages, "stream": False, "think": think,
            "options": {"temperature": temperature, "num_ctx": 12288, "num_predict": num_predict}}
    if fmt:
        body["format"] = fmt
    r = httpx.post(url.rstrip("/") + "/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    msg = r.json().get("message") or {}
    return (msg.get("content") or "").strip()


def _json(text):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text or "", re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


WRITE_TASK = re.compile(r"^\s*(please\s+)?(write|draft|compose|prepare|create)\b.{0,40}\b(email|e-mail|letter|memo|message|note|minutes|rfi|transmittal)\b", re.I)
FROM_DOCS = re.compile(r"\b(based on|from|using|according to|summari[sz]e)\b.{0,40}\b(document|drawing|report|spec|file|pdf|workbook)", re.I)


def wants_documents(question):
    q = question or ""
    if WRITE_TASK.search(q) and not FROM_DOCS.search(q):
        return False
    return bool(DOC_HINT.search(q))


ABSTAIN = re.compile(r"could not (verify|find)|not (found|available|provided|stated|mentioned) in|no (information|reference|mention)|"
                     r"does not (contain|mention|include)|cannot find|i do not have|isn't (in|available)|is not (in|available)", re.I)


def is_abstention(text):
    t = (text or "").strip()
    return len(t) < 600 and bool(ABSTAIN.search(t))


def classify(url, model, question, doc_names):
    """'general' or 'documents'. Cheap rules first, then the model."""
    q = (question or "").strip()
    if SMALL_TALK.match(q):
        return "general"
    if WRITE_TASK.search(q) and not FROM_DOCS.search(q):
        return "general"
    if wants_documents(q):
        return "documents"
    if not doc_names:
        return "general"
    low = q.lower()
    for name in doc_names:
        stem = os.path.splitext(os.path.basename(name))[0].lower()
        if len(stem) >= 5 and stem in low:
            return "documents"
    files = "\n".join("- " + os.path.basename(n) for n in doc_names[:40])
    try:
        raw = _chat(url, model, [{"role": "system", "content": CLASSIFY},
                                 {"role": "user", "content": "Project files:\n%s\n\nUser message:\n%s" % (files, q)}],
                    temperature=0, num_predict=40, fmt="json", timeout=60)
        route = (_json(raw) or {}).get("route")
        return "general" if route == "general" else "documents"
    except Exception as exc:
        logger.warning("general_answer classify failed: {}", exc)
        return "documents"


def answer(url, model, question, history=None, status=lambda m: None):
    """Draft -> verify (with code-checked arithmetic) -> revise. Returns (text, trace)."""
    msgs = [{"role": "system", "content": SYSTEM}]
    for m in (history or [])[-6:]:
        role, content = m.get("role"), (m.get("content") or m.get("text") or "")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:3000]})
    msgs.append({"role": "user", "content": question})
    trace = {"steps": []}
    if SMALL_TALK.match(question or ""):
        status("Answering")
        draft = _chat(url, model, msgs, think=False, temperature=0.4, num_predict=400)
        trace["steps"].append("draft")
        return draft, trace
    status("Thinking it through")
    draft = _chat(url, model, msgs, think=True, num_predict=8192)
    if not draft:  # reasoning used the whole budget; answer directly
        draft = _chat(url, model, msgs, think=False, num_predict=3000)
    trace["steps"].append("draft")
    if not draft:
        return "I could not produce an answer this time. Please rephrase the question.", trace
    status("Verifying the answer")
    checks = arithmetic_checks(draft)
    review_in = "QUESTION:\n%s\n\nDRAFT:\n%s\n\nCOMPUTED CHECKS (done in code, trust these):\n%s" % (
        question, draft, "\n".join(checks) or "(no arithmetic statements found)")
    final = draft
    try:
        raw = _chat(url, model, [{"role": "system", "content": VERIFY}, {"role": "user", "content": review_in}],
                    think=False, temperature=0, fmt="json", num_predict=3000)
        verdict = _json(raw) or {}
        trace["verify"] = {"ok": verdict.get("ok"), "issues": verdict.get("issues", [])[:6], "checks": checks}
        revised = (verdict.get("revised") or "").strip()
        if verdict.get("ok") is False and len(revised) > 20:
            status("Correcting the answer")
            final = revised
            trace["steps"].append("revised")
            if arithmetic_checks(final) and any("WRONG" in c for c in arithmetic_checks(final)):
                trace["steps"].append("arithmetic-still-wrong")
                final += "\n\n_Note: a calculation above could not be confirmed automatically - please double-check it._"
    except Exception as exc:
        logger.warning("general_answer verify failed: {}", exc)
        trace["verify"] = {"error": str(exc)[:200]}
        if any("WRONG" in c for c in checks):
            final += "\n\n_Note: an automatic check found a possible calculation error: " + "; ".join(c for c in checks if "WRONG" in c) + "._"
    return final, trace


def with_label(text, small_talk=False):
    return text if small_talk else text + LABEL
