"""
Local Agentic AI Qwen 3.5 9B Engine for MPD (Masterplan Processing Division).
Implements Intent Parsing, Query Planning, Approved Tool Registry, and Spatial Reasoning.
"""
import os
import re
import json
import httpx
from typing import Dict, Any, List, Optional
from loguru import logger

from config import get_settings
from services.masterplan.models import MasterplanAIQueryRequest, MasterplanAIQueryResponse, MasterplanPlot
from services.masterplan import db
from services.masterplan.spatial_engine import SpatialReasoningEngine

OLLAMA_HOST = getattr(get_settings(), "ollama_host", "http://127.0.0.1:11434")
REASONING_MODEL = "qwen3.5:9b"


class MasterplanAIAgent:
    """
    Offline local agentic copilot for design review meetings.
    """

    def __init__(self):
        self.spatial_engine = SpatialReasoningEngine()

    def _execute_tool(self, tool_name: str, args: Dict[str, Any], project_id: str) -> Dict[str, Any]:
        """Approved Tool Registry execution."""
        if tool_name == "query_plots":
            plots = db.get_plots(
                project_id=project_id,
                land_use=args.get("land_use"),
                sector=args.get("sector"),
                status=args.get("status"),
                search=args.get("search")
            )
            min_far = args.get("min_far")
            max_far = args.get("max_far")
            if min_far is not None:
                plots = [p for p in plots if p.far >= float(min_far)]
            if max_far is not None:
                plots = [p for p in plots if p.far <= float(max_far)]
            return {
                "count": len(plots),
                "plots": [p.dict(exclude={"geometry"}) for p in plots[:25]],
                "plot_ids": [p.plot_id for p in plots]
            }

        elif tool_name == "get_plot_details":
            plot = db.get_plot(project_id, args.get("plot_id", ""))
            return {"plot": plot.dict() if plot else None}

        elif tool_name == "run_spatial_audit":
            res = self.spatial_engine.run_project_audit(project_id)
            return res

        elif tool_name == "calculate_kpis":
            summary = db.get_project_summary(project_id)
            return summary.dict()

        elif tool_name == "update_plot_parameter":
            plot_id = args.get("plot_id")
            field = args.get("field")
            val = args.get("value")
            reason = args.get("reason", "Design review adjustment")

            plot = db.get_plot(project_id, plot_id)
            if not plot:
                return {"error": f"Plot {plot_id} not found"}

            if hasattr(plot, field):
                setattr(plot, field, val)
                if field in ("achieved_gfa", "area_sqm"):
                    plot.far = round(plot.achieved_gfa / plot.area_sqm, 2) if plot.area_sqm > 0 else 0.0

                st, viols = self.spatial_engine.validate_plot(plot)
                plot.status = st
                plot.violations = viols
                db.save_plot(project_id, plot, author=f"AI Agent ({reason})")
                return {"status": "success", "plot": plot.dict(exclude={"geometry"})}
            return {"error": f"Invalid field: {field}"}

        elif tool_name == "undo_last_action":
            res = db.undo_last_audit(project_id)
            return res or {"message": "No actions to undo"}

        return {"error": f"Unknown tool: {tool_name}"}

    def _fallback_deterministic_plan(self, query: str, project_id: str) -> MasterplanAIQueryResponse:
        """
        Deterministic Intent Parser & Query Planner fallback.
        Ensures instantaneous sub-second response for standard design review queries.
        """
        q = query.lower()

        # Check for Undo request
        if "undo" in q or "revert" in q:
            res = self._execute_tool("undo_last_action", {}, project_id)
            msg = res.get("message", "Undo completed")
            return MasterplanAIQueryResponse(
                answer=f"🔄 **Audit Rollback**: {msg}",
                intent="UNDO_ACTION",
                tools_called=["undo_last_action"],
                highlight_plots=[res.get("plot_id")] if res.get("plot_id") else [],
                action_performed="UNDO"
            )

        # Check for Spatial Audit request
        if any(k in q for k in ("audit", "validate", "check compliance", "violations", "encroach")):
            audit_res = self._execute_tool("run_spatial_audit", {}, project_id)
            plots = db.get_plots(project_id)
            viol_plots = [p for p in plots if p.status == "violation"]
            warn_plots = [p for p in plots if p.status == "warning"]

            lines = [
                f"### 📋 Masterplan Spatial Compliance Audit Complete",
                f"- **Total Plots**: {len(plots)}",
                f"- **Compliant**: {len(plots) - len(viol_plots) - len(warn_plots)} ✅",
                f"- **Warnings**: {len(warn_plots)} ⚠️",
                f"- **Violations**: {len(viol_plots)} ❌",
                ""
            ]
            if viol_plots:
                lines.append("#### 🚨 Identified Non-Compliant Plots:")
                for vp in viol_plots:
                    lines.append(f"- **{vp.plot_id}** ({vp.land_use}, FAR: {vp.far:.2f}): {', '.join(vp.violations)}")
            if warn_plots:
                lines.append("\n#### ⚠️ Advisory Flags:")
                for wp in warn_plots:
                    lines.append(f"- **{wp.plot_id}** ({wp.land_use}): {', '.join(wp.violations)}")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="SPATIAL_AUDIT",
                tools_called=["run_spatial_audit"],
                highlight_plots=[p.plot_id for p in viol_plots + warn_plots],
                kpis=audit_res
            )

        # Check for FAR specific queries
        if "far" in q:
            match = re.search(r"(?:>|greater than|exceeding|above)\s*(\d*\.?\d+)", q)
            min_far = float(match.group(1)) if match else 2.5
            tool_res = self._execute_tool("query_plots", {"min_far": min_far}, project_id)
            plots = tool_res["plots"]
            pids = tool_res["plot_ids"]

            lines = [
                f"### 🏢 High Density FAR Analysis (FAR ≥ {min_far})",
                f"Found **{len(plots)}** plots meeting this density threshold in the masterplan:",
                ""
            ]
            for p in plots:
                lines.append(f"- **{p['plot_id']}** ({p['land_use']}, {p['sector']}): FAR **{p['far']:.2f}** (Achieved GFA: {p['achieved_gfa']:,.0f} m², Max Allowed FAR: {p['max_far']:.2f})")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="QUERY_DENSITY",
                tools_called=["query_plots"],
                highlight_plots=pids
            )

        # Check for Land Use breakdown or filters
        for lu in ("residential", "commercial", "mixed use", "open space", "park", "civic", "utilities"):
            if lu in q:
                norm_lu = "Residential" if "res" in lu else ("Commercial" if "com" in lu else ("Mixed Use" if "mix" in lu else ("Open Space / Park" if "park" in lu or "open" in lu else ("Civic" if "civ" in lu else "Utilities"))))
                tool_res = self._execute_tool("query_plots", {"land_use": norm_lu}, project_id)
                plots = tool_res["plots"]
                tot_gfa = sum(p["achieved_gfa"] for p in plots)
                tot_area = sum(p["area_sqm"] for p in plots)
                avg_far = (tot_gfa / tot_area) if tot_area > 0 else 0.0

                lines = [
                    f"### 📍 {norm_lu} Parcels Breakdown",
                    f"- **Total Parcels**: {len(plots)}",
                    f"- **Total Land Footprint**: {tot_area:,.1f} m²",
                    f"- **Total Achieved GFA**: {tot_gfa:,.1f} m²",
                    f"- **Effective FAR**: {avg_far:.2f}",
                    "",
                    "| Plot ID | Sector | Footprint (m²) | Achieved GFA (m²) | FAR | Status |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- |"
                ]
                for p in plots[:12]:
                    st_badge = "✅ Compliant" if p['status'] == 'compliant' else ("⚠️ Warning" if p['status'] == 'warning' else "❌ Violation")
                    lines.append(f"| **{p['plot_id']}** | {p['sector']} | {p['area_sqm']:,.0f} | {p['achieved_gfa']:,.0f} | {p['far']:.2f} | {st_badge} |")

                return MasterplanAIQueryResponse(
                    answer="\n".join(lines),
                    intent="QUERY_LAND_USE",
                    tools_called=["query_plots"],
                    highlight_plots=tool_res["plot_ids"]
                )

        # Check for specific Plot ID query (e.g. P-105, Plot 105)
        id_m = re.search(r"(?:P|PLOT)[-_ ]*(\d+)", q, re.IGNORECASE)
        if id_m:
            target_id = f"P-{id_m.group(1)}"
            plot = db.get_plot(project_id, target_id)
            if plot:
                lines = [
                    f"### 🎯 Detailed Inspection: Plot {plot.plot_id}",
                    f"- **Land Use**: {plot.land_use}",
                    f"- **Sector**: {plot.sector}",
                    f"- **Plot Footprint**: {plot.area_sqm:,.1f} m²",
                    f"- **Permitted GFA**: {plot.permitted_gfa:,.1f} m² (Max FAR: {plot.max_far:.2f})",
                    f"- **Achieved GFA**: {plot.achieved_gfa:,.1f} m² (FAR: {plot.far:.2f})",
                    f"- **Building Height Envelope**: {plot.max_height} (Max Site Coverage: {plot.max_coverage_pct}%)",
                    f"- **Setback Buffers**: Front {plot.front_setback_m}m | Rear {plot.rear_setback_m}m | Side {plot.side_setback_m}m",
                    f"- **Parking**: {plot.parking_provided} bays provided vs {plot.parking_required} bays required",
                    f"- **Regulatory Status**: **{plot.status.upper()}**"
                ]
                if plot.violations:
                    lines.append(f"\n⚠️ **Violations / Notes**: {'; '.join(plot.violations)}")
                return MasterplanAIQueryResponse(
                    answer="\n".join(lines),
                    intent="INSPECT_PLOT",
                    tools_called=["get_plot_details"],
                    highlight_plots=[plot.plot_id]
                )

        # General KPI Summary
        kpis = self._execute_tool("calculate_kpis", {}, project_id)
        lines = [
            f"### 🌐 Expo Hills Masterplan Overview ({project_id})",
            f"- **Total Masterplan Area**: {kpis['total_area_sqm']:,.1f} m² ({kpis['total_area_sqm']/10000:.2f} Ha)",
            f"- **Total Plots**: {kpis['total_plots']}",
            f"- **Total Permitted GFA**: {kpis['total_gfa_sqm']:,.1f} m²",
            f"- **Average FAR**: {kpis['average_far']:.2f}",
            f"- **Compliance Summary**: {kpis['compliant_plots']} Compliant ✅ | {kpis['warning_plots']} Warnings ⚠️ | {kpis['violation_plots']} Violations ❌",
            "",
            "#### Land Use Distribution:"
        ]
        for lu, data in kpis.get("land_use_breakdown", {}).items():
            lines.append(f"- **{lu}**: {data['total_area_sqm']:,.0f} m² ({data['pct_area']}%) · {data['plot_count']} parcels")

        return MasterplanAIQueryResponse(
            answer="\n".join(lines),
            intent="MASTERPLAN_SUMMARY",
            tools_called=["calculate_kpis"],
            highlight_plots=[]
        )

    async def process_query(self, req: MasterplanAIQueryRequest) -> MasterplanAIQueryResponse:
        """
        Coordinates the Local Agentic AI Qwen 3.5 9B with Intent Parsing and Tool Execution.
        """
        # Try Ollama Qwen 3.5 9B with reasoning
        try:
            summary = db.get_project_summary(req.project_id)
            system_prompt = (
                f"You are the Masterplan AI Copilot (MPD) operating offline on Windows during an architectural and urban design review meeting.\n"
                f"Project: {req.project_id}.\n"
                f"Total Plots: {summary.total_plots}, Total GFA: {summary.total_gfa_sqm} m2, Average FAR: {summary.average_far}.\n"
                f"You analyze FAR, setbacks, zoning compliance, land use distribution, and parking ratios.\n"
                f"Answer clearly and concisely in GitHub Markdown with bullet points or tables.\n"
                f"If you identify specific plot IDs relevant to the question, list them at the end inside [HIGHLIGHT: P-101, P-102]."
            )

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                    json={
                        "model": REASONING_MODEL,
                        "prompt": req.query,
                        "system": system_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 700
                        }
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    ans_text = data.get("response", "").strip()
                    if ans_text:
                        # Extract any highlight markers
                        hl_match = re.search(r"\[HIGHLIGHT:\s*([^\]]+)\]", ans_text, re.IGNORECASE)
                        highlights = []
                        if hl_match:
                            highlights = [p.strip().upper() for p in hl_match.group(1).split(",") if p.strip()]
                            ans_text = re.sub(r"\[HIGHLIGHT:\s*[^\]]+\]", "", ans_text).strip()

                        # If no explicit highlight tag, search for plot IDs like P-101 in text
                        if not highlights:
                            p_matches = re.findall(r"\b(P-\d{3})\b", ans_text, re.IGNORECASE)
                            highlights = list(set(p.upper() for p in p_matches))

                        return MasterplanAIQueryResponse(
                            answer=ans_text,
                            intent="AGENTIC_REASONING_QWEN35",
                            tools_called=["qwen3.5_agent_reasoner"],
                            highlight_plots=highlights
                        )
        except Exception as exc:
            logger.debug(f"Ollama Qwen 3.5 9B direct query bypassed to deterministic plan: {exc}")

        # Deterministic Planner fallback
        return self._fallback_deterministic_plan(req.query, req.project_id)
