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
    if brief.mode == "concept":
        # FLUX weights the opening words most: lead with the subject and camera so it renders one building, not a site plan.
        sections = ["Architectural photograph, eye-level street view of a single building: " + brief.prompt, "Mode: " + brief.mode]
    else:
        sections = ["Original design brief: " + brief.prompt, "Mode: " + brief.mode]
    if brief.mode != "concept":
        sections += ["Use the uploaded image as the fixed reference. Keep unchanged: " + "; ".join(protected),
                     SCOPES[brief.mode]]
    materials = brief.materials or option["materials"]
    lighting = brief.lighting or ("Keep the source lighting direction" if brief.mode != "concept" else "Natural daylight")
    sections += ["Materials: " + materials, "Requested variation: " + option["changes"],
                 "Lighting: " + lighting, ("Keep: the overall building geometry as described, structure plausible and consistent, plain facades and a clean image without lettering or signs." if brief.mode != "concept" else "Composition: one building as the clear subject, seen from eye level on the street, with the site context and climate described in the brief; plain facades without lettering or signs.")]
    if brief.mode != "concept":
        sections.append("Final edit boundary (takes precedence over suggestions): " + SCOPES[brief.mode])
    prompt = "\n".join(sections)
    if brief.mode == "concept":
        # Text-to-image: FLUX 3 renders labelled "Key: value" briefs as diagrams/site plans, so write one prose
        # paragraph following the render skill order (subject and massing, facade, camera, light, context).
        def _s(t):
            t = (t or "").strip().rstrip(".")
            return t[:1].upper() + t[1:] if t else ""
        parts = ["Eye-level architectural photograph of " + _s(brief.prompt)[:1].lower() + _s(brief.prompt)[1:],
                 _s(option["changes"]), "Facade materials: " + _s(materials),
                 "Camera at pedestrian height across the street, the whole building in frame as the single subject, vertical lines straight",
                 _s(lighting), "Plain facades without lettering or signs"]
        if brief.protected_elements:
            parts.insert(1, "Keep " + ", ".join(brief.protected_elements))
        prompt = ". ".join(p for p in parts if p) + "."
    if len(prompt) > 32000:
        raise ValueError("The complete design brief exceeds 32000 characters. Shorten the brief or additional constraints.")
    return {"id": "option_" + str(index+1), "title": option["title"], "style": brief.architectural_style,
            "prompt": prompt, "rationale": option["rationale"], "materials": materials,
            "shading_strategy": option["shading_strategy"], "changes": option["changes"], "protected_elements": protected}


def fallback_options(brief, n=3):
    if brief.mode == "creative_facade":
        names = [("Vertical fin screen", "Redesign the external screen with a vertical fin rhythm within the existing envelope"),
                 ("Perforated panel screen", "Redesign the external screen with a perforated panel pattern within the existing envelope"),
                 ("Geometric lattice screen", "Redesign the external screen with an ordered geometric lattice within the existing envelope"),
                 ("Horizontal louvre screen", "Redesign the external screen with horizontal louvres within the existing envelope"),
                 ("Folded plate screen", "Redesign the external screen with folded metal plates within the existing envelope"),
                 ("Layered mesh screen", "Redesign the external screen with layered metal mesh within the existing envelope")][:n]
        return [{"title": title, "materials": brief.materials or "Retain the reference material palette unless the brief requests a change",
                 "changes": changes, "shading_strategy": "Screen arrangement proposal only; shading performance requires separate assessment",
                 "rationale": "An editable screen alternative; keep the underlying building, openings and camera fixed. No image analysis performed."}
                for title, changes in names]
    if brief.mode == "enhancement":
        names = [("Balanced daylight", "Balanced exposure and restrained surface detail"),
                 ("Material detail", "Emphasise finish texture without altering edges or openings"),
                 ("Soft reflections", "Reduce harsh glazing reflections and preserve source illumination direction"),
                 ("Crisp contrast", "Sharper edge contrast and clearer shadow definition"),
                 ("Overcast calm", "Even, diffuse light with soft shadows"),
                 ("Evening glow", "Warm interior glow behind the glazing")][:n]
    else:
        names = [("Warm mineral finish", "Warm mineral finish within existing facade panels"),
                 ("Refined metal finish", "Subtle metallic finish within existing opaque facade panels"),
                 ("Textured masonry finish", "Restrained textured finish within existing facade panels"),
                 ("Light stone finish", "Pale natural stone finish within existing facade panels"),
                 ("Timber accent finish", "Timber accents within existing facade panels"),
                 ("Dark ceramic finish", "Dark glazed ceramic finish within existing facade panels")][:n]
    return [{"title": title, "materials": brief.materials or changes, "changes": changes if not brief.materials else title + ": vary finish texture within the specified material palette only",
             "shading_strategy": "Preserve existing shading geometry; no performance claim",
             "rationale": "A brief-based starting option for manual review; no image analysis or structural validation performed."} for title,changes in names]



_ALIASES = {"title": ("title", "name", "option", "option_name"), "materials": ("materials", "material", "material_palette"),
            "changes": ("changes", "change", "description", "design_change"), "shading_strategy": ("shading_strategy", "shading", "climate_strategy"),
            "rationale": ("rationale", "reason", "why")}


def _extract_options(data, fields):
    """Accept the shapes small local models actually return: {"options": [...]}, a bare list, or another key holding the list."""
    if isinstance(data, dict):
        lst = data.get("options")
        if isinstance(lst, dict):
            lst = [lst]
        if not isinstance(lst, list):
            lst = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
        if lst is None:
            # A single option object returned on its own, or options keyed by name ({"option_1": {...}}).
            inner = [v for v in data.values() if isinstance(v, dict)]
            lst = inner if inner else [data]
    else:
        lst = data if isinstance(data, list) else []
    out = []
    for c in lst:
        if not isinstance(c, dict):
            continue
        low = {str(k).lower().strip(): v for k, v in c.items()}
        row = {}
        for f in fields:
            v = next((low[a] for a in _ALIASES[f] if isinstance(low.get(a), str) and low[a].strip()), "")
            row[f] = v.strip()[:400]
        if row["title"] and row["changes"]:
            for f in fields:
                row[f] = row[f] or ("Not specified" if f != "materials" else "As described in the brief")
            out.append(row)
    return out

async def generate_design_brief(brief):
    n = int(getattr(brief, "option_count", 3) or 3)
    url = ComfyUIClient._validate_and_normalize_url(prompt_reasoner.OLLAMA_URL)
    constraints = list(dict.fromkeys(PROTECTED + brief.protected_elements)) if brief.mode != "concept" else brief.protected_elements
    system = ("Return JSON with exactly " + str(n) + " distinct options in an options list. Each option must have nonempty string title, materials, changes, shading_strategy, rationale. "
              "You are proposing alternatives from a written brief, NOT analysing an image. Do not claim the image was inspected or geometry was preserved. "
              "Preserve all user constraints, specified materials, floor counts, openings, signage and camera. "
              "Never propose new floors, massing, balconies, openings or camera optics for reference modes. "
              "Do not invent dimensions, compliance, energy performance or structural feasibility. Make rationale concrete and concise. "
              "Explicit user requirements override stylistic suggestions. For enhancement mode vary rendering treatment only. "
              "The options must differ in substance (for example facade system, screen or panel logic, or climate response, within the edit scope), not only in colour, lighting or camera. Write changes as positive statements of what to show. "
              "Each field max 200 characters; do not output a diffusion prompt. Authoritative edit scope: " + SCOPES[brief.mode])
    data = brief.model_dump();data["protected_elements"] = constraints
    payload = {"model": prompt_reasoner.REASONING_MODEL, "messages": [{"role":"system","content":system},{"role":"user","content":json.dumps(data)}],
               "format":"json","stream":False,"think":False,"keep_alive":0,"options":{"temperature":0.35,"num_predict":1000}}
    model = None;error = None
    fields = ("title", "materials", "changes", "shading_strategy", "rationale")
    payload["options"]["num_predict"] = 500 * n + 300
    last_exc = None
    collected = []
    # The local model often returns fewer options than asked (frequently just one). Keep asking for the
    # missing ones, telling it which titles already exist, until we have n distinct options or run out of tries.
    for _attempt in range(n + 2):
        need = n - len(collected)
        if need <= 0:
            break
        msgs = list(payload["messages"])
        if collected:
            msgs = msgs + [{"role": "user", "content": "Already proposed (do not repeat these strategies): " + "; ".join(c["title"] for c in collected)
                            + ". Return JSON with exactly " + str(need) + " NEW, substantially different options in an options list."}]
        try:
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                response = await client.post(url + "/api/chat", json={**payload, "messages": msgs})
                response.raise_for_status()
                got = _extract_options(json.loads(response.json()["message"]["content"]), fields)
            seen_t = {c["title"].casefold() for c in collected}; seen_c = {c["changes"].casefold() for c in collected}
            for c in got:
                if c["title"].casefold() not in seen_t and c["changes"].casefold() not in seen_c:
                    collected.append(c); seen_t.add(c["title"].casefold()); seen_c.add(c["changes"].casefold())
            if not got:
                raise ValueError("Reasoner returned no usable options")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            last_exc = exc
            payload["options"]["temperature"] = 0.5
    if len(collected) >= n:
        choices = collected[:n]
        model = prompt_reasoner.REASONING_MODEL
    elif collected:
        # Keep the real AI options and top up with presets rather than discarding them.
        choices = collected + fallback_options(brief, n)[: n - len(collected)]
        model = prompt_reasoner.REASONING_MODEL
        error = f"The local model proposed {len(collected)} of {n} options; the rest are editable presets."
    if model is None:
        exc = last_exc
        choices = fallback_options(brief, n)
        error = "Local reasoning unavailable or invalid (" + (str(exc)[:160] if exc else "unknown") + "); showing editable brief-based presets."
    options = [compile_option(brief,c,i) for i,c in enumerate(choices)]
    return {"success":True,"original_prompt":brief.prompt,"enhanced_prompt":options[0]['prompt'],
            "reasoning":str(n) + " proposals based on your written brief. The reference image has not been analysed; preservation instructions are not a geometry guarantee.",
            "preserved_constraints":constraints,"design_options":options,"model":model,"error":error}
