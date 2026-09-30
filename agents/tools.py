"""
Controlled Tool Definitions for Expo Design AI (Phase 6).

Agents operate through controlled tools. Agents must NOT directly modify
files, databases or engineering models without explicit tool permissions.

Available tools:
- read_document()
- search_knowledge()
- search_code()
- get_drawing()
- get_bim_element()
- measure_geometry()
- query_ifc()
- query_revit()
- run_rule()
- calculate()
- create_finding()
- generate_report()
"""
import os
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class ToolPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


@dataclass
class ToolDefinition:
    """Definition of a controlled tool."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON schema
    permission: ToolPermission
    handler: Optional[Callable] = None
    enabled: bool = True


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_name: str
    success: bool
    data: Any = None
    error: str = ""
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """
    Registry of all available tools for agents.
    Tools are controlled and permission-checked.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register the default set of controlled tools."""

        # Read-only tools
        self.register(ToolDefinition(
            name="read_document",
            description="Read a document from the project knowledge base",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID or filename"},
                    "page": {"type": "integer", "description": "Page number (optional)"},
                },
                "required": ["document_id"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="search_knowledge",
            description="Search the engineering knowledge hub",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "entity_type": {"type": "string", "description": "Filter by entity type"},
                    "limit": {"type": "integer", "description": "Maximum results"},
                },
                "required": ["query"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="search_code",
            description="Search building code requirements",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "code": {"type": "string", "description": "Code identifier (DBC, IBC, etc.)"},
                    "discipline": {"type": "string", "description": "Discipline filter"},
                },
                "required": ["query"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="get_drawing",
            description="Get drawing metadata and content",
            parameters={
                "type": "object",
                "properties": {
                    "drawing_id": {"type": "string", "description": "Drawing ID or filename"},
                    "revision": {"type": "string", "description": "Specific revision"},
                },
                "required": ["drawing_id"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="get_bim_element",
            description="Get BIM element properties by GUID",
            parameters={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "description": "Element GUID"},
                    "ifc_class": {"type": "string", "description": "IFC class filter"},
                    "level": {"type": "string", "description": "Level filter"},
                },
                "required": ["guid"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="measure_geometry",
            description="Measure geometry from a drawing or model",
            parameters={
                "type": "object",
                "properties": {
                    "element_id": {"type": "string", "description": "Element to measure"},
                    "measurement_type": {"type": "string", "description": "Type: length, area, volume"},
                },
                "required": ["element_id", "measurement_type"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="query_ifc",
            description="Query IFC model data",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "IFC query"},
                    "model_id": {"type": "string", "description": "Model ID"},
                },
                "required": ["query"],
            },
            permission=ToolPermission.READ,
        ))

        self.register(ToolDefinition(
            name="run_rule",
            description="Run a deterministic compliance rule",
            parameters={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string", "description": "Rule identifier"},
                    "actual_value": {"type": "number", "description": "Value to check"},
                    "context": {"type": "object", "description": "Additional context"},
                },
                "required": ["rule_id", "actual_value"],
            },
            permission=ToolPermission.EXECUTE,
        ))

        self.register(ToolDefinition(
            name="calculate",
            description="Perform a calculation",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Mathematical expression"},
                    "variables": {"type": "object", "description": "Variable values"},
                },
                "required": ["expression"],
            },
            permission=ToolPermission.EXECUTE,
        ))

        # Write tools (require explicit permission)
        self.register(ToolDefinition(
            name="create_finding",
            description="Create a compliance finding",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Finding title"},
                    "description": {"type": "string", "description": "Finding description"},
                    "severity": {"type": "string", "description": "Severity: critical, high, medium, low"},
                    "status": {"type": "string", "description": "Status: PASS, FAIL, REVIEW"},
                    "evidence": {"type": "string", "description": "Supporting evidence"},
                },
                "required": ["title", "description"],
            },
            permission=ToolPermission.WRITE,
        ))

        self.register(ToolDefinition(
            name="generate_report",
            description="Generate a report",
            parameters={
                "type": "object",
                "properties": {
                    "report_type": {"type": "string", "description": "Type: compliance, review, etc."},
                    "project_id": {"type": "string", "description": "Project ID"},
                    "format": {"type": "string", "description": "Format: pdf, excel, word"},
                },
                "required": ["report_type", "project_id"],
            },
            permission=ToolPermission.WRITE,
        ))

    def register(self, tool: ToolDefinition):
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.info("Registered tool: {} (permission: {})", tool.name, tool.permission.value)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, permission: ToolPermission = None) -> List[Dict[str, Any]]:
        """List all tools, optionally filtered by permission."""
        tools = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            if permission and tool.permission != permission:
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "permission": tool.permission.value,
            })
        return tools

    def execute(self, name: str, parameters: Dict[str, Any],
                user: Optional[dict] = None) -> ToolResult:
        """
        Execute a tool with permission checking.
        """
        import time
        start = time.time()

        tool = self._tools.get(name)
        if not tool:
            return ToolResult(tool_name=name, success=False, error=f"Unknown tool: {name}")

        if not tool.enabled:
            return ToolResult(tool_name=name, success=False, error=f"Tool {name} is disabled")

        # Permission check
        if user and tool.permission in (ToolPermission.WRITE, ToolPermission.ADMIN):
            if user.get("role") not in ("admin", "lead"):
                return ToolResult(tool_name=name, success=False,
                                  error=f"Insufficient permissions for {name}")

        # Execute handler if registered
        if tool.handler:
            try:
                result = tool.handler(parameters, user=user)
                elapsed = (time.time() - start) * 1000
                return ToolResult(tool_name=name, success=True, data=result,
                                  execution_time_ms=elapsed)
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                return ToolResult(tool_name=name, success=False, error=str(e),
                                  execution_time_ms=elapsed)
        else:
            # No handler registered — return schema for agent to use
            return ToolResult(tool_name=name, success=True,
                              data={"message": f"Tool {name} available", "schema": tool.parameters},
                              execution_time_ms=(time.time() - start) * 1000)


# Singleton instance
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    return _registry
