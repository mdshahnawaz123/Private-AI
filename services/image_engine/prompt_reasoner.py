"""
Prompt Reasoning Engine for Expo Design AI Image Studio.

Uses local reasoning model (qwen3.5:9b via Ollama) to expand user architectural
briefs into rich, material-aware, lighting-accurate photorealistic prompts.
Strictly unloads VRAM (keep_alive: 0) immediately after reasoning to preserve
the 16 GB RTX 5080 budget for the subsequent diffusion render pass.
"""
import json
import os
from typing import Any, Dict, Optional
import httpx
from loguru import logger

OLLAMA_URL = os.getenv("EXPO_OLLAMA_HOST", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
REASONING_MODEL = os.getenv("EXPO_REASONING_MODEL", "qwen3.5:9b")

SYSTEM_REASONING_PROMPT = (
    "You are an expert architectural visualization director. "
    "Given an architectural design brief, style, and building type, reason through the architectural "
    "composition, materials, textures, ambient lighting, and environmental context. "
    "Return valid JSON ONLY with exactly two keys:\n"
    "\"reasoning\": 1-2 concise sentences explaining the architectural intent, lighting conditions, and material palette.\n"
    "\"enhanced_prompt\": a single cohesive, high-detail prompt for the diffusion render engine (40 to 75 words).\n"
    "Do NOT include markdown formatting or commentary outside the JSON."
)


async def enhance_architectural_prompt(
    prompt: str,
    building_type: Optional[str] = None,
    architectural_style: Optional[str] = None,
    unload_vram: bool = True,
    timeout_sec: float = 25.0,
) -> Dict[str, Any]:
    """
    Reason about and expand an architectural design prompt using qwen3.5:9b.
    Immediately frees GPU memory when unload_vram=True (keep_alive=0).
    Falls back gracefully to the original prompt if Ollama is unreachable.
    """
    if not prompt or not prompt.strip():
        return {
            "success": False,
            "original_prompt": prompt,
            "enhanced_prompt": prompt,
            "reasoning": None,
            "error": "Empty prompt",
        }

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
            {"role": "system", "content": SYSTEM_REASONING_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": 0 if unload_vram else "5m",
        "options": {
            "temperature": 0.6,
            "num_predict": 300,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        raw_content = data.get("message", {}).get("content", "").strip()
        parsed = json.loads(raw_content)

        enhanced = parsed.get("enhanced_prompt") or prompt
        reasoning = parsed.get("reasoning") or "Architectural design reasoning applied."

        logger.info(
            f"Prompt reasoning completed via {REASONING_MODEL}: enhanced '{prompt[:40]}...' ({len(enhanced)} chars)"
        )

        return {
            "success": True,
            "original_prompt": prompt,
            "enhanced_prompt": enhanced.strip(),
            "reasoning": reasoning.strip(),
            "model": REASONING_MODEL,
        }

    except Exception as exc:
        logger.warning(
            f"Prompt reasoning skipped/fallback due to: {type(exc).__name__}: {exc}. Using deterministic prompt."
        )
        # Deterministic architectural fallback
        arch_prefix = ""
        if building_type or architectural_style:
            btype_part = f" of a {building_type}" if building_type else ""
            style_part = f" in {architectural_style} style" if architectural_style else ""
            arch_prefix = f"Architectural render{btype_part}{style_part}. "
        fallback_prompt = f"{arch_prefix}{prompt.strip()}, highly detailed, professional architectural visualization"

        return {
            "success": False,
            "original_prompt": prompt,
            "enhanced_prompt": fallback_prompt,
            "reasoning": "Standard architectural synthesis (Reasoning engine offline/fallback).",
            "error": str(exc),
        }
