import os
import sys

sys.path.append(os.getcwd())
import main

project = "C3085 - 3EH -Expo Hills"
query = "Tower 6 Level 2 Floor GFA"

import json

# Let's write the query to ask_model
# Actually, I'll just formulate the exact prompt that is sent to Ollama
# and send it to ollama to see what Qwen says.
context_docs = main.retrieve_context(project, query, k=8)
ctx = "\n\n".join(d.page_content for d in context_docs)[:38000]

sys_msg = f"""You are Expo Design AI, a BIM model reviewer for a client-side engineering consultancy. The user is looking at a 3D model in the viewer. The model has ALREADY been parsed from its IFC file and the extracted data is given below as MODEL DATA. Answer the user's question using this data.

MODEL DATA (extracted from the IFC file currently open in the 3D viewer):
---
{ctx}
---

ANSWER RULES:
- Use ONLY the MODEL DATA (and the selected element, if given) above. Do NOT use outside knowledge and do NOT invent or estimate any number, quantity, level, name or property.
- Quote exact values and units exactly as they appear (areas in m2, counts, level names, IFC types, property values).
- The user's wording may differ from IFC terms. Map on meaning: "columns" -> IfcColumn, "walls" -> IfcWall, "rooms"/"spaces" -> IfcSpace, "floors"/"levels"/"storeys" -> IfcBuildingStorey, "beams" -> IfcBeam, "doors" -> IfcDoor, etc.
- For "how many X" give the count of the matching IFC type. For areas, sum or list the IfcSpace areas as asked. For "what is selected" / "properties of this", use the SELECTED ELEMENT block.
- If the answer is genuinely not in the model data, say clearly: "That information is not in the current model data" and say what would provide it (e.g. select the element, or the property was not exported to IFC). NEVER fabricate.
- You ARE able to read this model -- the geometry and properties were extracted from the IFC. Never say you cannot see or open 3D models.
- Answer concisely. Use markdown (short lists / bold) when it helps a reviewer scan the answer."""

import httpx

payload = {
    "model": "qwen2.5:32b",
    "prompt": sys_msg + "\n\nUser Question: " + query + "\nAssistant:",
    "stream": False,
    "options": {
        "temperature": 0.0
    }
}

r = httpx.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=120)
print("QWEN RESPONSE:")
print(r.json().get("response"))
print("="*50)
print("PROMPT SENT:")
print(payload["prompt"])
