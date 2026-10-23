import re

path = r'C:\3EH\ExpoDesignAI - Copy\services\bim_mcp_bridge.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add lighting synonyms
synonym_addition = '''    "light": ["%light%", "%lighting%", "%luminaire%", "%lamp%"],
    "lights": ["%light%", "%lighting%", "%luminaire%", "%lamp%"],
    "street light": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "street lights": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "street lighting": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "lighting": ["%lighting%", "%luminaire%", "%light%"],
    "luminaire": ["%luminaire%"],
    "luminaires": ["%luminaire%"],
    "pole": ["%pole%", "%lighting_column%"],
    "poles": ["%pole%", "%lighting_column%"],
'''
target_syn = 'SYNONYM_MAP: Dict[str, List[str]] = {\n'
assert target_syn in text
text = text.replace(target_syn, target_syn + synonym_addition, 1)

# 2. Add lighting to CLASS_MAP
class_addition = '''    "light": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "lights": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "street light": ["IFCBUILDINGELEMENTPROXY"],
    "street lights": ["IFCBUILDINGELEMENTPROXY"],
    "street lighting": ["IFCBUILDINGELEMENTPROXY"],
    "lighting": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "luminaire": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
'''
target_class = 'CLASS_MAP: Dict[str, List[str]] = {\n'
assert target_class in text
text = text.replace(target_class, target_class + class_addition, 1)

# 3. Add multi-token search in search_elements
old_search_logic = '''        # Keyword matching with synonym expansion
        if kw:
            synonyms = SYNONYM_MAP.get(kw, [f"%{kw}%"])
            token_likes = synonyms if len(synonyms) > 1 else [f"%{kw}%"]
            like_clauses = []
            for t in token_likes:
                like_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                params.extend([t, t, t, t])
            where_clauses.append(f"({' OR '.join(like_clauses)})")'''

new_search_logic = '''        # Keyword matching with synonym expansion and multi-token fallback
        if kw:
            synonyms = SYNONYM_MAP.get(kw, [])
            if synonyms:
                like_clauses = []
                for t in synonyms:
                    like_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                    params.extend([t, t, t, t])
                where_clauses.append(f"({' OR '.join(like_clauses)})")
            else:
                tokens = [t for t in re.split(r'[\\s_,-]+', kw) if len(t) >= 2]
                if len(tokens) > 1:
                    token_clauses = []
                    for tok in tokens:
                        token_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                        params.extend([f"%{tok}%", f"%{tok}%", f"%{tok}%", f"%{tok}%"])
                    where_clauses.append(f"({' AND '.join(token_clauses)})")
                else:
                    like = f"%{kw}%"
                    where_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                    params.extend([like, like, like, like])'''

assert old_search_logic in text
text = text.replace(old_search_logic, new_search_logic, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print('Updated services/bim_mcp_bridge.py with lighting synonyms and multi-token search successfully.')
