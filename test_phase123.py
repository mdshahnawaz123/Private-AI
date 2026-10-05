import fitz
import json
import re

pdf_path = r"C:\3EH\ExpoDesignAI - Copy\data\docs\C3085 - 3EH -Expo Hills\Schedules\C3085-SCH-3EH6105-AR-0000001(5).pdf"
doc = fitz.open(pdf_path)

def normalize_number(text):
    if not text:
        return None
    # Remove commas
    t = text.replace(',', '').strip()
    try:
        if '.' in t:
            return float(t)
        return int(t)
    except:
        # Check if it has a percentage
        if t.endswith('%'):
            try:
                return float(t[:-1]) / 100.0
            except:
                pass
        return None

results = []

for page_num in range(doc.page_count):
    page = doc[page_num]
    tabs = page.find_tables()
    for t_idx, t in enumerate(tabs.tables):
        ext = t.extract()
        if not ext: continue
        
        # 1. Forward-fill `None` to reconstruct merged cells
        # We only forward fill vertically (from the row above)
        filled = []
        last_row = [None] * len(ext[0])
        for row in ext:
            new_row = []
            for col_idx, cell in enumerate(row):
                if cell is None:
                    new_row.append(last_row[col_idx])
                else:
                    new_row.append(cell)
            filled.append(new_row)
            last_row = new_row
            
        # 2. Identify the header row
        # A good heuristic: the row with the most text cells, or containing known keywords
        header_row_idx = -1
        for i, row in enumerate(filled):
            if any('LEVEL' in str(c).upper() for c in row if c) and any('GFA' in str(c).upper() for c in row if c):
                header_row_idx = i
                break
                
        if header_row_idx == -1:
            continue
            
        headers = [str(c).replace('\n', ' ').strip() if c else f"Col_{j}" for j, c in enumerate(filled[header_row_idx])]
        
        # 3. Extract data rows
        for i in range(header_row_idx + 1, len(filled)):
            row = filled[i]
            
            # Simple heuristic: if row[3] is a level and row[1] is a tower
            tower_val = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            level_val = str(row[3]).strip() if len(row) > 3 and row[3] else ""
            
            if not tower_val or not level_val.upper().startswith('LEVEL'):
                continue
                
            # Clean tower/level
            tower_match = re.search(r'TOWER\s*(\d+)', tower_val, re.I)
            tower_norm = tower_match.group(1) if tower_match else tower_val
            
            level_match = re.search(r'LEVEL\s*(\d+)', level_val, re.I)
            level_norm = level_match.group(1) if level_match else level_val
            
            for col_idx in range(4, len(row)):
                col_name = headers[col_idx]
                raw_val = str(row[col_idx]).strip() if row[col_idx] else ""
                if not raw_val or raw_val == '0' or raw_val == '-':
                    continue
                    
                val_norm = normalize_number(raw_val)
                unit = "sqm" if "(sqm)" in col_name.lower() else ("%" if "(%)" in col_name else "unit")
                
                # Clean field name
                field_clean = re.sub(r'\(.*?\)', '', col_name).strip()
                
                rec = {
                    "document_id": "C3085-SCH-3EH6105-AR-0000001(5).pdf",
                    "page": page_num + 1,
                    "table": f"Table_{t_idx+1}",
                    "tower": tower_norm,
                    "level": level_norm,
                    "field": field_clean,
                    "value": val_norm,
                    "unit": unit,
                    "raw_val": raw_val,
                    "raw_col": col_name
                }
                results.append(rec)

# Print Tower 6 Level 02 Floor GFA
for r in results:
    if r['tower'] == '6' and r['level'] == '02' and 'GFA' in r['field']:
        print("FOUND EXPECTED RECORD:")
        print(json.dumps(r, indent=2))
        
print(f"Total structured records parsed: {len(results)}")
