"""Local stdio MCP facade. Every action uses Expo's authenticated HTTP API.
No arbitrary code execution and no model-callable approval tool.
"""
import os
from pathlib import Path
from urllib.parse import urlparse
import httpx
try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

mcp=FastMCP('Expo Drawing to Blender')


def client():
    base=os.getenv('EXPO_API_URL','http://127.0.0.1:8090')
    parsed=urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('MCP bridge requires local Expo API')
    token=os.getenv('EXPO_API_TOKEN')
    if not token: raise ValueError('Set EXPO_API_TOKEN to your Expo login token; never include it in prompts')
    return httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},timeout=60)


def request(method,path,**kwargs):
    with client() as c:
        result=c.request(method,path,**kwargs)
        result.raise_for_status()
        return result.json()


def jid(value):
    import re
    if not re.fullmatch('[0-9a-f]{32}',value): raise ValueError('Invalid job ID')
    return value


@mcp.tool()
def blender_health() -> dict:
    """Check local Blender, model configuration and API key presence."""
    return request('GET','/api/blender/health')


@mcp.tool()
def create_pdf_model_job(relative_pdf:str,project:str,cloud_processing_confirmed:bool=False) -> dict:
    """Upload a PDF under EXPO_MCP_IMPORT_ROOT and start analysis. Requires user's cloud-processing authorization.
    Stops for human source/dimension review before building. Do not claim unknowns are resolved.
    """
    if not cloud_processing_confirmed: raise ValueError('User must authorize sending this drawing to OpenAI')
    configured=os.getenv('EXPO_MCP_IMPORT_ROOT')
    if not configured: raise ValueError('Configure EXPO_MCP_IMPORT_ROOT for a dedicated drawing folder')
    root=Path(configured).resolve(); path=(root/relative_pdf).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.pdf': raise ValueError('PDF outside import root')
    with path.open('rb') as stream:
        return request('POST','/api/blender/jobs',data={'project':project,'cloud_consent':'true'},
                       files={'file':(path.name,stream,'application/pdf')})


@mcp.tool()
def get_model_job(job_id:str) -> dict:
    """Observe progress, unknowns, source evidence, review and output state."""
    return request('GET',f'/api/blender/jobs/{jid(job_id)}')


@mcp.tool()
def revise_model_proposal(job_id:str,plan:dict,furniture:list[dict]) -> dict:
    """Submit evidence-backed corrections. Invalidates approval. Never remove unknowns by guessing."""
    return request('POST',f'/api/blender/jobs/{jid(job_id)}/revise',json={'plan':plan,'furniture':furniture})


@mcp.tool()
def build_approved_model(job_id:str) -> dict:
    """Build/render only after a human approved the exact review in Expo's UI."""
    return request('POST',f'/api/blender/jobs/{jid(job_id)}/build')


@mcp.tool()
def open_completed_model(job_id:str) -> dict:
    """Open the completed model in visible Blender on this computer when the user requests it."""
    return request('POST',f'/api/blender/jobs/{jid(job_id)}/open')


if __name__ == '__main__':
    mcp.run(transport='stdio')
