"""
Agent Runtime for Expo Design AI (Phase 6).

Controlled agent execution with:
- PLANNING → TOOL EXECUTION → OBSERVATION → VALIDATION → FINAL RESPONSE

Agents do NOT have unrestricted OS or database access.
The AI Orchestrator controls agent execution.
Agent actions are logged.
"""
import json
import time
import uuid
import datetime
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

from agents.tools import get_registry, ToolResult, ToolPermission


class AgentState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    OBSERVING = "observing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentStep:
    """A single step in agent execution."""
    step_number: int
    action: str  # plan, tool_call, observe, validate
    description: str = ""
    tool_name: str = ""
    tool_params: Dict[str, Any] = field(default_factory=dict)
    tool_result: Optional[ToolResult] = None
    timestamp: str = ""
    duration_ms: float = 0.0


@dataclass
class AgentRun:
    """A complete agent run."""
    run_id: str = ""
    agent_name: str = ""
    project_id: str = ""
    user: Optional[dict] = None
    query: str = ""
    state: AgentState = AgentState.IDLE
    steps: List[AgentStep] = field(default_factory=list)
    final_response: str = ""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    completed_at: str = ""
    total_duration_ms: float = 0.0
    success: bool = False
    error: str = ""


class Agent(ABC):
    """Base class for all agents."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._tool_registry = get_registry()

    @abstractmethod
    def plan(self, query: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan the steps to accomplish the task."""
        ...

    @abstractmethod
    def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """Execute a single step."""
        ...

    @abstractmethod
    def validate(self, results: List[ToolResult], context: Dict[str, Any]) -> bool:
        """Validate the results."""
        ...


class ComplianceAgent(Agent):
    """
    Code Compliance Agent.
    Checks project evidence against code requirements.
    """

    def __init__(self):
        super().__init__("compliance_agent", "Checks compliance against building codes")

    def plan(self, query: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan compliance check steps."""
        steps = []
        project_id = context.get("project_id", "default")

        # Step 1: Search for relevant code requirements
        steps.append({
            "action": "tool_call",
            "tool_name": "search_code",
            "params": {"query": query, "limit": 5},
            "description": "Search for relevant code requirements",
        })

        # Step 2: Get project evidence
        steps.append({
            "action": "tool_call",
            "tool_name": "search_knowledge",
            "params": {"query": query, "limit": 10},
            "description": "Get project evidence",
        })

        # Step 3: Run compliance rules
        steps.append({
            "action": "tool_call",
            "tool_name": "run_rule",
            "params": {"rule_id": "DOOR-MIN-WIDTH", "actual_value": 0},
            "description": "Run compliance rules",
        })

        return steps

    def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """Execute a single step."""
        tool_name = step.get("tool_name", "")
        params = step.get("params", {})
        return self._tool_registry.execute(tool_name, params, user=context.get("user"))

    def validate(self, results: List[ToolResult], context: Dict[str, Any]) -> bool:
        """Validate that all steps completed successfully."""
        return all(r.success for r in results)


class DrawingQAAgent(Agent):
    """
    Drawing QA Agent.
    Reviews drawings for issues and compliance.
    """

    def __init__(self):
        super().__init__("drawing_qa_agent", "Reviews drawings for quality and compliance")

    def plan(self, query: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan drawing QA steps."""
        steps = []

        # Step 1: Get drawing
        steps.append({
            "action": "tool_call",
            "tool_name": "get_drawing",
            "params": {"drawing_id": context.get("drawing_id", "")},
            "description": "Get drawing metadata",
        })

        # Step 2: Analyze drawing
        steps.append({
            "action": "tool_call",
            "tool_name": "measure_geometry",
            "params": {"element_id": context.get("element_id", ""), "measurement_type": "length"},
            "description": "Measure drawing geometry",
        })

        # Step 3: Check compliance
        steps.append({
            "action": "tool_call",
            "tool_name": "run_rule",
            "params": {"rule_id": "DOOR-MIN-WIDTH", "actual_value": 0},
            "description": "Check compliance",
        })

        return steps

    def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """Execute a single step."""
        tool_name = step.get("tool_name", "")
        params = step.get("params", {})
        return self._tool_registry.execute(tool_name, params, user=context.get("user"))

    def validate(self, results: List[ToolResult], context: Dict[str, Any]) -> bool:
        """Validate results."""
        return all(r.success for r in results)


class KnowledgeAgent(Agent):
    """
    Knowledge Agent.
    Searches and retrieves information from the knowledge hub.
    """

    def __init__(self):
        super().__init__("knowledge_agent", "Searches and retrieves engineering knowledge")

    def plan(self, query: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan knowledge search steps."""
        steps = []

        # Step 1: Search knowledge hub
        steps.append({
            "action": "tool_call",
            "tool_name": "search_knowledge",
            "params": {"query": query, "limit": 10},
            "description": "Search knowledge hub",
        })

        # Step 2: Search code
        steps.append({
            "action": "tool_call",
            "tool_name": "search_code",
            "params": {"query": query, "limit": 5},
            "description": "Search building codes",
        })

        return steps

    def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """Execute a single step."""
        tool_name = step.get("tool_name", "")
        params = step.get("params", {})
        return self._tool_registry.execute(tool_name, params, user=context.get("user"))

    def validate(self, results: List[ToolResult], context: Dict[str, Any]) -> bool:
        """Validate results."""
        return any(r.success for r in results)


class AgentRuntime:
    """
    Controlled agent execution runtime.
    Manages the full agent lifecycle.
    """

    def __init__(self):
        self._agents: Dict[str, Agent] = {}
        self._runs: Dict[str, AgentRun] = {}
        self._register_default_agents()

    def _register_default_agents(self):
        """Register default agents."""
        self.register_agent(ComplianceAgent())
        self.register_agent(DrawingQAAgent())
        self.register_agent(KnowledgeAgent())

    def register_agent(self, agent: Agent):
        """Register an agent."""
        self._agents[agent.name] = agent
        logger.info("Registered agent: {} ({})", agent.name, agent.description)

    def get_agent(self, name: str) -> Optional[Agent]:
        """Get an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> List[Dict[str, str]]:
        """List all registered agents."""
        return [
            {"name": a.name, "description": a.description}
            for a in self._agents.values()
        ]

    def execute(self, agent_name: str, query: str,
                project_id: str = "default",
                user: Optional[dict] = None,
                context: Dict[str, Any] = None) -> AgentRun:
        """
        Execute an agent run.
        PLANNING → TOOL EXECUTION → OBSERVATION → VALIDATION → FINAL RESPONSE
        """
        agent = self._agents.get(agent_name)
        if not agent:
            return AgentRun(
                run_id=f"run-{uuid.uuid4().hex[:8]}",
                agent_name=agent_name,
                success=False,
                error=f"Unknown agent: {agent_name}",
            )

        context = context or {}
        context["project_id"] = project_id
        context["user"] = user

        run = AgentRun(
            run_id=f"run-{uuid.uuid4().hex[:8]}",
            agent_name=agent_name,
            project_id=project_id,
            user=user,
            query=query,
            state=AgentState.PLANNING,
            created_at=datetime.datetime.utcnow().isoformat(),
        )
        self._runs[run.run_id] = run

        start_time = time.time()

        try:
            # Step 1: PLANNING
            logger.info("[Agent {}] Starting planning phase", agent_name)
            plan = agent.plan(query, context)
            run.steps.append(AgentStep(
                step_number=0,
                action="plan",
                description=f"Planned {len(plan)} steps",
                timestamp=datetime.datetime.utcnow().isoformat(),
            ))

            # Step 2: TOOL EXECUTION + OBSERVATION
            run.state = AgentState.EXECUTING
            results = []
            for i, step_def in enumerate(plan):
                logger.info("[Agent {}] Executing step {}/{}", agent_name, i + 1, len(plan))
                step_start = time.time()

                result = agent.execute_step(step_def, context)
                results.append(result)

                run.steps.append(AgentStep(
                    step_number=i + 1,
                    action="tool_call",
                    description=step_def.get("description", ""),
                    tool_name=step_def.get("tool_name", ""),
                    tool_params=step_def.get("params", {}),
                    tool_result=result,
                    timestamp=datetime.datetime.utcnow().isoformat(),
                    duration_ms=(time.time() - step_start) * 1000,
                ))

            # Step 3: VALIDATION
            run.state = AgentState.VALIDATING
            is_valid = agent.validate(results, context)
            run.steps.append(AgentStep(
                step_number=len(plan) + 1,
                action="validate",
                description=f"Validation {'passed' if is_valid else 'failed'}",
                timestamp=datetime.datetime.utcnow().isoformat(),
            ))

            # Step 4: FINAL RESPONSE
            run.state = AgentState.COMPLETED
            run.success = is_valid
            run.final_response = f"Agent {agent_name} completed {len(plan)} steps"
            run.completed_at = datetime.datetime.utcnow().isoformat()
            run.total_duration_ms = (time.time() - start_time) * 1000

            logger.info("[Agent {}] Run completed: {} ({}ms)",
                        agent_name, "success" if is_valid else "failed",
                        run.total_duration_ms)

        except Exception as e:
            run.state = AgentState.FAILED
            run.success = False
            run.error = str(e)
            run.completed_at = datetime.datetime.utcnow().isoformat()
            run.total_duration_ms = (time.time() - start_time) * 1000
            logger.error("[Agent {}] Run failed: {}", agent_name, e)

        return run

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        """Get a run by ID."""
        return self._runs.get(run_id)

    def list_runs(self, project_id: str = "") -> List[AgentRun]:
        """List all runs, optionally filtered by project."""
        runs = list(self._runs.values())
        if project_id:
            runs = [r for r in runs if r.project_id == project_id]
        return runs


# Singleton instance
_runtime = AgentRuntime()


def get_runtime() -> AgentRuntime:
    """Get the global agent runtime instance."""
    return _runtime
