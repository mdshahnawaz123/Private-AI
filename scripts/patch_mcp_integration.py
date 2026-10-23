import re
import os

path = r'C:\3EH\ExpoDesignAI - Copy\main.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

is_crlf = '\r\n' in text
nl = '\r\n' if is_crlf else '\n'

# 1. Include mcp_router
t1 = f"from routers.sandbox_status import router as sandbox_status_router{nl}app.include_router(sandbox_status_router)"
r1 = f"from routers.sandbox_status import router as sandbox_status_router{nl}app.include_router(sandbox_status_router){nl}from routers.mcp_routes import router as mcp_router{nl}app.include_router(mcp_router)"

if t1 in text:
    text = text.replace(t1, r1, 1)
    print("Replaced router registration successfully.")
else:
    print("Warning: router target not found")

# 2. Add MCP agent to ask_model
t2 = f"    from intelligence.model_answers import exact_model_answer, validate_model_prose{nl}    exact_answer = exact_model_answer(req.query, ctx, sel){nl}    if exact_answer is not None:{nl}        def exact_gen():{nl}            yield f\"data: {{json.dumps({{'type': 'token', 'text': exact_answer}})}}\\n\\n\"{nl}            yield f\"data: {{json.dumps({{'type': 'done'}})}}\\n\\n\"{nl}        return StreamingResponse(exact_gen(), media_type=\"text/event-stream\")"

mcp_lines = [
    "    # Direct MCP Bridge to Qwen AI Model: dynamic tool access to BIM model database",
    "    try:",
    "        from services.bim_mcp_bridge import run_qwen_mcp_agent",
    "        mcp_res = await run_qwen_mcp_agent(",
    "            project=req.project,",
    "            query=req.query,",
    "            context=ctx,",
    "            selection=sel,",
    "            chat_history=[{'role': getattr(m, 'role', 'user'), 'content': getattr(m, 'content', '')} for m in (req.messages or [])]",
    "        )",
    "        if mcp_res and mcp_res.get('answer'):",
    "            ans_text = mcp_res['answer']",
    "            v_action = mcp_res.get('viewer_action')",
    "            def mcp_gen():",
    "                yield f\"data: {json.dumps({'type': 'token', 'text': ans_text})}\\n\\n\"",
    "                if v_action and v_action.get('items'):",
    "                    yield f\"data: {json.dumps({'type': 'action', 'action': v_action.get('action'), 'items': v_action.get('items')[:5000]})}\\n\\n\"",
    "                try:",
    "                    structured = response_schema.build_structured_response(",
    "                        req.query, ans_text, [], subtitle_hint=\"3D model (MCP Bridge)\", focus_doc_used=False)",
    "                    yield f\"data: {json.dumps({'type':'structured','data':structured})}\\n\\n\"",
    "                except Exception as _e_rr:",
    "                    logger.warning('Response renderer build failed: {}', _e_rr)",
    "                yield f\"data: {json.dumps({'type': 'done'})}\\n\\n\"",
    "            return StreamingResponse(mcp_gen(), media_type='text/event-stream')",
    "    except Exception as _mcp_e:",
    "        logger.warning('MCP agent pass bypassed: {}', _mcp_e)",
]

mcp_block = nl.join(mcp_lines)
r2 = t2 + nl + nl + mcp_block

if t2 in text:
    text = text.replace(t2, r2, 1)
    print("Replaced ask_model MCP hook successfully.")
else:
    print("Warning: ask_model target not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patch complete.")
