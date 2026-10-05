import re
import db
from intelligence.structured_query import execute_structured_query

def robust_parse_query(query: str):
    q = query.lower()
    
    word_to_num = {
        "one": "1", "first": "1",
        "two": "2", "second": "2",
        "three": "3", "third": "3",
        "four": "4", "fourth": "4",
        "five": "5", "fifth": "5",
        "six": "6", "sixth": "6",
        "seven": "7", "seventh": "7",
        "eight": "8", "eighth": "8",
        "nine": "9", "ninth": "9",
        "ten": "10", "tenth": "10",
        "eleven": "11", "eleventh": "11"
    }
    
    def resolve_num(val):
        if not val: return None
        v = val.strip()
        return word_to_num.get(v, v).zfill(2) if v.isdigit() or v in word_to_num else v
        
    # Tower detection
    # "tower 6", "tower six", "t6"
    t_match = re.search(r'\b(?:tower|t)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q)
    tower = str(int(resolve_num(t_match.group(1)))) if t_match else None
    
    # Level detection
    # "level 2", "l2", "second floor", "level 02", "floor 2"
    levels = []
    # Match standard "level X" or "floor X" or "lX"
    for m in re.finditer(r'\b(?:level|floor|l)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q):
        levels.append(resolve_num(m.group(1)))
    # Match "Xth floor"
    for m in re.finditer(r'\b(' + '|'.join(word_to_num.keys()) + r'|\d+(?:st|nd|rd|th)?)\s+floor\b', q):
        val = m.group(1).replace('st','').replace('nd','').replace('rd','').replace('th','')
        levels.append(resolve_num(val))
    
    # Remove duplicates preserving order
    unique_levels = list(dict.fromkeys(levels))
    level = unique_levels[0] if unique_levels else None
    level_2 = unique_levels[1] if len(unique_levels) > 1 else None
    
    # Field detection
    fields = [
        ('Floor GFA', ['gfa', 'gross floor area']),
        ('Floor GA', ['ga\b', 'gross area']), # \b to prevent matching 'gaps' but python regex needs care
        ('Floor NISA', ['nisa', 'net internal sellable area']),
        ('Floor NSA', ['nsa', 'net sellable area', 'net usable area']),
        ('Floor BUA', ['bua', 'built up area']),
        ('Balconies', ['balcony', 'balconies']),
        ('Floor Efficiency', ['efficiency'])
    ]
    
    target_field = None
    target_field_2 = None
    found_fields = []
    
    for canonical, aliases in fields:
        for alias in aliases:
            # use word boundaries unless it's a multi-word phrase
            pattern = r'\b' + re.escape(alias) + r'\b' if len(alias.split()) == 1 else re.escape(alias)
            if re.search(pattern, q):
                if canonical not in found_fields:
                    found_fields.append(canonical)
                break
                
    target_field = found_fields[0] if len(found_fields) > 0 else None
    
    if not target_field:
        return None
        
    # Calculation detection
    calc_type = None
    if re.search(r'\b(difference|compare|minus)\b', q):
        calc_type = "difference"
    elif re.search(r'\b(percentage|percent|%)\b', q):
        calc_type = "percentage"
        if len(found_fields) > 1:
            target_field_2 = found_fields[1]
    elif re.search(r'\b(total|sum)\b', q):
        calc_type = "sum"
        
    res = {
        "type": "structured",
        "tower": tower,
        "level": level,
        "field": target_field,
        "calc": calc_type
    }
    if level_2: res["level_2"] = level_2
    if target_field_2: res["field_2"] = target_field_2
    
    return res

test_queries = [
    "What is the GFA of Tower 6 Level 2?",
    "How much gross floor area is on Level 2 of Tower 6?",
    "Tell me Tower 6's Level 02 GFA.",
    "What is the gross floor area for Tower Six, second floor?",
    "How much area does Tower 6 have on L2?",
    "Give me the Floor GA for Tower 6 Level 2.",
    "What is Tower 6 Level 2 net usable area?",
    "What is the total GFA of Tower 6?",
    "Compare Tower 6 Level 2 and Level 11 GFA.",
    "What is Level 2 GFA?",
    "What is Tower 99 Level 1 GFA?"
]

print("--- PHASE 2 NLP PARSER TEST ---")
project_id = 1
successes = 0
failures = 0
ambiguous = 0
not_found = 0

for q in test_queries:
    print(f"\nUser question: {q}")
    parsed = robust_parse_query(q)
    print(f"Parsed structured intent: {parsed}")
    
    if not parsed:
        print("Validation: FAILED to parse intent")
        failures += 1
        continue
        
    status, context = execute_structured_query(parsed, project_id)
    print(f"Validation: {status.upper()}")
    print(f"Final answer:\n{context}")
    
    if status == 'success': successes += 1
    elif status == 'ambiguous': ambiguous += 1
    elif status == 'not_found': not_found += 1
    else: failures += 1

print("\n--- REPORT ---")
print(f"Total: {len(test_queries)}")
print(f"Successful: {successes}")
print(f"Failed parsing/eval: {failures}")
print(f"Ambiguous handled properly: {ambiguous}")
print(f"Not found handled properly: {not_found}")
