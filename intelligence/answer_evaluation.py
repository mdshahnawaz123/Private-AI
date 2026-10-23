"""Small real-answer evaluator; callers supply independently verified gold cases.

No built-in benchmark answers, canned model callbacks or status-only passes.
The callback must invoke the same authenticated application answer path being
evaluated. This utility never invents gold labels or advertises model accuracy
from the regression tests which exercise this evaluator.
"""
from time import perf_counter
import re


def evaluate_cases(cases, ask):
    if not cases:
        raise ValueError('Independently labelled cases required')
    results = []
    for case in cases:
        if not case.get('question') or not case.get('source_hash'):
            raise ValueError('Each case needs a question and independently checked source hash')
        gold = case.get('expected_answer')
        abstain = case.get('expect_abstention') is True
        if not abstain and (not isinstance(gold, str) or not gold.strip() or not case.get('expected_sources')):
            raise ValueError('Answer text and exact source/page labels required')
        start = perf_counter()
        actual = ask(case['question'])
        if not isinstance(actual, dict) or actual.get('mocked') or actual.get('model_digest') in (None, '', 'mock'):
            raise ValueError('Actual model/pipeline result with model digest required')
        normalize = lambda value: re.sub(r'\s+', ' ', str(value)).strip().casefold()
        answer = str(actual.get('answer') or '')
        if abstain:
            correct = actual.get('abstained') is True
            citation_correct = not actual.get('sources')
        else:
            # Exact comparison is deliberately conservative. A human can review
            # equivalent prose; a permissive substring must not hide extra claims.
            correct = normalize(answer) == normalize(gold) and not actual.get('abstained')
            identity = lambda source: (str(source.get('document_id') or source.get('source') or ''), str(source.get('page')))
            expected = {identity(s) for s in case['expected_sources']}
            returned = {identity(s) for s in actual.get('sources', [])}
            citation_correct = bool(expected) and expected == returned
        results.append({'question': case['question'], 'answer': answer,
            'answer_correct': bool(correct), 'citation_correct': citation_correct,
            'passed': bool(correct and citation_correct), 'seconds': perf_counter() - start,
            'model_digest': actual['model_digest'], 'source_hash': case['source_hash'],
            'sources': actual.get('sources', [])})
    return {'evaluation_kind': 'labelled_answer_and_citation', 'total': len(results),
            'answer_exact_match': sum(r['answer_correct'] for r in results) / len(results),
            'citation_exact_match': sum(r['citation_correct'] for r in results) / len(results),
            'results': results}
