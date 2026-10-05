import os
import sys

sys.path.append(os.getcwd())
import main

project = "C3085 - 3EH -Expo Hills"
query = "Tower 6 Level 2 Floor GFA"

import json

context_docs = main.retrieve_context(project, query, k=8)
# In newer version, it returns a list of dictionaries if it's the raw retrieve_context
# Wait, let's see what retrieve_context actually returns:
if hasattr(context_docs, "results"):
    ctx = "\n\n".join(r.content for r in context_docs.results)[:38000]
else:
    # If it's old behavior returning list of docs
    try:
        ctx = "\n\n".join(d.page_content for d in context_docs)[:38000]
    except:
        ctx = "\n\n".join(str(getattr(d, "content", d)) for d in context_docs)[:38000]

sys_msg = f"""You are Expo Design AI, a BIM model reviewer for a client-side engineering consultancy. Answer the user's question using this data.

MODEL DATA:
---
{ctx}
---

ANSWER RULES:
- Use ONLY the MODEL DATA above. Do NOT use outside knowledge and do NOT invent or estimate any number.
- Quote exact values.
- Answer concisely."""

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
