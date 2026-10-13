"""Read-only local-Qwen skill pilot. No downloads or application configuration writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from intelligence.answer_guard import guarded_answer
from intelligence.citation_identity import prepare_citations, resolve_citations
from intelligence.exact_answers import exact_answer
from intelligence.native_titleblock import native_title_answer
from intelligence.native_schedule import native_schedule_answer
from intelligence.inspection_answers import inspection_answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(args.source).resolve()
    meta = json.loads(Path(str(path) + '.index.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != meta.get('source_sha256') or meta.get('processing_complete') is False or meta.get('truncated'):
        raise RuntimeError('Current, complete source evidence is required')
    from config import resolve_role
    import httpx
    from langchain_core.messages import SystemMessage, HumanMessage
    from local_chat import LocalChatOllama
    role = resolve_role('chat')
    if urlparse(role['base_url']).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('This pilot permits loopback model services only')
    model = role['model']
    if model not in ('qwen3.5:9b', 'qwen2.5:7b', 'qwen2.5vl:7b'):
        raise RuntimeError('Model not allowed for this pilot')
    available = httpx.get(role['base_url'].rstrip('/') + '/api/tags', timeout=10).raise_for_status().json()
    if model not in {m['name'] for m in available['models']}:
        raise RuntimeError('Configured model is not installed; no download will be attempted')
    doc = {'filename': path.name, 'path': str(path), 'status': 'ready_with_warnings'}
    skill = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text(encoding='utf-8')
    questions = [
        ('title', 'Give the drawing title, level and zone.', native_title_answer),
        ('schedule', 'What are the width, length and depth of drop panel DP10?', native_schedule_answer),
        ('review', 'What review comments limit construction approval?', inspection_answer),
        ('missing', 'What is the depth of SYNTH-060?', None),
    ]
    # Native PDF text, not noisy drawing table reconstructions or vision output.
    evidence = '\n\n'.join(f"[SOURCE: {path.name} | PAGE {p['page']}]\n{p.get('text', '')}" for p in meta.get('pages', []))
    if len(evidence) > 30000:
        raise RuntimeError('Pilot evidence budget exceeded; select a smaller source')
    sources = [{'source': path.name, 'page': p['page']} for p in meta.get('pages', [])]
    results = {'model': model, 'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(),
               'source_sha256': digest, 'production_integration': False, 'cases': []}
    for name, question, tool in questions:
        reading = tool(question, [doc]) if tool else None
        context = evidence
        if reading and reading.get('status') == 'SUCCESS':
            context += '\n\nHOST EXACT NATIVE-FIELD READING (not construction certification):\n' + reading['answer']
        model_context, identities = prepare_citations(context, sources)
        llm = LocalChatOllama(model=model, url=role['base_url'], temperature=0,
                              num_predict=700, keep_alive='5m', timeout=180)
        started = time.monotonic()
        raw = ''.join(c.content for c in llm.stream([
            SystemMessage(content=skill + '\n\nSOURCE EVIDENCE:\n' + model_context),
            HumanMessage(content=question)]))
        answer = resolve_citations(raw, identities)
        published, issues = guarded_answer(answer, context, sources)
        row = {'case': name, 'question': question, 'seconds': round(time.monotonic()-started, 3),
               'raw_answer': raw, 'answer': answer, 'published_answer': published,
               'gate_issues': issues, 'tool_reading': reading,
               'assessment': 'PENDING_SOURCE_REVIEW'}
        results['cases'].append(row)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps({k: row[k] for k in ('case', 'seconds', 'answer', 'gate_issues')}), flush=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Source changed during the pilot; discard results')


if __name__ == '__main__':
    main()
