"""
FLOORA Engine — Autodesk AI Lab FLOORA-1.7B Integration
Model: ADSKAILab/floora-1.7b (Hugging Face)
Paper: FLOORA: A Human-Aligned Domain-Specific Language Model for Architectural Design (arXiv:2609.36064)

Generates structured multifamily residential floor plans from massing geometry,
structural materials, and building metadata using Autodesk's architectural DSL.
"""

import os
import re
from typing import Dict, List, Tuple, Any

MODEL_ID_1_7B = "ADSKAILab/floora-1.7b"
MODEL_ID_0_6B = "ADSKAILab/floora-0.6b"

_model = None
_tokenizer = None
_device = None

def get_floora_model(model_id: str = MODEL_ID_1_7B):
    """
    Lazy loader for FLOORA model and custom tokenizer.
    """
    global _model, _tokenizer, _device
    if _model is not None:
        return _model, _tokenizer, _device

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"[FLOORA] Loading model {model_id}...")
    _tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if hasattr(_tokenizer, "add_eos_token"):
        _tokenizer.add_eos_token = False

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[FLOORA] Using device: {_device}")

    _model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16 if _device == "cuda" else torch.float32,
        trust_remote_code=True,
    )
    _model.to(_device)
    _model.eval()
    print("[FLOORA] Model loaded successfully.")
    return _model, _tokenizer, _device


def build_floora_prompt(
    massing_polygon: List[Tuple[float, float]],
    storeys: int = 12,
    level: int = 2,
    elevation: int = 60,
    height: int = 35,
    material: str = "concrete_frame",
    occupancy_type: str = "multifamily_residential"
) -> str:
    """
    Builds the structured <context> prompt expected by FLOORA.
    Coordinates are normalized to integers as expected by the DSL tokenizer.
    """
    poly_str = " ".join([f"{int(round(x))},{int(round(y))}" for x, y in massing_polygon])
    
    prompt = f"""<context>
<building>
building {{ occupancy_type {occupancy_type} storeys {storeys} level {level} elevation {elevation} }}
</building>
<structure>
structure {{ material {material} }}
</structure>
<massing>
massing {{ height {height} polygon {poly_str} }}
</massing>
</context>
<generate>
<space>
</generate>
<completion>
"""
    return prompt


def parse_coord_list(coords_text: str) -> List[List[int]]:
    """Parse coordinate text string into list of [x, y] integer pairs."""
    points = []
    for coord_pair in re.findall(r"\d+\s*,\s*\d+", coords_text):
        points.append(list(map(int, re.split(r"\s*,\s*", coord_pair))))
    return points


def parse_floora_completion(generated_text: str) -> Dict[str, Any]:
    """
    Parses the generated FLOORA architectural DSL completion into vector polygons.
    """
    elements = {
        "cores": [],
        "corridors": [],
        "living_units": [],
        "other": []
    }

    completion_pattern = r"<completion>(.*?)(?:</completion>|$)"
    match = re.search(completion_pattern, generated_text, re.DOTALL)
    completion_content = match.group(1).strip() if match else generated_text

    space_pattern = r"polygon\s+(\w+)\s+((?:\d+\s*,\s*\d+\s*)+)"
    for m in re.finditer(space_pattern, completion_content):
        space_type = m.group(1).lower()
        coords = parse_coord_list(m.group(2))
        item = {
            "type": space_type,
            "coordinates": coords
        }
        if space_type == "core":
            elements["cores"].append(item)
        elif space_type == "corridor":
            elements["corridors"].append(item)
        elif space_type in ("living_unit", "unit", "apartment"):
            elements["living_units"].append(item)
        else:
            elements["other"].append(item)

    return elements


def generate_floora_layout(
    massing_polygon: List[Tuple[float, float]],
    storeys: int = 12,
    material: str = "concrete_frame",
    max_new_tokens: int = 2048
) -> Dict[str, Any]:
    """
    End-to-end floorplan generation using Autodesk's FLOORA model.
    """
    import torch

    model, tokenizer, device = get_floora_model()
    prompt = build_floora_prompt(massing_polygon, storeys=storeys, material=material)

    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    stop_token_ids = {tokenizer.eos_token_id}
    eoc_token_id = getattr(tokenizer, "eoc_token_id", None)
    if eoc_token_id is not None:
        stop_token_ids.add(eoc_token_id)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=list(stop_token_ids),
            do_sample=True,
            temperature=0.7,
            top_p=0.95
        )

    output_str = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=False)
    parsed = parse_floora_completion(output_str)

    return {
        "prompt": prompt,
        "raw_dsl": output_str,
        "elements": parsed,
        "summary": {
            "num_cores": len(parsed["cores"]),
            "num_corridors": len(parsed["corridors"]),
            "num_units": len(parsed["living_units"])
        }
    }


if __name__ == "__main__":
    test_polygon = [(0, 0), (400, 0), (400, 250), (280, 250), (280, 180), (120, 180), (120, 250), (0, 250)]
    p = build_floora_prompt(test_polygon, storeys=12)
    print("Sample FLOORA Prompt:\n", p)
