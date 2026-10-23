"""HTTP & SSE endpoints for the BIM Model MCP Bridge.

Allows internal frontend clients, automated test suites, and remote agents
to discover tools, execute BIM MCP operations, and chat with Qwen 3.5 9B.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import auth
from services.bim_mcp_bridge import (
    BIM_MCP_TOOLS,
    dispatch_tool_call,
    run_qwen_mcp_agent,
)

router = APIRouter(prefix="/api/mcp", tags=["BIM MCP Bridge"])


class CallToolRequest(BaseModel):
    tool: str = Field(..., description="Tool name, e.g. 'bim_search_elements'")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments dictionary")


class McpChatRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)
    query: str = Field(..., min_length=1, max_length=4000)
    context: Optional[str] = Field(default="", max_length=50000)
    selection: Optional[str] = Field(default="", max_length=10000)
    messages: Optional[List[Dict[str, str]]] = Field(default_factory=list)


@router.get("/tools")
def list_tools(request: Request):
    """List all available BIM Model MCP tools and their JSON schemas."""
    return {"tools": BIM_MCP_TOOLS}


@router.post("/call")
def call_tool(body: CallToolRequest, request: Request):
    """Execute a BIM Model MCP tool directly."""
    project = body.arguments.get("project")
    if project:
        auth.require_project(request, project)
    result = dispatch_tool_call(body.tool, body.arguments)
    if "error" in result and not result.get("success", False):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/chat")
async def chat_with_mcp(body: McpChatRequest, request: Request):
    """Chat with Qwen 3.5 9B equipped with direct MCP BIM Model tools."""
    auth.require_project(request, body.project)
    try:
        res = await run_qwen_mcp_agent(
            project=body.project,
            query=body.query,
            context=body.context or "",
            selection=body.selection or "",
            chat_history=body.messages or []
        )
        return {
            "status": "ok",
            "answer": res.get("answer", ""),
            "tool_calls_executed": res.get("tool_calls_executed", []),
            "viewer_action": res.get("viewer_action")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MCP Qwen agent failed: {e}")
