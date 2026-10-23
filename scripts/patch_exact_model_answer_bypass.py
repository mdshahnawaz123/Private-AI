path = r'C:\3EH\ExpoDesignAI - Copy\main.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

is_crlf = '\r\n' in text
nl = '\r\n' if is_crlf else '\n'

target = f"    from intelligence.model_answers import exact_model_answer, validate_model_prose{nl}    exact_answer = exact_model_answer(req.query, ctx, sel){nl}    if exact_answer is not None:"
replacement = f"    from intelligence.model_answers import exact_model_answer, validate_model_prose, MISSING{nl}    exact_answer = exact_model_answer(req.query, ctx, sel){nl}    if exact_answer is not None and exact_answer != MISSING:"

assert target in text, "Target not found in main.py"
text = text.replace(target, replacement, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Successfully patched main.py to allow MCP bridge to handle queries when exact_answer == MISSING")
