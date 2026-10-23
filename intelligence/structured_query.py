import project_db

import re
import json
import time
import db
import httpx


def classify_query(question):
    q = question.lower()
    
    # Exact document QA mapping
    doc_exact = ["gfa", "nsa", "nisa", "bua", "ga", "gross floor area", "net usable area", "consultant", "document", "report", "revision", "schedule", "tower", "calculation", "compare", "difference"]
    if any(k in q for k in doc_exact):
        return "DOCUMENT_QA"
        
    model_keywords = [
        "model", "element", "category", "categories", "storey", "level", "guid", "propert", "quantit",
        "wall", "door", "window", "slab", "beam", "column", "stair", "roof", "furniture",
        "highlight", "isolate", "zoom", "select", "this", "cross check",
        "find"
    ]
    
    if "this" in q or "selected" in q: return "MODEL_QA"
    if "isolate" in q or "highlight" in q or "zoom" in q or "search" in q or "cross check" in q: return "MODEL_QA"
    
    m_score = sum(1 for k in model_keywords if k in q)
    if m_score > 0: return "MODEL_QA"
    
    return "DOCUMENT_QA"

def execute_model_qa(question, project_id, call_qwen_func, user_context={}):
    import services.bim_service as bs
    service = bs.get_bim_service()
    
    t_start = time.perf_counter()
    resp = {
        "status": "SUCCESS", "question": question, "route": "model_qa", "answer": "",
        "data": {}, "calculation": {}, "provenance": [], "confidence": {"score": 1.0, "reason": "Controlled Model Tool"},
        "warnings": []
    }
    
    sel_guid = user_context.get("selected_guid", "") if user_context else ""
    sys_prompt = f"""
    You are routing a query to a BIM 3D model API.
    Available tools:
    - getModelInfo()
    - getStoreys()
    - getCategories()
    - countElements(category="", level="")
    - findElements(category="", level="", name="")
    - getElementProperties(guid="")
    - getQuantities(guid="")
    - getCrossCheck(query_type="", category="", level="", property="")
    
    Question: {question}
    Active Selection GUID: {sel_guid}
    
    Return EXACTLY a JSON object with:
    1. "tool" (string name)
    2. "args" (dictionary of arguments)
    3. "viewer_action" (string: "highlight", "isolate", "zoom", "select", "clear", or "none") based on what the user wants to do visually. If they just ask a question, default to "highlight". If they say clear/hide/reset, use "clear".
    
    Do not include markdown or other text.
    """
    
    try:
        if call_qwen_func:
            tool_json_str, _ = call_qwen_func(sys_prompt)
            tool_json_str = tool_json_str.strip()
            if tool_json_str.startswith("```json"): tool_json_str = tool_json_str[7:]
            if tool_json_str.endswith("```"): tool_json_str = tool_json_str[:-3]
            tool_req = json.loads(tool_json_str)
        else:
            return {"status": "ERROR", "answer": "LLM required for tool routing."}, 0
    except Exception as e:
        resp["status"] = "AMBIGUOUS"
        resp["answer"] = "I couldn't understand which model data you are asking for. Could you clarify?"
        return resp, time.perf_counter() - t_start
        
    tool = tool_req.get("tool")
    args = tool_req.get("args", {})
    action = tool_req.get("viewer_action", "highlight")
    
    if tool in ["getElementProperties", "getQuantities"] and not args.get("guid") and sel_guid:
        args["guid"] = sel_guid
        
    tool_result = None
    
    try:
        if tool == "getModelInfo": tool_result = service.get_stats(project_id)
        elif tool == "getStoreys": tool_result = service.get_element_count_by_level(project_id)
        elif tool == "getCategories": tool_result = service.get_element_count_by_class(project_id)
        elif tool == "countElements":
            cat = args.get("category", "").upper() if args.get("category") else ""
            if cat and not cat.startswith("IFC"): cat = "IFC" + cat.upper()
            els = service.query_elements(project_id, ifc_class=cat, level=args.get("level", ""))
            tool_result = {"count": len(els), "category": cat, "level": args.get("level", ""), "elements": [{"guid": e.get("guid")} for e in els[:100]]}
        elif tool == "findElements":
            cat = args.get("category", "").upper() if args.get("category") else ""
            if cat and not cat.startswith("IFC"): cat = "IFC" + cat.upper()
            els = service.query_elements(project_id, ifc_class=cat, level=args.get("level", ""))
            n = args.get("name", "").lower()
            if n: els = [e for e in els if n in str(e.get("name", "")).lower() or n in str(e.get("type_name", "")).lower()]
            tool_result = {"count": len(els), "elements": [{"guid": e.get("guid"), "name": e.get("name")} for e in els[:100]]}
        elif tool == "getElementProperties":
            el = service.get_element_by_guid(args.get("guid", ""), project_id)
            tool_result = el if el else {"error": "NOT_FOUND", "message": "Element not found."}
        elif tool == "getQuantities":
            el = service.get_element_by_guid(args.get("guid", ""), project_id)
            tool_result = el.get("dimensions", {}) if el else {"error": "NOT_FOUND", "message": "Element not found."}
        elif tool == "getCrossCheck":
            q_type = args.get("query_type", "")
            cat = args.get("category", "").upper() if args.get("category") else ""
            if cat and not cat.startswith("IFC"): cat = "IFC" + cat.upper()
            els = service.query_elements(project_id, ifc_class=cat, level=args.get("level", ""))
            
            if q_type == "count_by_level":
                counts = {}
                for e in els:
                    lvl = e.get("level") or "Unknown"
                    counts[lvl] = counts.get(lvl, 0) + 1
                tool_result = {"cross_check": "count_by_level", "category": cat, "result": counts}
            elif q_type == "area_by_category":
                total_area = 0.0
                for e in els:
                    dim = e.get("dimensions") or {}
                    area = dim.get("Area") or dim.get("GrossArea") or dim.get("NetArea")
                    if area:
                        try: total_area += float(area)
                        except Exception as e: pass
                tool_result = {"cross_check": "area_by_category", "category": cat, "total_area": total_area}
            elif q_type == "missing_property":
                prop = args.get("property", "").lower()
                missing = []
                for e in els:
                    # simplified check in dimensions and material
                    if prop not in str(e).lower():
                        missing.append({"guid": e.get("guid"), "name": e.get("name")})
                tool_result = {"cross_check": "missing_property", "property": prop, "count": len(missing), "elements": missing[:50]}
            else:
                tool_result = {"error": "NOT_FOUND", "message": f"Unsupported cross-check: {q_type}"}
        else:
            resp["status"] = "UNSUPPORTED"
            resp["answer"] = f"Tool {tool} is not supported."
            return resp, time.perf_counter() - t_start
    except Exception as e:
        resp["status"] = "ERROR"
        resp["answer"] = f"Tool execution failed: {e}"
        return resp, time.perf_counter() - t_start
        
    if isinstance(tool_result, dict) and tool_result.get("error") == "NOT_FOUND":
        resp["status"] = "NOT_FOUND"
        resp["answer"] = tool_result.get("message")
        return resp, time.perf_counter() - t_start
        
    resp["data"] = tool_result
    v_guids = []
    if tool_result.get("elements"):
        v_guids = [e.get("guid") for e in tool_result["elements"] if isinstance(e, dict) and e.get("guid")]
    elif tool_result.get("guid"):
        v_guids = [tool_result["guid"]]
    resp["viewer_action"] = {"action": action, "guids": v_guids}
    
    if call_qwen_func:
        ans_prompt = f"Question: {question}\nActive Selection GUID: {sel_guid}\nData: {json.dumps(tool_result)}\nProvide a short natural answer based ONLY on the Data. Do NOT invent numbers."
        ans, _ = call_qwen_func(ans_prompt)
        resp["answer"] = ans
    
    return resp, time.perf_counter() - t_start




def format_provenance(r):
    return {
        "document_id": getattr(r, "project_id", ""),
        "document_name": r.doc,
        "page": r.page,
        "table": r.schedule,
        "entity": f"Primary {r.tower} Secondary {r.level}",
        "field": r.field,
        "value": r.value,
        "unit": r.unit,
        "source_type": "structured_record",
        "confidence": getattr(r,'confidence','AMBIGUOUS'),
        "verification_status": "REVIEW_REQUIRED" if getattr(r,'source_type','')=='PDF_IMAGE' else "INTERPRETED"
    }

# Document QA uses ingestion's canonical, project-scoped records.
from intelligence.document_query import (
    call_local_model as call_qwen_safe,
    robust_parse_query,
    execute_structured_query,
    query_document,
)
