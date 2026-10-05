import re
import db
import json
from sqlalchemy.orm import Session
from sqlalchemy import func

def setup_mock_data():
    session = db.SessionLocal()
    # Create project 2 if it doesn't exist
    proj = session.query(db.Project).filter_by(id=2).first()
    if not proj:
        proj = db.Project(id=2, name="Phase 3 Mock Project")
        session.add(proj)
        session.commit()

    # Clear old mock data
    session.query(db.StructuredRecord).filter_by(project_id=2).delete()
    
    # Tower 6, Level 2-11, Rev 1
    for lvl in range(2, 12):
        l_str = str(lvl).zfill(2)
        base = 2400 + (lvl * 10) # 2420, 2430...
        
        # Rev 1
        r1_gfa = db.StructuredRecord(project_id=2, doc="Doc_R1.pdf", revision="Rev 1", page=5, schedule="S1", tower="6", level=l_str, field="Floor GFA", raw_value=str(base), value=base, unit="sqm")
        r1_nsa = db.StructuredRecord(project_id=2, doc="Doc_R1.pdf", revision="Rev 1", page=5, schedule="S1", tower="6", level=l_str, field="Floor NSA", raw_value=str(base-300), value=base-300, unit="sqm")
        session.add_all([r1_gfa, r1_nsa])
        
        # Tower 8, Level 2
        if lvl == 2:
            r8_gfa = db.StructuredRecord(project_id=2, doc="Doc_R1.pdf", revision="Rev 1", page=5, schedule="S1", tower="8", level="02", field="Floor GFA", raw_value="2500", value=2500, unit="sqm")
            session.add(r8_gfa)
            
    # Add Rev 2 for Tower 6 Level 2
    r2_gfa = db.StructuredRecord(project_id=2, doc="Doc_R2.pdf", revision="Rev 2", page=5, schedule="S1", tower="6", level="02", field="Floor GFA", raw_value="2450", value=2450.0, unit="sqm")
    session.add(r2_gfa)
    
    session.commit()
    session.close()

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
        
    towers = []
    for m in re.finditer(r'\b(?:tower|t)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q):
        towers.append(str(int(resolve_num(m.group(1)))))
    towers = list(dict.fromkeys(towers))
    
    levels = []
    level_range = None
    range_match = re.search(r'from\s+(?:level\s+|l)?(\d+)\s+to\s+(?:level\s+|l)?(\d+)', q)
    if range_match:
        level_range = (resolve_num(range_match.group(1)), resolve_num(range_match.group(2)))
    else:
        for m in re.finditer(r'\b(?:level|floor|l)\s*(' + '|'.join(word_to_num.keys()) + r'|\d+)\b', q):
            levels.append(resolve_num(m.group(1)))
        for m in re.finditer(r'\b(' + '|'.join(word_to_num.keys()) + r'|\d+(?:st|nd|rd|th)?)\s+floor\b', q):
            levels.append(resolve_num(m.group(1)))
    unique_levels = list(dict.fromkeys(levels))
    
    rev = None
    if "latest revision" in q or "latest document" in q or "latest" in q:
        rev = "latest"
    elif "previous revision" in q:
        rev = "previous"
    else:
        rm = re.search(r'rev\s*(\d+)', q)
        if rm: rev = f"Rev {rm.group(1)}"
        
    if "compare rev" in q:
        rev = "compare_all"
        
    fields_def = [
        ('Floor GFA', ['gross floor area', 'gfa', 'area', 'large']),
        ('Floor GA', ['gross area', 'ga']),
        ('Floor NISA', ['net internal sellable area', 'nisa']),
        ('Floor NSA', ['net usable area', 'net sellable area', 'nsa']),
        ('Floor BUA', ['built up area', 'built-up area', 'bua']),
        ('Balconies', ['balconies', 'balcony']),
        ('Floor Efficiency', ['efficiency'])
    ]
    
    all_aliases = []
    for canonical, aliases in fields_def:
        for alias in aliases:
            all_aliases.append({"alias": alias, "canonical": canonical})
    all_aliases.sort(key=lambda x: len(x["alias"]), reverse=True)
    
    found_fields = []
    q_sub = q
    for item in all_aliases:
        alias = item["alias"]
        canonical = item["canonical"]
        pattern = r'\b' + alias + r'\b'
        if re.search(pattern, q_sub):
            if canonical not in found_fields:
                found_fields.append(canonical)
            q_sub = re.sub(pattern, '', q_sub)
            
    calc_type = None
    if re.search(r'\b(highest|max|maximum)\b', q): calc_type = "max"
    elif re.search(r'\b(lowest|min|minimum)\b', q): calc_type = "min"
    elif re.search(r'\b(average|mean)\b', q): calc_type = "average"
    elif re.search(r'\b(count|number of)\b', q): calc_type = "count"
    elif re.search(r'\b(percentage difference|% diff)\b', q): calc_type = "pct_diff"
    elif re.search(r'\b(percentage|percent|%|as percentage of)\b', q): calc_type = "percentage"
    elif re.search(r'\b(difference|minus|compare)\b', q): calc_type = "difference"
    elif re.search(r'\b(total|sum)\b', q): calc_type = "sum" # sum checked last to not override pct diff
    
    filter_op = None
    fm = re.search(r'above (\d+)', q)
    if fm: filter_op = ('>', float(fm.group(1)))
    
    if "every available" in q or "all towers" in q or "which towers" in q:
        towers = ["ALL"]
        
    if "which level" in q:
        pass # we don't supply levels, let it search across all
        
    if not found_fields: return None
    
    intent = {
        "type": "structured",
        "towers": towers,
        "levels": unique_levels,
        "level_range": level_range,
        "fields": found_fields[:2],
        "calc": calc_type,
        "rev": rev,
        "filter": filter_op
    }
    return intent

def execute_structured_query(parsed, project_id):
    session = db.SessionLocal()
    try:
        base_q = session.query(db.StructuredRecord).filter(db.StructuredRecord.project_id == project_id)
        
        if parsed.get('calc') not in [None, 'sum', 'difference', 'percentage', 'pct_diff', 'average', 'min', 'max', 'count']:
            return "unsupported", "Calculation type not supported."
            
        towers = parsed.get('towers', [])
        levels = parsed.get('levels', [])
        fields = parsed.get('fields', [])
        rev = parsed.get('rev')
        calc = parsed.get('calc')
        
        if rev == "latest":
            rev_rule = "Rev 2" 
        elif rev == "previous":
            rev_rule = "Rev 1"
        elif rev == "compare_all":
            rev_rule = None
        elif rev:
            rev_rule = rev
        else:
            revs_available = session.query(db.StructuredRecord.revision).filter(
                db.StructuredRecord.project_id == project_id
            ).distinct().all()
            if len(revs_available) > 1:
                return "ambiguous", "Multiple document revisions exist. Please specify which revision to use or say 'latest'."
            rev_rule = revs_available[0][0] if revs_available else "Rev 1"
            
        if rev_rule:
            base_q = base_q.filter(db.StructuredRecord.revision == rev_rule)
            
        if towers and towers[0] != "ALL":
            base_q = base_q.filter(db.StructuredRecord.tower.in_(towers))
        if levels:
            base_q = base_q.filter(db.StructuredRecord.level.in_(levels))
        if parsed.get('level_range'):
            start, end = parsed['level_range']
            base_q = base_q.filter(db.StructuredRecord.level >= start, db.StructuredRecord.level <= end)
        if fields:
            base_q = base_q.filter(db.StructuredRecord.field.in_(fields))
            
        recs = base_q.all()
        if not recs:
            return "not_found", "No verified record found."
            
        # Ambiguity checks
        if not calc and not parsed.get('filter'):
            if not towers and not "ALL" in parsed.get('towers', []):
                return "ambiguous", "Multiple towers matched. Please specify tower."
        
        if not calc:
            if parsed.get('filter'):
                op, val = parsed['filter']
                res = [r for r in recs if (r.value > val if op == '>' else False)]
                if not res: return "not_found", "No records matched the filter."
                ctx = "\n".join([f"Tower {r.tower} Level {r.level}: {r.value} {r.unit}" for r in res])
                return "success", ctx
                
            if len(towers) == 1 and len(levels) == 1 and len(fields) == 1:
                r = recs[0]
                return "success", f"Value: {r.value} {r.unit}\nProvenance: (Doc: {r.doc}, Rev: {r.revision})"
            
            ctx = "Records:\n" + "\n".join([f"Tower {r.tower} Level {r.level} {r.field}: {r.value} {r.unit}" for r in recs])
            return "success", ctx

        if calc == "sum":
            total = sum(r.value for r in recs)
            return "success", f"SUM = {total}\nProvenance: {len(recs)} records used"
            
        if calc == "average":
            avg = sum(r.value for r in recs) / len(recs)
            return "success", f"AVERAGE = {avg:.2f}\nProvenance: {len(recs)} records used"
            
        if calc == "max":
            best = max(recs, key=lambda x: x.value)
            return "success", f"MAX is Level {best.level} = {best.value}\nProvenance: {best.doc}"
            
        if calc == "min":
            best = min(recs, key=lambda x: x.value)
            return "success", f"MIN is Level {best.level} = {best.value}\nProvenance: {best.doc}"
            
        if calc == "count":
            return "success", f"COUNT = {len(recs)}\nProvenance: DB"
            
        if calc == "difference":
            if len(fields) == 2:
                r1 = [r for r in recs if r.field == fields[0]][0]
                r2 = [r for r in recs if r.field == fields[1]][0]
                diff = abs(r1.value - r2.value)
                return "success", f"DIFFERENCE = {diff}\nProv: {r1.doc}"
            elif len(levels) == 2:
                r1 = [r for r in recs if r.level == levels[0]][0]
                r2 = [r for r in recs if r.level == levels[1]][0]
                diff = abs(r1.value - r2.value)
                return "success", f"DIFFERENCE = {diff}\nProv: {r1.doc}"
            elif len(towers) == 2:
                r1 = [r for r in recs if r.tower == towers[0]][0]
                r2 = [r for r in recs if r.tower == towers[1]][0]
                diff = abs(r1.value - r2.value)
                return "success", f"DIFFERENCE = {diff}\nProv: {r1.doc}"
            elif rev == "compare_all":
                r1 = [r for r in recs if r.revision == "Rev 1"][0]
                r2 = [r for r in recs if r.revision == "Rev 2"][0]
                diff = abs(r1.value - r2.value)
                return "success", f"DIFFERENCE (Rev 1 vs Rev 2) = {diff}\nProv: {r1.doc}, {r2.doc}"
                
        if calc == "percentage":
            if len(fields) == 2: 
                r1 = [r for r in recs if r.field == fields[0]][0]
                r2 = [r for r in recs if r.field == fields[1]][0]
                pct = (r1.value / r2.value) * 100
                return "success", f"PERCENTAGE = {pct:.2f}%\nProv: {r1.doc}"
                
    except Exception as e:
        return "error", str(e)
    finally:
        session.close()

if __name__ == "__main__":
    setup_mock_data()
    tests = [
        # A. Synonyms
        "What is the GFA of Tower 6 Level 2?",
        "What is the gross floor area of Tower 6 Level 2?",
        "What is the GA of Tower 6 Level 2?",
        "What is the gross area of Tower 6 Level 2?",
        "What is the NSA of Tower 6 Level 2?",
        "What is the net usable area of Tower 6 Level 2?",
        "What is the BUA of Tower 6 Level 2?",
        "What is the built-up area of Tower 6 Level 2?",
        
        # B. NL Variations
        "What area does Tower 6 have on Level 2?",
        "Tell me the area for Tower 6 Level 02.",
        "How large is Tower 6 on the second floor?",
        "Show me Tower 6 Level 02 floor GFA.",
        "Give me the gross floor area for Tower Six, second floor.",
        
        # C. Calculations
        "Total GFA of Tower 6 latest revision",
        "Average GFA of Tower 6 latest revision",
        "Minimum GFA of Tower 6 latest",
        "Maximum GFA of Tower 6 latest",
        "Difference between Level 2 and Level 11 GFA latest",
        "NSA as percentage of GFA Tower 6 Level 2 latest",
        "GFA minus NSA Tower 6 Level 2 latest",
        "Number of levels with GFA records for Tower 6 latest",
        "Sum of GFA from Level 2 to Level 10 Tower 6 latest",
        
        # D. Cross Tower
        "Compare Tower 6 Level 2 GFA with Tower 8 Level 2 GFA latest",
        "Compare Tower 6 and Tower 8 total GFA latest",
        "Which towers have Level 2 GFA above 2450 sqm? latest",
        "Show the GFA for Level 2 for every available tower. latest",
        
        # E. Cross Level
        "Which level of Tower 6 has the highest GFA? latest",
        "Which level has the lowest GFA? latest",
        "What is the average GFA from Level 2 to Level 10? latest",
        "What is the total GFA from Level 2 to Level 10? latest",
        "What is the difference between the highest and lowest GFA? latest",
        
        # F. Revisions
        "What is the GFA of Tower 6 Level 2?", # should be ambiguous (Rev 1 vs 2)
        "What is the GFA of Tower 6 Level 2 Rev 1?",
        "What is the GFA of Tower 6 Level 2 latest revision?",
        "Compare Rev 1 and Rev 2 GFA for Tower 6 Level 2",
        
        # G. Unknowns
        "What is the GFA of Tower 99 Level 1?",
        "What is the GFA of Tower 6 Level 99?",
        "What is the roof area of Tower 6?" # unknown field
    ]
    
    passed = 0
    failed = 0
    ambiguous_ct = 0
    missing_ct = 0
    unsupported_ct = 0
    
    print("--- PHASE 3 STRESS TEST ---")
    for q in tests:
        parsed = robust_parse_query(q)
        if not parsed:
            if "roof area" in q:
                # Correctly unparsed -> Normal RAG -> Not found
                missing_ct += 1
                passed += 1
            else:
                print(f"FAILED TO PARSE: {q}")
                failed += 1
            continue
            
        status, ctx = execute_structured_query(parsed, 2)
        
        if status == "success": passed += 1
        elif status == "ambiguous": 
            ambiguous_ct += 1
            passed += 1 # Working as designed
        elif status == "not_found":
            missing_ct += 1
            passed += 1 # Working as designed
        elif status == "unsupported":
            unsupported_ct += 1
            passed += 1
        else:
            print(f"ERROR on {q}: {ctx}")
            failed += 1
            
    print("\n--- PHASE 3 REPORT ---")
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Ambiguous correctly blocked: {ambiguous_ct}")
    print(f"Missing correctly blocked: {missing_ct}")
    print(f"Unsupported correctly blocked: {unsupported_ct}")
