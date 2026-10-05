import time
import base64
import httpx
t0 = time.time()
with open('test_img.png', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
try:
    res = httpx.post('http://localhost:11434/api/chat', json={
        'model': 'qwen2.5vl:7b',
        'stream': False,
        'messages': [{'role': 'user', 'content': 'Extract all text exactly.', 'images': [b64]}]
    }, timeout=120)
    print(f"Time: {time.time()-t0:.1f}s")
    print(f"Result: {res.json().get('message', {}).get('content')}")
except Exception as e:
    print(f"FAIL: {e}")
