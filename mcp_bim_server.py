"""Standalone Model Context Protocol (MCP) Server for Expo Design AI BIM Models.

Connects BIM 3D models (IFC SQLite indices, spatial structures, properties,
quantity takeoffs, and 3D viewer actions) directly to external MCP clients
(e.g., Claude Desktop, Antigravity, Cursor) or internal AI reasoning agents.

Transport:
    stdio: Standard stdio MCP transport for local desktop AI agents
    python mcp_bim_server.py
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from services.bim_mcp_bridge import (
    search_elements,
    get_element_details,
    spatial_summary,
    takeoff_summary,
    list_models,
    create_viewer_action,
    measure_distance,
    run_qwen_mcp_agent,
)
from services.ifc_index import connect

mcp = MCPServer("Expo BIM Model MCP Bridge")


@mcp.tool()
def bim_search_elements(
    project: str,
    keyword: str = "",
    ifc_class: str = "",
    storey: str = "",
    limit: int = 50
) -> dict:
    """Search elements in the BIM model database by keyword, class, or storey.
    Includes semantic expansion (e.g. 'plant' matches palms, trees, shrubs, canopies).
    Returns total count, breakdown by type, and sample elements with IDs and properties.
    """
    return search_elements(
        project=project,
        keyword=keyword,
        ifc_class=ifc_class,
        storey=storey,
        limit=limit
    )


@mcp.tool()
def bim_get_element_details(
    project: str = "",
    element_id: Optional[int] = None,
    guid: Optional[str] = None
) -> dict:
    """Get full properties, dimensions, elevations, and all property sets for a specific BIM element."""
    return get_element_details(
        project=project,
        element_id=element_id,
        guid=guid
    )


@mcp.tool()
def bim_spatial_summary(project: str) -> dict:
    """Get building spatial hierarchy: storeys, elevations, element counts, areas, and volumes per level."""
    return spatial_summary(project=project)


@mcp.tool()
def bim_takeoff_summary(
    project: str,
    group_by: str = "class",
    ifc_class: Optional[str] = None,
    storey: Optional[str] = None,
    keyword: Optional[str] = None
) -> dict:
    """Calculate quantity takeoff (QTO) aggregations grouped by class, type, storey, or material."""
    return takeoff_summary(
        project=project,
        group_by=group_by,
        ifc_class=ifc_class,
        storey=storey,
        keyword=keyword
    )


@mcp.tool()
def bim_list_models(project: str) -> dict:
    """List loaded IFC models in the project, element counts, and engineering disciplines."""
    return list_models(project=project)


@mcp.tool()
def bim_measure_distance(
    project: str,
    element_id_1: Optional[int] = None,
    element_id_2: Optional[int] = None,
    keyword_1: Optional[str] = None,
    keyword_2: Optional[str] = None
) -> dict:
    """Measure exact 3D Euclidean distance, horizontal distance, and elevation difference
    between two elements in the BIM model using real geometry (e.g. distance between two trees, columns, or doors).
    """
    return measure_distance(
        project=project,
        element_id_1=element_id_1,
        element_id_2=element_id_2,
        keyword_1=keyword_1,
        keyword_2=keyword_2
    )


@mcp.tool()
def bim_viewer_action(
    project: str,
    action: str,
    keyword: Optional[str] = None,
    ifc_class: Optional[str] = None,
    element_ids: Optional[List[int]] = None,
    color: Optional[str] = None
) -> dict:
    """Prepare a verified 3D viewer action (isolate, hide, show, color, reset, fit)
    with exact element step_ids resolved from the SQLite database.
    """
    return create_viewer_action(
        project=project,
        action=action,
        keyword=keyword,
        ifc_class=ifc_class,
        element_ids=element_ids,
        color=color
    )


@mcp.tool()
async def bim_ask_qwen(project: str, query: str) -> dict:
    """Ask Qwen 3.5 9B with direct MCP BIM tool access to reason over the model,
    search elements, compute takeoffs, and return verified answers + viewer actions.
    """
    return await run_qwen_mcp_agent(project=project, query=query)


@mcp.resource("bim://projects")
def list_indexed_projects() -> str:
    """List all projects indexed in the BIM database."""
    con = connect()
    try:
        cur = con.execute("SELECT DISTINCT project, COUNT(*) FROM elements GROUP BY project")
        projects = [{"project": r[0], "elements": r[1]} for r in cur.fetchall()]
        return json.dumps(projects, indent=2)
    finally:
        con.close()


@mcp.resource("bim://summary/{project}")
def get_project_resource(project: str) -> str:
    """Get project BIM summary resource."""
    summary = spatial_summary(project)
    models = list_models(project)
    return json.dumps({"spatial": summary, "models": models}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
