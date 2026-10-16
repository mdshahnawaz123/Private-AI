"""Local design proposals: structured instructions, never geometry certification."""
import json
import httpx
from services.image_engine import prompt_reasoner
from services.image_engine.comfyui_client import ComfyUIClient

PROTECTED = ["floor count", "building outline", "structural grid, columns and slabs", "openings, parking and ramps", "signage", "camera and perspective"]

SCOPES = {
    "creative_facade": "Redesign only the external facade screen: change its pattern, perforations, panel rhythm, fins and screen materials within the existing facade envelope. Keep overall massing, silhouette, roofline, floor count, slab levels, structural grid, window and door positions, entrances, parking and ramps unchanged. Keep access and openings clear. Do not add balconies, extensions or floors. Screen detail may change; the underlying building geometry must not.",
    "materials": "Change facade surface materials, colour and texture only. Keep the existing screen pattern, fins, panel layout and all underlying building geometry unchanged.",
    "enhancement": "Improve rendering quality, exposure, material realism and reflections only. Keep the facade design, screen pattern, materials and all building geometry unchanged.",
    "concept": "Develop a new architectural concept within the original written brief.",
}


def compile_option(brief, option, index):
    protected = list(dict.fromkeys(PROTECTED + brief.protected_elements)) if brief.mode != "concept" else list(brief.protected_elements)
    # The original brief is retained verbatim rather than trusting a model summary.
    sections = ["Original design brief: " + brief.prompt, "Mode: " + brief.mode]
    if brief.mode != "concept":
        sections += ["Use the uploaded image as the fixed reference. Keep unchanged: " + "; ".join(protected),
                     SCOPES[brief.mode]]
    materials = brief.materials or option["materials"]
    lighting = brief.lighting or ("Keep the source lighting direction" if brief.mode != "concept" else "Natural daylight")
    sections += ["Materials: " + materials, "Requested variation: " + option["changes"],
                 "Lighting: " + lighting, "Avoid: changed overall building geometry, unreadable signage, invented structural details, text overlays."]
    if brief.mode != "concept":
        sections.append("Final edit boundary (takes precedence over suggestions): " + SCOPES[brief.mode])
    prompt = "\n".join(sections)
    if len(prompt) > 32000:
        raise ValueError("The complete design brief exceeds 32000 characters. Shorten the brief or additional constraints.")
    return {"id": "option_" + str(index+1), "title": option["title"], "style": brief.architectural_style,
            "prompt": prompt, "rationale": option["rationale"], "materials": materials,
            "shading_strategy": option["shading_strategy"], "changes": option["changes"], "protected_elements": protected}


def fallback_options(brief):
    if brief.mode == "creative_facade":
        names = [("Vertical fin screen", "Redesign the external screen with a vertical fin rhythm within the existing envelope"),
                 ("Perforated panel screen", "Redesign the external screen with a perforated panel pattern within the existing envelope"),
                 ("Geometric lattice screen", "Redesign the external screen with an ordered geometric lattice within the existing envelope")]
        return [{"title": title, "materials": brief.materials or "Retain the reference material palette unless the brief requests a change",
                 "changes": changes, "shading_strategy": "Screen arrangement proposal only; shading performance requires separate assessment",
                 "rationale": "An editable screen alternative; keep the underlying building, openings and camera fixed. No image analysis performed."}
                for title, changes in names]
    if brief.mode == "enhancement":
        names = [("Balanced daylight", "Balanced exposure and restrained surface detail"),
                 ("Material detail", "Emphasise finish texture without altering edges or openings"),
                 ("Soft reflections", "Reduce harsh glazing reflections and preserve source illumination direction")]
    else:
        names = [("Warm mineral finish", "Warm mineral finish within existing facade panels"),
                 ("Refined metal finish", "Subtle metallic finish within existing opaque facade panels"),
                 ("Textured masonry finish", "Restrained textured finish within existing facade panels")]
    return [{"title": title, "materials": brief.materials or changes, "changes": changes if not brief.materials else title + ": vary finish texture within the specified material palette only",
             "shading_strategy": "Preserve existing shading geometry; no performance claim",
             "rationale": "A brief-based starting option for manual review; no image analysis or structural validation performed."} for title,changes in names]


async def generate_design_brief(brief):
    url = ComfyUIClient._validate_and_normalize_url(prompt_reasoner.OLLAMA_URL)
    constraints = list(dict.fromkeys(PROTECTED + brief.protected_elements)) if brief.mode != "concept" else brief.protected_elements
    system = ("Return JSON with exactly three distinct options in an options list. Each option must have nonempty string title, materials, changes, shading_strategy, rationale. "
              "You are proposing alternatives from a written brief, NOT analysing an image. Do not claim the image was inspected or geometry was preserved. "
              "Preserve all user constraints, specified materials, floor counts, openings, signage and camera. "
              "Never propose new floors, massing, balconies, openings or camera optics for reference modes. "
              "Do not invent dimensions, compliance, energy performance or structural feasibility. Make rationale concrete and concise. "
              "Explicit user requirements override stylistic suggestions. For enhancement mode vary rendering treatment only. "
              "Each field max 200 characters; do not output a diffusion prompt. Authoritative edit scope: " + SCOPES[brief.mode])
    data = brief.model_dump();data["protected_elements"] = constraints
    payload = {"model": prompt_reasoner.REASONING_MODEL, "messages": [{"role":"system","content":system},{"role":"user","content":json.dumps(data)}],
               "format":"json","stream":False,"think":False,"keep_alive":0,"options":{"temperature":0.35,"num_predict":1000}}
    model = None;error = None
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            response = await client.post(url + "/api/chat", json=payload)
            response.raise_for_status()
            choices = json.loads(response.json()["message"]["content"])["options"]
        fields = ("title", "materials", "changes", "shading_strategy", "rationale")
        if len(choices) != 3 or any(not isinstance(c,dict) or any(not isinstance(c.get(k),str) or not c[k].strip() or len(c[k])>400 for k in fields) for c in choices):
            raise ValueError("Reasoner returned incomplete design options")
        if len({c['title'].strip().casefold() for c in choices}) != 3 or len({c['changes'].strip().casefold() for c in choices}) != 3:
            raise ValueError("Reasoner returned duplicate options")
        model = prompt_reasoner.REASONING_MODEL
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        choices = fallback_options(brief)
        error = "Local reasoning unavailable or invalid; showing editable brief-based presets."
    options = [compile_option(brief,c,i) for i,c in enumerate(choices)]
    return {"success":True,"original_prompt":brief.prompt,"enhanced_prompt":options[0]['prompt'],
            "reasoning":"Three proposals based on your written brief. The reference image has not been analysed; preservation instructions are not a geometry guarantee.",
            "preserved_constraints":constraints,"design_options":options,"model":model,"error":error}
