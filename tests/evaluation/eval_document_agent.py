"""Run the bounded agent against C5055; retain actual results and timing."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from intelligence.document_agent import run_agent

root = Path('data/docs/C5055 - Sider').resolve()
source = root / 'Drawings/C5055-SDW-2DR0229-ST-2B11102(1).pdf'
cases = ['Give the drawing title, level and zone.',
         'What are the width, length and depth of drop panel DP10?',
         'What review comments limit construction approval?',
         'What is the depth of SYNTH-060?']
results = []
for question in cases:
    start = time.monotonic()
    result = run_agent(question, root, source)
    results.append({'question': question, 'seconds': round(time.monotonic()-start, 3), **result})
    out = Path('output/document-agent/results.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results[-1]), flush=True)
