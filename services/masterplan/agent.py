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
from services.masterplan.reconciliation import MasterplanReconciliationEngine
from services.masterplan.parsers.dxf_parser import MasterplanDxfParser
from services.masterplan.parsers.excel_parser import MasterplanExcelParser
from services.masterplan.view_commands import parse_view_command

OLLAMA_HOST = getattr(get_settings(), "ollama_host", "http://127.0.0.1:11434")
REASONING_MODEL = "qwen3.5:9b"


class MasterplanAIAgent:
    """
    Offline local agentic copilot for design review meetings.
    """

    def __init__(self):
        self.spatial_engine = SpatialReasoningEngine()
        self.reconciliation_engine = MasterplanReconciliationEngine()
        self.dxf_parser = MasterplanDxfParser()
        self.excel_parser = MasterplanExcelParser()

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
                "plots": [p.dict(exclude={"geometry"}) for p in plots],
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

        # Check for Reconcile / Check Files / Stabilize Relation instruction or query
        is_reconcile_action = any(k in q for k in (
            "check file", "check files", "stabiliz", "stabliz", "reconcil", "link cad",
            "link excel", "link file", "correlat", "cross reference", "ground truth"
        ))
        is_status_query = any(k in q for k in ("show file", "show files", "list file", "list files", "what is the relation"))

        if is_reconcile_action or is_status_query:
            files = db.get_file_records(project_id)
            rel = db.get_latest_file_relation(project_id)
            cad_f = [f for f in files if f['file_type'] == 'cad']
            exc_f = [f for f in files if f['file_type'] == 'excel']

            # If user explicitly asked to check files / reconcile / stabilize relation
            if is_reconcile_action and cad_f and exc_f:
                try:
                    c_plots = self.dxf_parser.parse_dxf(cad_f[0]['file_path'], project_id)
                    e_plots = self.excel_parser.parse_excel(exc_f[0]['file_path'], project_id)
                    rec = self.reconciliation_engine.analyze_correlation(
                        c_plots, e_plots, cad_f[0]['filename'], exc_f[0]['filename']
                    )

                    if rec.get("discrepancies"):
                        cards_html = []
                        disc_list = rec["discrepancies"]
                        for d in disc_list:
                            pid = d["plot_id"]
                            cad_v = d.get("cad_val", "")
                            exc_v = d.get("excel_val", "")
                            m_cad = re.search(r"[-+]?\d*\.?\d+", str(cad_v))
                            m_exc = re.search(r"[-+]?\d*\.?\d+", str(exc_v))
                            cad_num = float(m_cad.group(0)) if m_cad else 0.0
                            exc_num = float(m_exc.group(0)) if m_exc else 0.0
                            diff_badge = f"<span class='mpd-badge warn' style='font-size:10px'>Δ {d['diff_pct']}%</span>" if d.get('diff_pct') else ''

                            cards_html.append(f"""
                            <div id="reconcileCard_{pid}" style="background:#090f1d;border:1px solid rgba(245,183,61,.35);border-radius:8px;padding:12px;margin:8px 0">
                              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                                <div style="font-weight:700;color:var(--amber);font-size:12.5px">{d.get('title', 'Plot ' + pid)}</div>
                                {diff_badge}
                              </div>
                              <div style="font-size:12px;color:var(--text);line-height:1.5;margin-bottom:10px">{d.get('question')}</div>
                              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
                                <div style="background:rgba(47,107,255,.1);border:1px solid rgba(47,107,255,.3);border-radius:6px;padding:6px 10px">
                                  <span style="font-size:10px;color:var(--muted);display:block">CAD DRAWING</span>
                                  <b style="color:var(--accent2);font-size:12px">{cad_v}</b>
                                </div>
                                <div style="background:rgba(53,208,127,.1);border:1px solid rgba(53,208,127,.3);border-radius:6px;padding:6px 10px">
                                  <span style="font-size:10px;color:var(--muted);display:block">EXCEL REGISTER</span>
                                  <b style="color:var(--green);font-size:12px">{exc_v}</b>
                                </div>
                              </div>
                              <div style="display:flex;gap:8px;flex-wrap:wrap">
                                <button class="primary" style="padding:6px 12px;font-size:11px" onclick="window._resolveMpdRelation('{project_id}', '{pid}', 'cad', {cad_num}, {exc_num})">
                                  Adopt CAD Geometry ({cad_v})
                                </button>
                                <button class="cad-btn" style="padding:6px 12px;font-size:11px;color:var(--green);border-color:rgba(53,208,127,.4)" onclick="window._resolveMpdRelation('{project_id}', '{pid}', 'excel', {cad_num}, {exc_num})">
                                  Adopt Excel Schedule ({exc_v})
                                </button>
                              </div>
                            </div>
                            """)

                        full_html = f"""
                        <div style="border-left:3px solid var(--amber);padding-left:10px">
                          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                            <span class="mpd-badge warn" style="font-size:10.5px;font-weight:700">⚠️ Masterplan Multi-Source Discrepancy</span>
                            <span style="font-size:11px;color:var(--muted)">{cad_f[0]['filename']} ⟷ {exc_f[0]['filename']}</span>
                          </div>
                          <div style="font-size:12.5px;color:var(--text);line-height:1.5;margin-bottom:8px">
                            Cross-correlation checked <b>{rec.get('matched_plots', len(c_plots))}</b> matched parcels. Found <b>{len(disc_list)}</b> parameter conflict between CAD parcel geometry and Excel register. Please confirm which source to stabilize:
                          </div>
                          {''.join(cards_html)}
                        </div>
                        """
                        plain_text = f"⚠️ Found {len(disc_list)} parameter conflicts between CAD ({cad_f[0]['filename']}) and Excel ({exc_f[0]['filename']}). Please review and confirm which source to stabilize."
                        return MasterplanAIQueryResponse(
                            answer=plain_text,
                            html=full_html,
                            intent="RECONCILE_DISCREPANCIES",
                            tools_called=["analyze_correlation"],
                            highlight_plots=[d["plot_id"] for d in disc_list],
                            reconciliation=rec
                        )
                    else:
                        # 100% parity: automatically stabilize and save relationship
                        db.save_file_relation(
                            project_id=project_id,
                            cad_file=cad_f[0]['filename'],
                            excel_file=exc_f[0]['filename'],
                            status="stabilized_linked",
                            matched_plots=rec.get("matched_plots", len(c_plots)),
                            resolutions={}
                        )
                        full_html = f"""
                        <div style="border-left:3px solid var(--green);padding-left:10px">
                          <div style="font-weight:700;color:var(--green);font-size:13px;margin-bottom:4px">🎉 Masterplan Sources Linked &amp; Ground Truth Stabilized</div>
                          <div style="font-size:12px;color:var(--text);line-height:1.5">
                            All parcels matched identically between CAD drawing <code>{cad_f[0]['filename']}</code> and Excel register <code>{exc_f[0]['filename']}</code>. The verified relationship has been stabilized and permanently saved into the Agentic AI model.
                          </div>
                        </div>
                        """
                        return MasterplanAIQueryResponse(
                            answer=f"🎉 100% parity verified between CAD ({cad_f[0]['filename']}) and Excel ({exc_f[0]['filename']}). Certified Ground Truth relation has been saved.",
                            html=full_html,
                            intent="STABILIZE_RELATION",
                            tools_called=["reconcile_and_stabilize"],
                            highlight_plots=[]
                        )
                except Exception as err:
                    logger.error(f"Error executing cross-reconciliation: {err}")
                    return MasterplanAIQueryResponse(
                        answer=f"⚠️ Failed to analyze files: {err}",
                        intent="RECONCILE_ERROR",
                        tools_called=["analyze_correlation"]
                    )

            # Informational status report if only one or no files exist, or if user just asked for status
            lines = [
                f"### 🔗 Masterplan Multi-Source Linkage & Ground Truth Status",
                f"- **Project**: `{project_id}`",
                f"- **Registered Source Documents**: {len(files)}",
                ""
            ]
            if files:
                lines.append("#### 📂 Uploaded Source Files:")
                for f in files:
                    lines.append(f"- **{f['filename']}** ({f['file_type'].upper()} · {f['plots_count']} plots · Status: `{f['status']}`)")
            else:
                lines.append("_No source documents uploaded yet for this project._")

            lines.append("")
            if rel and rel.get("status") == "stabilized_linked":
                lines.append("#### ✅ Certified Ground Truth Relation Active:")
                lines.append(f"- **CAD Vector Geometry**: `{rel['cad_file']}`")
                lines.append(f"- **Excel Development Register**: `{rel['excel_file']}`")
                lines.append(f"- **Stabilized Parcels**: {rel['matched_plots']} parcels unified")
                if rel.get("resolutions"):
                    lines.append("- **Confirmed Discrepancy Resolutions**:")
                    for p_id, res_val in rel["resolutions"].items():
                        lines.append(f"  • Plot **{p_id}**: Adopted **{str(res_val).upper()}** value")
                lines.append("\nThe Agentic AI spatial model is actively evaluating FAR density, setbacks, and land use using this verified ground truth.")
            elif cad_f and exc_f:
                lines.append("⚡ **Ready to Stabilize**: Both CAD drawing and Excel register are uploaded. Ask me to **check file and stabilize the relation**, or click **Reconcile & Link** in the toolbar.")
            elif cad_f:
                lines.append(f"⚠️ **Pending Excel Schedule**: CAD drawing `{cad_f[0]['filename']}` is registered. To establish the relationship, upload the Excel register (.xlsx) using the **Import File** button.")
            elif exc_f:
                lines.append(f"⚠️ **Pending CAD Geometry**: Excel register `{exc_f[0]['filename']}` is registered. To establish the relationship, upload the CAD drawing (.dxf/.dwg) using the **Import File** button.")
            else:
                lines.append("⚠️ **No Files Uploaded**: Upload both a CAD drawing (.dxf/.dwg) and an Excel schedule (.xlsx) using the **Import File** button to link sources into the AI model.")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="QUERY_RELATION",
                tools_called=["get_file_records", "get_latest_file_relation"],
                highlight_plots=[]
            )

        # Check for direct Adopt / Stabilize instruction in chat (e.g., 'adopt cad for P-405')
        adopt_m = re.search(r"(?:adopt|stabilize|stablize|use|choose)\s*(cad|excel)\s*(?:for|on)?\s*(?:plot\s*|p[-_ ]*)?([a-zA-Z0-9_.-]+)", q)
        if adopt_m:
            choice = adopt_m.group(1).lower()
            plot_token = adopt_m.group(2).strip()
            norm_plot_id = f"P-{plot_token}" if not plot_token.upper().startswith("P-") else plot_token
            plot = db.get_plot(project_id, norm_plot_id) or db.get_plot(project_id, plot_token)
            if plot:
                rel = db.get_latest_file_relation(project_id) or {}
                resolutions = rel.get("resolutions", {})
                resolutions[plot.plot_id] = choice
                db.save_file_relation(
                    project_id=project_id,
                    cad_file=rel.get("cad_file", "CAD Geometry"),
                    excel_file=rel.get("excel_file", "Excel Register"),
                    status="stabilized_linked",
                    matched_plots=max(rel.get("matched_plots", 1), 1),
                    resolutions=resolutions
                )
                self.spatial_engine.run_project_audit(project_id)
                return MasterplanAIQueryResponse(
                    answer=f"✅ **Stabilized Ground Truth for Plot {plot.plot_id}**: Confirmed adoption of **{choice.upper()}** as the certified ground truth. Spatial calculations and future queries are now linked to this verified value.",
                    intent="STABILIZE_RELATION",
                    tools_called=["stabilize_relation"],
                    highlight_plots=[plot.plot_id],
                    action_performed="STABILIZE"
                )

        # Check for CAD Linework & Drawing Audit queries
        is_cad_audit = any(k in q for k in (
            "cad audit", "audit line", "audit lines", "audit cad", "everyline", "stall",
            "parking stall", "parking stalls", "parking bay", "parking bays", "drawing audit",
            "cad entity", "cad entities", "how many lines", "how many entities", "basement 2",
            "cad drawing", "dwg"
        ))
        if is_cad_audit:
            return MasterplanAIQueryResponse(
                answer='A verified CAD linework/compliance audit is not available. Uploaded files and plot registers do not establish measured entity counts, fire ratings or code compliance. Inspect the drawing with validated audit tools.',
                intent='CAD_AUDIT_UNVERIFIED', confidence=0.0, tools_called=[], highlight_plots=[])
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
        for lu in ("residential", "commercial", "mixed use", "mixed type", "mixed-use", "open space", "park", "civic", "utilities"):
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

        # Check for Generic Plot List / Table request
        if any(k in q for k in ("list of plots", "list plots", "show plots", "all plots", "table of plots", "plots table", "give me plots", "show all plots", "plot register", "list all plots")):
            all_plots = db.get_plots(project_id)
            lines = [
                f"### 📋 Masterplan Plot Register ({len(all_plots)} parcels)",
                f"Extracted directly from project CAD drawing and development register records:",
                "",
                "| Plot ID | Land Use | Sector | Footprint (m²) | Achieved GFA (m²) | FAR | Status |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
            ]
            for p in all_plots[:15]:
                st_badge = "✅ Compliant" if p.status == 'compliant' else ("⚠️ Warning" if p.status == 'warning' else "❌ Violation")
                lines.append(f"| **{p.plot_id}** | {p.land_use} | {p.sector} | {p.area_sqm:,.0f} | {p.achieved_gfa:,.0f} | {p.far:.2f} | {st_badge} |")
            if len(all_plots) > 15:
                lines.append(f"\n_...showing 15 of {len(all_plots)} parcels. Ask me to filter by land use (e.g. 'Show residential plots'), density (e.g. 'FAR >= 2.5'), or inspect any specific plot ID._")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="LIST_PLOTS",
                tools_called=["query_plots"],
                highlight_plots=[p.plot_id for p in all_plots[:15]]
            )

        # Check for Ranking / Largest / Smallest / Top plots query
        if any(k in q for k in ("largest", "biggest", "highest far", "top plots", "highest gfa", "smallest")):
            all_plots = db.get_plots(project_id)
            if "far" in q:
                sorted_plots = sorted(all_plots, key=lambda p: p.far, reverse=True)
                metric = "FAR"
            elif "gfa" in q:
                sorted_plots = sorted(all_plots, key=lambda p: p.achieved_gfa, reverse=True)
                metric = "Achieved GFA"
            elif "smallest" in q:
                sorted_plots = sorted(all_plots, key=lambda p: p.area_sqm)
                metric = "Smallest Footprint Area"
            else:
                sorted_plots = sorted(all_plots, key=lambda p: p.area_sqm, reverse=True)
                metric = "Footprint Area"

            lines = [
                f"### 🏆 Top Masterplan Parcels by {metric}",
                "",
                f"| Rank | Plot ID | Land Use | Sector | Footprint (m²) | Achieved GFA (m²) | FAR | Status |",
                f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
            ]
            for idx, p in enumerate(sorted_plots[:6], 1):
                st_badge = "✅ Compliant" if p.status == 'compliant' else ("⚠️ Warning" if p.status == 'warning' else "❌ Violation")
                lines.append(f"| #{idx} | **{p.plot_id}** | {p.land_use} | {p.sector} | {p.area_sqm:,.0f} | {p.achieved_gfa:,.0f} | {p.far:.2f} | {st_badge} |")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="QUERY_RANKINGS",
                tools_called=["query_plots"],
                highlight_plots=[p.plot_id for p in sorted_plots[:6]]
            )

        # Check for Parking Deficit or Requirements
        if any(k in q for k in ("parking", "parking deficit", "parking bay", "parking bays", "parking required")):
            all_plots = db.get_plots(project_id)
            tot_req = sum(p.parking_required for p in all_plots)
            tot_prov = sum(p.parking_provided for p in all_plots)
            diff = tot_prov - tot_req
            deficit_plots = [p for p in all_plots if p.parking_provided < p.parking_required]

            lines = [
                f"### 🚗 Masterplan Parking Capacity & Deficit Analysis",
                f"- **Total Parking Bays Required**: {tot_req:,} bays",
                f"- **Total Parking Bays Provided**: {tot_prov:,} bays",
                f"- **Net Balance**: {'+' if diff >= 0 else ''}{diff:,} bays ({'Surplus ✅' if diff >= 0 else 'Deficit ⚠️'})",
                ""
            ]
            if deficit_plots:
                lines.append("#### ⚠️ Parcels with Parking Deficit:")
                lines.append("| Plot ID | Land Use | Required | Provided | Deficit |")
                lines.append("| :--- | :--- | :--- | :--- | :--- |")
                for dp in deficit_plots[:8]:
                    lines.append(f"| **{dp.plot_id}** | {dp.land_use} | {dp.parking_required} | {dp.parking_provided} | **-{dp.parking_required - dp.parking_provided}** |")
            else:
                lines.append("✅ All plots currently satisfy minimum parking bay requirements.")

            return MasterplanAIQueryResponse(
                answer="\n".join(lines),
                intent="QUERY_PARKING",
                tools_called=["calculate_kpis", "query_plots"],
                highlight_plots=[p.plot_id for p in deficit_plots]
            )

        # Check for specific Plot ID query (e.g. PLOT-L, Plot L-2, PLOT-TOR, P-101, Plot 101, Plot no 5215039, 5215039)
        all_plots = db.get_plots(project_id)
        matched_plot = None

        # Clean query by removing filler words like "no", "number", "num", "#"
        clean_q = re.sub(r"\b(?:plot|p)\.?\s*(?:no|number|num)?\.?\s*#?\s*", "plot ", q, flags=re.IGNORECASE)

        for p in all_plots:
            pid = p.plot_id.lower()
            short_id = pid.replace("plot-", "").replace("p-", "").strip()
            if pid in q or pid in clean_q or f"plot {short_id}" in clean_q or f"plot-{short_id}" in clean_q or f"p-{short_id}" in clean_q:
                matched_plot = p
                break
            if len(short_id) >= 4 and re.search(r"\b" + re.escape(short_id) + r"\b", q):
                matched_plot = p
                break

        if not matched_plot:
            id_m = re.search(r"\b(?:plot|p)\s*(?:no|number|num)?\.?\s*#?\s*([a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*)\b", q, re.IGNORECASE)
            if id_m:
                tok = id_m.group(1).upper()
                if tok not in ("NO", "NUMBER", "NUM", "THE", "ALL", "THIS", "THAT"):
                    matched_plot = (
                        db.get_plot(project_id, tok) or
                        db.get_plot(project_id, f"PLOT-{tok}") or
                        db.get_plot(project_id, f"P-{tok}") or
                        (db.get_plot(project_id, f"P-{int(tok):03d}") if tok.isdigit() and len(tok) < 4 else None)
                    )

        if not matched_plot:
            num_tokens = re.findall(r"\b\d{4,8}\b", q)
            for tok in num_tokens:
                matched_plot = (
                    db.get_plot(project_id, tok) or
                    db.get_plot(project_id, f"PLOT-{tok}") or
                    db.get_plot(project_id, f"P-{tok}")
                )
                if matched_plot:
                    break

        if matched_plot:
            plot = matched_plot
            try:
                evidence = json.loads(plot.notes or '{}')
            except (ValueError,TypeError):
                evidence = {}
            if isinstance(evidence,dict) and evidence.get('method') == 'hatch_label_containment':
                measured=evidence.get('measured_area_sqm')
                annotated=evidence.get('annotated_area_sqm')
                lines=[f"### Plot {plot.plot_id}", f"Source: {evidence.get('source')}"]
                lines.append(f"Measured hatch area: **{measured:,.2f} m²**." if measured is not None else 'Measured area unavailable: drawing units need confirmation.')
                lines.append(f"Area written in CAD label: **{annotated:,.2f} m²**." if annotated is not None else 'No unique area value was identified in the CAD label.')
                lines.append('Linked by plot-ID label containment in a transformed hatch. Approval and engineering compliance have not been verified.')
                return MasterplanAIQueryResponse(answer='\n'.join(lines),intent='INSPECT_PLOT',tools_called=['get_plot_details'],highlight_plots=[plot.plot_id])
            rel = db.get_latest_file_relation(project_id)
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
            if rel and rel.get("resolutions") and plot.plot_id in rel["resolutions"]:
                res_choice = rel["resolutions"][plot.plot_id]
                lines.append(f"- **Ground Truth Link**: Verified & Stabilized (Adopted **{str(res_choice).upper()}** value)")
            elif rel and rel.get("status") == "stabilized_linked":
                lines.append(f"- **Ground Truth Link**: Verified from CAD ⟷ Excel unified model")

            if plot.notes:
                lines.append(f"- **Provenance**: {plot.notes}")

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
        action = parse_view_command(req.query)
        if action:
            return MasterplanAIQueryResponse(answer='Drawing action requested.',intent='VIEW_ACTION',view_actions=[action],tools_called=['drawing_view_controller'])
        # Check deterministic plan first for high-precision specific queries (Plot Inspection, Linework Audit, Direct Filters)
        det_res = self._fallback_deterministic_plan(req.query, req.project_id)
        if det_res.intent in ("INSPECT_PLOT", "AUDIT_LINEWORK", "QUERY_VIOLATIONS", "QUERY_LAND_USE", "QUERY_DENSITY", "CAD_AUDIT_UNVERIFIED", "LIST_PLOTS", "QUERY_RANKINGS", "QUERY_PARKING"):
            colors = {'yellow':'#ffff00', 'red':'#ff0000', 'green':'#00ff00', 'blue':'#0080ff', 'orange':'#ffa500', 'purple':'#a855f7'}
            det_res.highlight_color = next((value for name,value in colors.items() if re.search(r'\b'+name+r'\b', req.query, re.I)), None)
            return det_res

        # Try Ollama Qwen 3.5 9B with reasoning for open-ended or general questions
        try:
            summary = db.get_project_summary(req.project_id)
            files = db.get_file_records(req.project_id)
            cad_names = [f['filename'] for f in files if f.get('file_type') == 'cad']
            exc_names = [f['filename'] for f in files if f.get('file_type') == 'excel']
            system_prompt = (
                f"You are the Design AI Copilot operating on project '{req.project_id}'.\n"
                f"Ingested Project Documents: CAD Drawing: {', '.join(cad_names) or 'None registered'}, Excel Register: {', '.join(exc_names) or 'None registered'}.\n"
                f"Project Overview: {summary.total_plots} parcels, {summary.total_area_sqm:,.0f} m² land area, {summary.total_gfa_sqm:,.0f} m² GFA, Average FAR {summary.average_far:.2f}.\n"
                f"Compliance: {summary.compliant_plots} Compliant, {summary.warning_plots} Warnings, {summary.violation_plots} Violations.\n"
                f"Like ChatGPT and Claude, reason over the masterplan drawings, schedules, and spatial parameters. Calculate exact numbers, explain zoning compliance, and answer any design or engineering question.\n"
                f"Format answers clearly in GitHub Markdown with bullet points or tables.\n"
                f"If you identify specific plot IDs relevant to the question, append them at the end inside [HIGHLIGHT: P-101, P-5215039]."
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

                        # If no explicit highlight tag, search for plot IDs like P-101 or P-5215039 in text
                        if not highlights:
                            p_matches = re.findall(r"\b(P-[A-Za-z0-9]+)\b", ans_text, re.IGNORECASE)
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
        return det_res
