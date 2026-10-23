"""Exact viewer-count answers and a final numerical evidence check for BIM prose.

Viewer evidence is a client snapshot, not a certified quantity takeoff. No area
or volume is inferred from geometry, units, names or category counts.
"""
import json
import re
import math

MISSING = 'That information is not in the current model data. Select the element or provide a model export containing the requested properties and units.'
ALIASES = {
    'door': ('IFCDOOR',), 'window': ('IFCWINDOW',),
    'wall': ('IFCWALL', 'IFCWALLSTANDARDCASE', 'IFCWALLELEMENTEDCASE'),
    'column': ('IFCCOLUMN', 'IFCCOLUMNSTANDARDCASE'), 'beam': ('IFCBEAM', 'IFCBEAMSTANDARDCASE'),
    'room': ('IFCSPACE',), 'space': ('IFCSPACE',), 'storey': ('IFCBUILDINGSTOREY',),
    'story': ('IFCBUILDINGSTOREY',), 'level': ('IFCBUILDINGSTOREY',),
    'slab': ('IFCSLAB', 'IFCSLABSTANDARDCASE'), 'roof': ('IFCROOF',),
}


def selected_quantity(question, selection):
    requested = [name for name in ('width', 'height', 'length', 'thickness', 'area', 'volume')
                 if re.search(r'\b' + name + r'\b', question.casefold())]
    if len(requested) != 1:
        return MISSING
    field = requested[0]
    keys = {field, 'overall' + field, 'net' + field, 'gross' + field}
    try:
        data = json.loads(selection or 'null')
    except (ValueError, TypeError):
        return MISSING
    values = set()
    def visit(item, depth=0):
        if depth > 16:
            return
        if isinstance(item, list):
            for child in item[:500]: visit(child, depth + 1)
        elif isinstance(item, dict):
            for key, value in item.items():
                if re.sub(r'[^a-z]', '', key.casefold()) in keys:
                    raw = value.get('value') if isinstance(value, dict) else value
                    unit = value.get('unit', value.get('Unit', '')) if isinstance(value, dict) else ''
                    if isinstance(unit, dict): unit = unit.get('value', '')
                    if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9µ²³^/% .-]{0,24}', unit): unit = ''
                    if (type(raw) in (int, float, str) and len(str(raw)) <= 100
                            and re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', str(raw))
                            and math.isfinite(float(raw))):
                        values.add((str(raw), str(unit)[:40]))
                if isinstance(value, (dict, list)): visit(value, depth + 1)
    visit(data)
    if len(values) != 1:
        return MISSING
    value, unit = values.pop()
    return f'{field.capitalize()}: **{value}**' + (f' {unit}.' if unit else '. Unit not supplied; no conversion was inferred.') + '\n\nSource: selected element properties in the current viewer snapshot.'


def exact_model_answer(question, context, selection=''):
    """Return a deterministic quantity answer, or None for non-quantity prose."""
    query = question.casefold()
    numeric = bool(re.search(r'\b(how many|count|number of|quantity|area|volume|height|width|length|thickness|total)\b', query))
    if not numeric:
        return None
    if not re.search(r'\b(how many|count|number of)\b', query):
        return selected_quantity(question, selection)
    try:
        data = json.loads(context)
    except (TypeError, ValueError):
        return MISSING
    if not isinstance(data, dict):
        return MISSING
    counts = data.get('counts')
    models = data.get('models')
    if data.get('counts_complete') is not True or not isinstance(counts, dict) or not isinstance(models, list) or not models:
        return MISSING
    if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in counts.items()):
        return MISSING
    # Reject partial or malformed aggregate contracts instead of trusting totals.
    for category, total in counts.items():
        if any(not isinstance(m, dict) or type(m.get('counts', {}).get(category, 0)) is not int for m in models):
            return MISSING
        if sum(m.get('counts', {}).get(category, 0) for m in models) != total:
            return MISSING
    matches = [name for name in ALIASES if re.search(r'\b' + name + r'(?:s|ies)?\b', query)]
    requested = re.findall(r'\bIFC[A-Z]+\b', question.upper())
    families = [(name, ALIASES[name]) for name in matches]
    if not families and requested:
        families = [(category, (category,)) for category in requested]
    if not families:
        return MISSING
    # Accept whole-category count questions only. Any unexecuted constraint
    # (colour, level, rating, exclusion, etc.) must not become an all-items count.
    vocabulary = {'how', 'many', 'count', 'number', 'of', 'the', 'a', 'an', 'and',
                  'are', 'there', 'is', 'current', 'loaded', 'model', 'models',
                  'please', 'tell', 'me', 'have', 'do', 'we'}
    vocabulary.update(ALIASES)
    vocabulary.update(name + 's' for name in ALIASES)
    vocabulary.update(c.lower() for _, group in families for c in group)
    if set(re.findall(r'\b[a-z0-9]+\b', query)) - vocabulary:
        return MISSING
    # Spatial/property filters require tools we have not executed. Do not answer
    # "doors on level 2" with the unfiltered whole-model door count.
    if re.search(r'\b(on|at|in|with|where|above|below|selected|visible|fire|external|internal|level|storey|story)\b', query) and not any(
            name in ('level', 'storey', 'story') and re.fullmatch(r'(?:how many|count|number of)\s+' + name + r'(?:s)?[?. ]*', query) for name in matches):
        return MISSING
    names = ', '.join(str(m.get('name') or m.get('id') or 'model') for m in models)
    lines = [f'{name.capitalize()}: **{sum(counts.get(c, 0) for c in family)}**' for name, family in families]
    return '\n'.join(lines) + '\n\nSource: current viewer snapshot (' + names + '). Counts include loaded models; no area or volume was inferred.'


def validate_model_prose(answer, context, selection):
    """Never publish model-generated numerical values absent from supplied data."""
    evidence = str(context or '') + '\n' + str(selection or '')
    numbers = set(re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?', evidence))
    claimed = set(re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?', answer))
    return answer if claimed <= numbers else MISSING
