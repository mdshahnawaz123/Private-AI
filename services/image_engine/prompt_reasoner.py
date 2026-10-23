"""
Architectural Visualization Director & Prompt Reasoning Engine for Expo Design AI.

Emulates ChatGPT-grade architectural prompt direction:
- Strictly preserves all hard user constraints (e.g. floor count "G+10", program, site context).
- Injects physical camera optics (eye-level 2-point perspective, 24mm tilt-shift lens, zero vertical keystoning).
- Emphasizes structural tectonics, floor-to-floor slab edges, podium-to-tower transition, and PBR materials.
- Avoids generic CGI buzzwords ("photorealistic, 8k, unreal engine") in favor of tactile physical descriptions.
- Synthesizes 3 distinct architectural design options (Option A, Option B, Option C) for immediate selection.
- Strictly unloads VRAM (keep_alive: 0) immediately after reasoning to preserve GPU memory for diffusion sampling.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from loguru import logger

OLLAMA_URL = os.getenv("EXPO_OLLAMA_HOST", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
REASONING_MODEL = os.getenv("EXPO_REASONING_MODEL", "qwen3.5:9b")

SYSTEM_ARCHITECTURAL_DIRECTOR_PROMPT = """You are an elite Architectural Visualization Director and Principal Architect (ChatGPT-grade architectural prompt designer).

Your mission is to transform the user's architectural brief into an ultra-realistic, highly detailed, photorealistic render prompt suitable for physical diffusion models.

MANDATORY DIRECTIVES:
1. STRICT CONSTRAINT PRESERVATION (ABSOLUTE RULE):
   - You MUST identify and strictly preserve all explicit constraints: floor counts (e.g. "G+10", "10 floors", "5-story", "ground + 10 levels", "podium"), building typologies, site/climate conditions, and specific materials.
   - NEVER alter, round, contradict, or omit these constraints. If the user asked for G+10, the building MUST feature a ground floor podium plus exactly 10 upper stories clearly articulated in the vertical facade massing.

2. ARCHITECTURAL PERSPECTIVE & PHYSICAL OPTICS:
   - Establish physical camera optics: Eye-level (1.7m human eye level) 2-point perspective or subtle low-angle street perspective looking up, shot on architectural tilt-shift lens (24mm or 28mm), zero vertical keystoning (perfect vertical parallel lines), crisp orthogonal rectilinear framing.

3. TECTONIC DEPTH & PBR REALISM (ZERO GENERIC BUZZWORDS):
   - Never use empty words like "photorealistic", "hyperrealistic", "unreal engine", "8k", "masterpiece", "trending on artstation".
   - Instead, describe tactile physical construction details: floor-to-floor heights, continuous horizontal concrete slab edges articulating each floor level, double-height ground floor lobby with 3000K warm interior illumination, anodized bronze or graphite aluminum mullions, Low-E double glazing with realistic interior depth and subtle reflections, deep 200mm shadow reveals, recessed spandrels, textured architectural finishes (board-formed concrete, flamed granite pavers, warm timber soffits, integrated lush balcony planter boxes).

4. NATURAL SOLAR DAYLIGHTING & ATMOSPHERE:
   - Specific sun angle: Late afternoon golden hour low sun (15-degree sun angle) casting crisp architectural shadow patterns, or soft diffused overcast morning light with rich ambient occlusion.
   - Surrounding environment: Pedestrian plaza with human figures at realistic distance for 1:1 scale reference, manicured urban landscaping, clean reflection in glass.

5. THREE DISTINCT ARCHITECTURAL DESIGN SCHEMES:
   - Create 3 distinct architectural design options honoring the exact same hard user constraints:
     * Option A: Biophilic & Terraced (integrated greenery, warm timber soffits, lush planter boxes)
     * Option B: Contemporary Glass & High-Tech Metallic (precision curtain wall, bronze/champagne fins, floating cantilevers)
     * Option C: Sculptural Monolithic Stone & Concrete (textured architectural concrete, flamed stone, rhythmic deep window reveals)

Output valid JSON ONLY with these exact keys:
{
  "preserved_constraints": ["G+10 (Ground + 10 upper stories)", "Residential typology", ...],
  "architectural_reasoning": "A concise architectural critique (2-3 sentences) analyzing massing, tectonic articulation, floor count expression, and daylighting.",
  "enhanced_prompt": "The primary recommended ChatGPT-grade architectural render prompt (80-140 words)",
  "design_options": [
    {
      "id": "option_a",
      "title": "Biophilic & Terraced",
      "style": "Biophilic Modernism",
      "prompt": "Full render prompt for option A honoring all constraints...",
      "rationale": "Architectural rationale for option A..."
    },
    {
      "id": "option_b",
      "title": "High-Tech Glass & Metallic",
      "style": "Contemporary High-Tech",
      "prompt": "Full render prompt for option B honoring all constraints...",
      "rationale": "Architectural rationale for option B..."
    },
    {
      "id": "option_c",
      "title": "Sculptural Monolithic Stone",
      "style": "Minimalist Tectonic",
      "prompt": "Full render prompt for option C honoring all constraints...",
      "rationale": "Architectural rationale for option C..."
    }
  ]
}
"""


def _render_skill_text() -> str:
    """FLUX 3 render-prompting rules from skills/architectural-render-prompting (2026-10-22)."""
    import os, re
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "skills", "architectural-render-prompting", "SKILL.md")
    try:
        text = open(path, encoding="utf-8").read()
        return re.sub(r"^---.*?---\s*", "", text, flags=re.S).strip()
    except OSError:
        return ""


def _system_prompt() -> str:
    skill = _render_skill_text()
    if not skill:
        return SYSTEM_ARCHITECTURAL_DIRECTOR_PROMPT
    return (SYSTEM_ARCHITECTURAL_DIRECTOR_PROMPT +
            "\n\nFLUX 3 RENDER-PROMPTING RULES (these take precedence over the camera, lighting, wording and "
            "option-style defaults above whenever they conflict; keep the same JSON keys and output format):\n" + skill)


def _detect_user_invariants(prompt: str, building_type: Optional[str] = None) -> List[str]:
    """Detect explicit architectural constraints like floor count, podium, typology."""
    constraints = []
    text = f"{prompt} {building_type or ''}"
    
    # Floor count patterns: G+10, B+G+10, 2B+G+15, G+2
    g_plus = re.findall(r"\b([A-Z0-9]+\s*\+\s*[A-Z0-9]+(?:\s*\+\s*[A-Z0-9]+)?)\b", text, re.IGNORECASE)
    for m in g_plus:
        clean = re.sub(r"\s+", "", m).upper()
        constraints.append(f"{clean} floor count")
    
    stories = re.findall(r"\b(\d+)[- ]*(?:stor(?:y|ies)|floors?|levels?)\b", text, re.IGNORECASE)
    for s in stories:
        constraints.append(f"{s}-story vertical height")
    
    # Typology
    typologies = ["residential", "commercial", "office", "mixed-use", "hotel", "villa", "pavilion", "tower", "hospital", "museum", "cultural"]
    for t in typologies:
        if re.search(rf"\b{t}\b", text, re.IGNORECASE):
            constraints.append(f"{t.capitalize()} typology")
            break
            
    # Podiums / Terraces / Balconies
    if re.search(r"\bpodium\b", text, re.IGNORECASE):
        constraints.append("Podium base")
    if re.search(r"\bbalcon(?:y|ies)\b", text, re.IGNORECASE):
        constraints.append("Integrated balconies")
    if re.search(r"\bterrace[s]?\b", text, re.IGNORECASE):
        constraints.append("Stepped terraces")
    if re.search(r"\bdubai\b", text, re.IGNORECASE):
        constraints.append("Dubai context/climate")

    return list(dict.fromkeys(constraints))


def _enforce_invariants(
    prompt: str,
    enhanced_prompt: str,
    preserved_constraints: List[str]
) -> tuple[str, List[str]]:
    """Guarantees that user hard constraints (like G+10) are never omitted from the render prompt."""
    res_constraints = list(preserved_constraints)
    detected = _detect_user_invariants(prompt)
    for d in detected:
        if not any(d.lower() in c.lower() for c in res_constraints):
            res_constraints.append(d)

    # Check for G+10 or similar floor patterns
    g_matches = re.findall(r"\b([A-Z0-9]+\s*\+\s*[A-Z0-9]+(?:\s*\+\s*[A-Z0-9]+)?)\b", prompt, re.IGNORECASE)
    for g in g_matches:
        g_clean = re.sub(r"\s+", "", g).upper()
        if g_clean not in enhanced_prompt.upper():
            # Invariant reinforcement: prepend floor specification
            enhanced_prompt = f"Architectural rendering of a {g_clean} building. {enhanced_prompt}"
            
    return enhanced_prompt, res_constraints


def _build_deterministic_options(
    prompt: str,
    building_type: Optional[str] = None,
    architectural_style: Optional[str] = None,
    error_msg: Optional[str] = None
) -> Dict[str, Any]:
    """Generates 3 rich deterministic architectural options preserving all user invariants."""
    clean_prompt = prompt.strip()
    detected = _detect_user_invariants(clean_prompt, building_type)
    
    # Extract any floor specification or default to prompt essence
    g_match = re.search(r"\b([A-Z0-9]+\s*\+\s*[A-Z0-9]+(?:\s*\+\s*[A-Z0-9]+)?)\b", clean_prompt, re.IGNORECASE)
    floor_spec = re.sub(r"\s+", "", g_match.group(1)).upper() if g_match else ""
    floor_prefix = f"{floor_spec} " if floor_spec else ""
    
    opt_a_prompt = (
        f"Eye-level 2-point perspective architectural photograph of a {floor_prefix}{clean_prompt}. "
        "Stepped biophilic balconies with lush native planter boxes and warm timber soffit ceilings. "
        "Clear floor-to-floor slab edge articulation showing each individual level, double-height entrance lobby "
        "with 3000K warm interior illumination, zero vertical keystoning, shot on 24mm tilt-shift architectural lens, "
        "late afternoon golden hour sunlight casting sharp linear shadow reveals across flamed granite paving."
    )
    
    opt_b_prompt = (
        f"Low-angle street perspective of a {floor_prefix}{clean_prompt}. "
        "High-performance curtain wall glazing with anodized bronze vertical shading fins and extruded aluminum spandrels. "
        "Crisp structural rhythm expressing all upper levels above a glazed podium base, Low-E glass reflecting warm ambient sky, "
        "zero vertical distortion, shot on 28mm tilt-shift lens, crisp rectilinear composition with pedestrian figures for scale."
    )
    
    opt_c_prompt = (
        f"Eye-level architectural composition of a {floor_prefix}{clean_prompt}. "
        "Sculptural board-formed fair-faced concrete facade paired with flamed limestone panels and deep 200mm recessed window punctures. "
        "Tactile tectonic depth, ground floor entrance canopy, clear horizontal slab lines articulating all floor tiers, "
        "soft overcast diffuse morning daylight with rich ambient occlusion, crisp architectural photography."
    )

    reasoning = (
        f"Architectural Director analysis applied to {floor_prefix or 'the project'}: "
        "Vertical massing articulated with distinct ground podium and clearly expressed upper levels to preserve user requirements. "
        "Physical camera optics calibrated to 2-point perspective with zero keystoning."
    )

    return {
        "success": False,
        "original_prompt": prompt,
        "enhanced_prompt": opt_a_prompt,
        "reasoning": reasoning if not error_msg else f"{reasoning} (Reasoning engine fallback: {error_msg})",
        "preserved_constraints": detected,
        "design_options": [
            {
                "id": "option_a",
                "title": "Biophilic & Terraced",
                "style": "Biophilic Modernism",
                "prompt": opt_a_prompt,
                "rationale": "Softens vertical massing with cantilevered green balconies and warm organic timber finishes."
            },
            {
                "id": "option_b",
                "title": "High-Tech Glass & Metallic",
                "style": "Contemporary High-Tech",
                "prompt": opt_b_prompt,
                "rationale": "Maximizes natural daylighting and precision detailing with bronze louvers and curtain wall glazing."
            },
            {
                "id": "option_c",
                "title": "Sculptural Monolithic Stone",
                "style": "Minimalist Tectonic",
                "prompt": opt_c_prompt,
                "rationale": "Commands tectonic presence with board-formed concrete and deeply recessed thermal reveals."
            }
        ],
        "model": "deterministic_director_fallback",
        "error": error_msg,
    }


async def enhance_architectural_prompt(
    prompt: str,
    building_type: Optional[str] = None,
    architectural_style: Optional[str] = None,
    unload_vram: bool = True,
    timeout_sec: float = 60.0,
) -> Dict[str, Any]:
    """
    Reason about and expand an architectural design prompt using qwen3.5:9b.
    Acts as an Architectural Visualization Director emulating ChatGPT:
    - Strictly preserves user requirements (e.g. G+10 floor count, program, geometry).
    - Injects physical camera optics, tectonic floor slab articulation, and PBR materials.
    - Yields 3 structured architectural design options.
    - Immediately unloads VRAM (keep_alive: 0) when unload_vram=True to free GPU memory for diffusion.
    - Gracefully falls back to deterministic architectural director if Ollama is offline.
    """
    if not prompt or not prompt.strip():
        return {
            "success": False,
            "original_prompt": prompt,
            "enhanced_prompt": prompt,
            "reasoning": None,
            "preserved_constraints": [],
            "design_options": [],
            "error": "Empty prompt",
        }

    from services.image_engine.comfyui_client import ComfyUIClient
    local_url = ComfyUIClient._validate_and_normalize_url(OLLAMA_URL)

    # Construct user message
    parts = []
    if building_type:
        parts.append(f"Building Type: {building_type}")
    if architectural_style:
        parts.append(f"Architectural Style: {architectural_style}")
    parts.append(f"Design Brief: {prompt.strip()}")
    user_content = "\n".join(parts)

    payload = {
        "model": REASONING_MODEL,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": 0 if unload_vram else "5m",
        "options": {
            "temperature": 0.65,
            "num_predict": 1200,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, trust_env=False) as client:
            resp = await client.post(f"{local_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        raw_content = data.get("message", {}).get("content", "").strip()
        
        # Clean potential markdown wrapping if present
        if raw_content.startswith("```"):
            raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content)
            raw_content = re.sub(r"\s*```$", "", raw_content)

        parsed = json.loads(raw_content)

        enhanced = parsed.get("enhanced_prompt") or prompt
        reasoning = parsed.get("architectural_reasoning") or parsed.get("reasoning") or "Architectural design reasoning applied."
        raw_constraints = parsed.get("preserved_constraints") or []
        if isinstance(raw_constraints, str):
            raw_constraints = [raw_constraints]

        # Enforce invariant preservation (e.g. G+10)
        enhanced, preserved_constraints = _enforce_invariants(prompt, enhanced, raw_constraints)

        # Parse design options
        raw_options = parsed.get("design_options") or []
        design_options = []
        if isinstance(raw_options, list):
            for opt in raw_options:
                if isinstance(opt, dict) and opt.get("prompt"):
                    opt_prompt, _ = _enforce_invariants(prompt, opt.get("prompt"), [])
                    design_options.append({
                        "id": opt.get("id") or f"opt_{len(design_options)+1}",
                        "title": opt.get("title") or "Architectural Scheme",
                        "style": opt.get("style"),
                        "prompt": opt_prompt.strip(),
                        "rationale": opt.get("rationale") or opt.get("explanation"),
                    })

        logger.info(
            f"Prompt reasoning completed via {REASONING_MODEL}: enhanced '{prompt[:40]}...' ({len(enhanced)} chars, {len(preserved_constraints)} constraints, {len(design_options)} options)"
        )

        return {
            "success": True,
            "original_prompt": prompt,
            "enhanced_prompt": enhanced.strip(),
            "reasoning": reasoning.strip(),
            "preserved_constraints": preserved_constraints,
            "design_options": design_options,
            "model": REASONING_MODEL,
        }

    except Exception as exc:
        logger.warning(
            f"Prompt reasoning fallback due to: {type(exc).__name__}: {exc}. Using deterministic director options."
        )
        return _build_deterministic_options(prompt, building_type, architectural_style, error_msg=str(exc))
