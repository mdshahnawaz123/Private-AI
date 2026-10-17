"""
ToolDesk: Model Capability Matrix and Tool Prerequisites Engine (Inspired by craft-ai-integrations).

Provides a formal capability matrix linking controlled tools (agents.tools) to AI model
profiles (core.model_registry). Verifies prerequisites (context window, multimodal inputs,
deterministic requirements, structured output support) and resolves automatic model fallbacks.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import threading

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class ToolPrerequisites:
    """
    Prerequisites required for an agent or execution engine to run a specific tool.
    Inspired by craft-ai-features ToolDesk specification.
    """
    required_capabilities: List[str] = field(default_factory=list)
    min_context_tokens: int = 4096
    input_modalities: List[str] = field(default_factory=lambda: ["text"])
    output_modalities: List[str] = field(default_factory=lambda: ["text"])
    deterministic: bool = False
    recommended_role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_capabilities": self.required_capabilities,
            "min_context_tokens": self.min_context_tokens,
            "input_modalities": self.input_modalities,
            "output_modalities": self.output_modalities,
            "deterministic": self.deterministic,
            "recommended_role": self.recommended_role,
        }


class ToolDesk:
    """
    Central Capability & Dispatch Matrix for Expo Design AI.
    Cross-references tools against model registry profiles to ensure:
    1. Zero model hallucination or crashes due to insufficient context length.
    2. Modality compatibility (vision, geometry, bim).
    3. Proper execution of deterministic rules without unnecessary LLM invocation.
    4. Deterministic fallback paths when preferred models are unavailable or busy.
    """

    def __init__(self, tool_registry=None, model_registry=None):
        self._tool_registry = tool_registry
        self._model_registry = model_registry
        self._lock = threading.Lock()

    @property
    def tool_registry(self):
        if self._tool_registry is None:
            from agents.tools import get_registry
            self._tool_registry = get_registry()
        return self._tool_registry

    @property
    def model_registry(self):
        if self._model_registry is None:
            from core.model_registry import get_registry
            self._model_registry = get_registry()
        return self._model_registry

    def check_model_support(self, tool_name: str, model_config) -> Dict[str, Any]:
        """
        Verify if a specific model profile satisfies all prerequisites of a tool.
        """
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {
                "supported": False,
                "reasons": [f"Tool '{tool_name}' not found in registry"],
                "token_headroom": 0,
                "matched_capabilities": [],
                "missing_capabilities": [],
            }

        prereq = getattr(tool, "prerequisites", None) or ToolPrerequisites()

        if prereq.deterministic:
            return {
                "supported": True,
                "reasons": ["Tool is deterministic engine; executes natively without LLM dependency"],
                "token_headroom": model_config.context_length if model_config else 0,
                "matched_capabilities": ["deterministic"],
                "missing_capabilities": [],
            }

        if not model_config:
            return {
                "supported": False,
                "reasons": ["No model profile provided"],
                "token_headroom": 0,
                "matched_capabilities": [],
                "missing_capabilities": list(prereq.required_capabilities),
            }

        reasons = []
        model_caps = set(getattr(model_config, "capabilities", []))
        req_caps = set(prereq.required_capabilities)

        matched = list(req_caps.intersection(model_caps))
        missing = list(req_caps.difference(model_caps))

        if missing:
            reasons.append(f"Missing required model capabilities: {missing}")

        ctx_length = getattr(model_config, "context_length", 0)
        token_headroom = ctx_length - prereq.min_context_tokens
        if token_headroom < 0:
            reasons.append(
                f"Insufficient context window: model provides {ctx_length} tokens, tool requires {prereq.min_context_tokens}"
            )

        # Modality checks
        model_modalities = set(getattr(model_config, "modalities", ["text"]))
        req_inputs = set(prereq.input_modalities)
        if "image" in req_inputs and "image" not in model_modalities and "vision" not in model_caps:
            reasons.append("Tool requires vision/image input modality, not supported by model")

        supported = len(reasons) == 0
        return {
            "supported": supported,
            "reasons": reasons,
            "token_headroom": token_headroom,
            "matched_capabilities": matched,
            "missing_capabilities": missing,
        }

    def get_capable_models(self, tool_name: str) -> List[Any]:
        """
        Return all registered and enabled models that meet the tool's prerequisites,
        sorted by priority (lower priority number = higher preference).
        """
        models = [m for m in self.model_registry._models.values() if m.enabled]
        capable = []
        for m in models:
            eval_res = self.check_model_support(tool_name, m)
            if eval_res["supported"]:
                capable.append(m)

        capable.sort(key=lambda m: getattr(m, "priority", 99))
        return capable

    def resolve_model_for_tool(self, tool_name: str, preferred_role: Optional[str] = None) -> Dict[str, Any]:
        """
        Resolves the optimal model for running a tool, checking prerequisites and falling back if necessary.
        """
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {
                "tool_name": tool_name,
                "status": "NOT_FOUND",
                "error": f"Tool '{tool_name}' is not registered",
                "selected_model": None,
                "selected_role": None,
                "fallback_used": False,
                "deterministic": False,
            }

        prereq = getattr(tool, "prerequisites", None) or ToolPrerequisites()

        if prereq.deterministic:
            return {
                "tool_name": tool_name,
                "status": "DETERMINISTIC_ONLY",
                "selected_model": None,
                "selected_role": None,
                "fallback_used": False,
                "deterministic": True,
                "reasons": ["Tool is deterministic engine; executed natively without model invocation."],
            }

        # 1. Check preferred role if explicitly requested
        target_role = preferred_role or prereq.recommended_role
        preferred_model = self.model_registry.get(target_role) if target_role else None
        
        if preferred_model and preferred_model.enabled:
            eval_res = self.check_model_support(tool_name, preferred_model)
            if eval_res["supported"]:
                return {
                    "tool_name": tool_name,
                    "status": "READY",
                    "selected_model": preferred_model.name,
                    "selected_role": preferred_model.role,
                    "fallback_used": False,
                    "deterministic": False,
                    "token_headroom": eval_res["token_headroom"],
                    "verification": eval_res,
                }

        # 2. Check fallback roles on the preferred model if defined
        if preferred_model and hasattr(preferred_model, "fallback_roles"):
            for f_role in preferred_model.fallback_roles:
                fb_model = self.model_registry.get(f_role)
                if fb_model and fb_model.enabled:
                    eval_fb = self.check_model_support(tool_name, fb_model)
                    if eval_fb["supported"]:
                        return {
                            "tool_name": tool_name,
                            "status": "FALLBACK_APPLIED",
                            "selected_model": fb_model.name,
                            "selected_role": fb_model.role,
                            "fallback_used": True,
                            "original_requested_role": target_role,
                            "deterministic": False,
                            "token_headroom": eval_fb["token_headroom"],
                            "verification": eval_fb,
                        }

        # 3. Search all registered models for the best capable candidate
        capable = self.get_capable_models(tool_name)
        if capable:
            best = capable[0]
            eval_best = self.check_model_support(tool_name, best)
            return {
                "tool_name": tool_name,
                "status": "FALLBACK_APPLIED" if preferred_role else "READY",
                "selected_model": best.name,
                "selected_role": best.role,
                "fallback_used": bool(preferred_role and preferred_role != best.role),
                "deterministic": False,
                "token_headroom": eval_best["token_headroom"],
                "verification": eval_best,
            }

        # 4. No capable model found
        return {
            "tool_name": tool_name,
            "status": "UNSATISFIED",
            "error": "No enabled model in registry satisfies all tool prerequisites",
            "selected_model": None,
            "selected_role": None,
            "fallback_used": False,
            "deterministic": False,
            "prerequisites": prereq.to_dict(),
        }

    def audit_matrix(self) -> Dict[str, Any]:
        """
        Produce a full cross-cutting matrix evaluation between all tools and models.
        """
        tools = self.tool_registry.list_tools()
        all_models = list(self.model_registry._models.values())
        
        matrix_rows = []
        supported_count = 0
        deterministic_count = 0

        for t_dict in tools:
            name = t_dict["name"]
            tool_obj = self.tool_registry.get(name)
            prereq = getattr(tool_obj, "prerequisites", None) or ToolPrerequisites()

            if prereq.deterministic:
                deterministic_count += 1
                supported_count += 1
                matrix_rows.append({
                    "tool": name,
                    "permission": tool_obj.permission.value if hasattr(tool_obj, "permission") else "unknown",
                    "deterministic": True,
                    "status": "READY_DETERMINISTIC",
                    "min_context_tokens": 0,
                    "required_capabilities": ["deterministic"],
                    "input_modalities": prereq.input_modalities,
                    "output_modalities": prereq.output_modalities,
                    "primary_role": "NATIVE_ENGINE",
                    "supported_by": ["NATIVE_ENGINE"],
                    "evaluations": {},
                })
                continue

            evals = {}
            capable_roles = []
            for m in all_models:
                m_eval = self.check_model_support(name, m)
                evals[m.role] = {
                    "model_name": m.name,
                    "supported": m_eval["supported"],
                    "reasons": m_eval["reasons"],
                    "token_headroom": m_eval["token_headroom"],
                }
                if m_eval["supported"] and m.enabled:
                    capable_roles.append(m.role)

            resolution = self.resolve_model_for_tool(name)
            is_supported = resolution["status"] in ("READY", "FALLBACK_APPLIED")
            if is_supported:
                supported_count += 1

            matrix_rows.append({
                "tool": name,
                "permission": tool_obj.permission.value if hasattr(tool_obj, "permission") else "unknown",
                "deterministic": False,
                "status": resolution["status"],
                "min_context_tokens": prereq.min_context_tokens,
                "required_capabilities": prereq.required_capabilities,
                "input_modalities": prereq.input_modalities,
                "output_modalities": prereq.output_modalities,
                "primary_role": resolution.get("selected_role"),
                "primary_model": resolution.get("selected_model"),
                "supported_by": capable_roles,
                "evaluations": evals,
            })

        total_tools = len(tools)
        coverage_pct = round((supported_count / total_tools * 100.0), 1) if total_tools > 0 else 0.0

        return {
            "summary": {
                "total_tools": total_tools,
                "total_models": len(all_models),
                "supported_tools": supported_count,
                "deterministic_tools": deterministic_count,
                "coverage_percentage": coverage_pct,
            },
            "matrix": matrix_rows,
        }


# Singleton instance
_tooldesk_instance = None
_tooldesk_lock = threading.Lock()


def get_tooldesk() -> ToolDesk:
    """Get the global ToolDesk instance."""
    global _tooldesk_instance
    if _tooldesk_instance is None:
        with _tooldesk_lock:
            if _tooldesk_instance is None:
                _tooldesk_instance = ToolDesk()
    return _tooldesk_instance
