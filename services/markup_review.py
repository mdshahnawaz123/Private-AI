"""Build review facts from input records; model output can only label disciplines."""
DISCIPLINES = {'Architectural', 'Structural', 'MEP', 'Code Egress', 'General'}
CLOSED = {'accepted', 'resolved', 'closed', 'completed'}


def build_review(markups, doc_name='', classifications=None):
    labels = {}
    if isinstance(classifications, list):
        for item in classifications:
            if not isinstance(item, dict):
                continue
            index, discipline = item.get('index'), item.get('discipline')
            if type(index) is int and 1 <= index <= len(markups) and discipline in DISCIPLINES:
                labels[index] = discipline
    facts, groups, suggestions = [], {}, []
    for index, markup in enumerate(markups, 1):
        identity = str(markup.get('id') or f'markup-{index}')
        citation = {'document': doc_name or 'Active Plan', 'markup_id': identity,
                    'input_index': index, 'page': markup.get('page')}
        fact = {'markup_id': identity, 'page': markup.get('page'),
                'status': markup.get('status') or 'Unspecified',
                'author': markup.get('author') or 'Unspecified',
                'type': markup.get('type') or markup.get('subject') or 'Unspecified',
                'text': str(markup.get('text') or ''),
                'measurement': markup.get('measurement'), 'citation': citation}
        facts.append(fact)
        groups.setdefault(labels.get(index, 'General'), []).append(fact)
        if str(fact['status']).strip().casefold() not in CLOSED:
            suggestions.append({'text': f'Review unresolved markup {identity} with the responsible reviewer.',
                                'kind': 'workflow_suggestion', 'citation': citation})
    open_count = len(suggestions)
    return {'executive_summary': f'{len(facts)} markups recorded; {open_count} are unresolved or have no closure status. '
                                 'Facts below reproduce the submitted markups. Workflow suggestions are not document requirements.',
            'total_count': len(facts), 'open_issues_count': open_count, 'by_discipline': groups,
            'facts': facts, 'suggestions': suggestions,
            'action_items': [f"Suggestion: {item['text']}" for item in suggestions],
            'review_basis': 'Submitted markup records only; drawing content and engineering recommendations are not independently verified.',
            'classification_basis': 'AI discipline labels; verify grouping' if labels else 'Unclassified input records'}
