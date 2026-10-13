"""Lightweight, dependency-free 'skills' system for the local LLM.

Not Claude Skills (those are an Anthropic-product-specific feature and only
run inside Claude's own tool-calling loop) -- this is the same underlying
pattern rebuilt for our local Ollama models: a library of markdown files,
each with task-specific instructions, that get pulled into the system
prompt ONLY when the user's query looks relevant, instead of permanently
bloating every prompt sent to the model.

Layout, one folder per skill under the top-level `skills/` directory:

    skills/
      compliance-clause-citation/
        SKILL.md
      quantity-takeoff-check/
        SKILL.md
      ...

Each SKILL.md has a small hand-rolled frontmatter block (deliberately not
YAML -- this is 3 known fields, a hand parser avoids adding a hard PyYAML
dependency for something this simple):

    ---
    name: compliance-clause-citation
    description: One line shown in logs/admin UI.
    keywords: comma, separated, trigger, words
    ---

    (markdown body -- the actual instructions, injected verbatim)

Matching is deliberately simple keyword overlap against the user's query,
not a second LLM call or an embedding lookup. qwen2.5vl:7b is small enough
that it is NOT trusted to decide for itself whether a skill applies --
that decision is made here, in code, and the model's only job is to follow
the instructions it's handed.
"""
from __future__ import annotations

import os
import re
import time

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_skill_md(text: str):
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    header, body = m.group(1), m.group(2).strip()
    fields = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip().lower()] = val.strip()
    name = fields.get("name", "").strip()
    if not name:
        return None
    keywords = [k.strip().lower() for k in fields.get("keywords", "").split(",") if k.strip()]
    return {
        "name": name,
        "description": fields.get("description", ""),
        "keywords": keywords,
        "body": body,
    }


def _load_all_skills():
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for entry in sorted(os.listdir(SKILLS_DIR)):
        skill_md = os.path.join(SKILLS_DIR, entry, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                parsed = _parse_skill_md(f.read())
        except Exception:
            continue
        if parsed:
            parsed["folder"] = entry
            skills.append(parsed)
    return skills


# Cached for 10s so adding/editing a SKILL.md during local development is
# picked up without a server restart, but a busy chat stream doesn't re-walk
# the filesystem on every token. Mirrors the TTL-sweep style already used by
# _pending_commands in main.py rather than introducing a new pattern.
_cache = {"ts": 0.0, "skills": []}
_CACHE_TTL = 10.0


def all_skills():
    now = time.time()
    if now - _cache["ts"] > _CACHE_TTL:
        _cache["skills"] = _load_all_skills()
        _cache["ts"] = now
    return _cache["skills"]


def match_skills(query: str, max_skills: int = 2):
    """Return the skills whose keywords appear in the query, best match first.

    Deliberately conservative: requires at least one real keyword hit (no
    fuzzy/semantic matching), and caps how many skills get injected into one
    prompt so the system message doesn't balloon on an ambiguous query that
    weakly matches several skills at once.
    """
    q = (query or "").lower()
    if not q.strip():
        return []
    scored = []
    for skill in all_skills():
        hits = sum(1 for kw in skill["keywords"] if kw and kw in q)
        if hits:
            scored.append((hits, skill))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [skill for _, skill in scored[:max_skills]]


def skills_prompt_block(query: str, max_skills: int = 2) -> str:
    """Build the text to append to the system prompt for this turn, or ''."""
    matched = match_skills(query, max_skills=max_skills)
    if not matched:
        return ""
    parts = ["\n\nTASK-SPECIFIC GUIDANCE (selected automatically for this question -- follow it in addition to, never instead of, the rules above):"]
    for skill in matched:
        parts.append(f"\n--- {skill['name']} ---\n{skill['body']}")
    return "\n".join(parts)
