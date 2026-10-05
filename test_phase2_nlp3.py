import re
import db
from intelligence.structured_query import execute_structured_query

def robust_parse_query(query: str):
    q = query.lower()
    
    word_to_num = {
        "one": "1", "first": "1", "1st": "1",
        "two": "2", "second": "2", "2nd": "2",
        "three": "3", "third": "3", "3rd": "3",
        "four": "4", "fourth": "4", "4th": "4",
        "five": "5", "fifth": "5", "5th": "5",
        "six": "6", "sixth": "6", "6th": "6",
        "seven": "7", "seventh": "7", "7th": "7",
        "eight": "8", "eighth": "8", "8th": "8",
        "nine": "9", "ninth": "9", "9th": "9",
        "ten": "10", "tenth": "10", "10th": "10",
        "eleven": "11", "eleventh": "11", "11th": "11"
    }
    
    def resolve_num(val):
        if not val: return None
        v = val.strip()
        v = word_to_num.get(v, v)
        return v.zfill(2) if v.isdigit() else v
        
    t_match = re.search(r'\b(?:tower|t)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q)
    tower = str(int(resolve_num(t_match.group(1)))) if t_match else None
    
    levels = []
    for m in re.finditer(r'\b(?:level|floor|l)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q):
        levels.append(resolve_num(m.group(1)))
    for m in re.finditer(r'\b(' + '|'.join(word_to_num.keys()) + r'|\d+(?:st|nd|rd|th)?)\s+floor\b', q):
        levels.append(resolve_num(m.group(1)))
    
    unique_levels = list(dict.fromkeys(levels))
    level = unique_levels[0] if unique_levels else None
    level_2 = unique_levels[1] if len(unique_levels) > 1 else None
    
    fields_def = [
        ('Floor GFA', ['gross floor area', 'gfa', 'area']),
        ('Floor GA', ['gross area', 'ga']),
        ('Floor NISA', ['net internal sellable area', 'nisa']),
        ('Floor NSA', ['net usable area', 'net sellable area', 'nsa']),
        ('Floor BUA', ['built up area', 'bua']),
        ('Balconies', ['balconies', 'balcony']),
        ('Floor Efficiency', ['efficiency'])
    ]
    
    # Flatten and sort aliases by length descending so longer phrases match first
    all_aliases = []
    for canonical, aliases in fields_def:
        for alias in aliases:
            all_aliases.append({"alias": alias, "canonical": canonical})
            
    all_aliases.sort(key=lambda x: len(x["alias"]), reverse=True)
    
    found_fields = []
    for item in all_aliases:
        alias = item["alias"]
        canonical = item["canonical"]
        pattern = r'\b' + alias + r'\b'
        if re.search(pattern, q):
            if canonical not in found_fields:
                found_fields.append(canonical)
            # Remove the matched phrase from string so "area" doesn't match if "net usable area" matched
            q = re.sub(pattern, '', q)
            
    target_field = found_fields[0] if len(found_fields) > 0 else None
    target_field_2 = found_fields[1] if len(found_fields) > 1 else None
    
    if not target_field:
        return None
        
    calc_type = None
    if re.search(r'\b(difference|compare|minus)\b', q):
        calc_type = "difference"
    elif re.search(r'\b(percentage|percent|%)\b', q):
        calc_type = "percentage"
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
    if target_field_2 and calc_type == "percentage": 
        res["field_2"] = target_field_2
    
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
incorrect = 0

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
    
    # Simple check for the tricky NSA query
    if "net usable area" in q and parsed.get('field') != "Floor NSA":
        print("ERROR: Parsed wrong field!")
        incorrect += 1
        failures += 1
        continue
        
    if status == 'success': successes += 1
    elif status == 'ambiguous': ambiguous += 1
    elif status == 'not_found': not_found += 1
    else: failures += 1

print("\n--- REPORT ---")
print(f"Total: {len(test_queries)}")
print(f"Successful: {successes}")
print(f"Incorrect field mapping: {incorrect}")
print(f"Failed parsing/eval: {failures}")
print(f"Ambiguous handled properly: {ambiguous}")
print(f"Not found handled properly: {not_found}")
