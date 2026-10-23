"""
Autonomous Python Code Interpreter Engine for Masterplan AI.
Enables Local Qwen 3.5 9B to act like ChatGPT / Claude Code Interpreter:
Autonomously writing, executing, and evaluating Python scripts against the
in-memory masterplan dataset (`plots_df`) behind the scenes without manual regex or hardcoded rules.
"""
import os
import re
import ast
import json
import math
import httpx
import pandas as pd
import numpy as np
import threading
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger

from config import get_settings

OLLAMA_HOST = getattr(get_settings(), "ollama_host", "http://127.0.0.1:11434")
CODE_MODEL = "qwen3.5:9b"
_EXECUTION_SLOTS = threading.BoundedSemaphore(2)


def build_plots_df(plots: list) -> pd.DataFrame:
    """Converts a list of MasterplanPlot objects into a rich Pandas DataFrame for Code Interpreter analysis."""
    records = []
    for p in plots:
        cx = p.geometry.centroid[0] if (p.geometry and p.geometry.centroid) else 0.0
        cy = p.geometry.centroid[1] if (p.geometry and p.geometry.centroid) else 0.0
        records.append({
            "plot_id": p.plot_id,
            "sector": p.sector or "",
            "land_use": p.land_use or "",
            "area_sqm": float(p.area_sqm or 0.0),
            "permitted_gfa": float(p.permitted_gfa or 0.0),
            "achieved_gfa": float(p.achieved_gfa or 0.0),
            "far": float(p.far or 0.0),
            "max_far": float(p.max_far or 0.0),
            "max_coverage_pct": float(p.max_coverage_pct or 0.0),
            "front_setback_m": float(p.front_setback_m or 0.0),
            "rear_setback_m": float(p.rear_setback_m or 0.0),
            "side_setback_m": float(p.side_setback_m or 0.0),
            "parking_required": int(p.parking_required or 0),
            "parking_provided": int(p.parking_provided or 0),
            "status": p.status or "compliant",
            "x": cx,
            "y": cy,
        })
    return pd.DataFrame(records)


def extract_python_code(raw_text: str) -> str:
    """Extracts executable Python code from LLM response markdown."""
    text = raw_text.strip()
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # If no markdown blocks, check if raw text looks like python code
    lines = [ln for ln in text.splitlines() if not ln.startswith("#") and ln.strip()]
    if any("=" in ln or "plots_df" in ln or "result" in ln for ln in lines):
        return text
    return ""


def execute_sandboxed_code(code_str: str, plots_df: pd.DataFrame) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not _EXECUTION_SLOTS.acquire(blocking=False):
        return None, 'Isolated MPD workers are busy; retry shortly'
    try:
        return _execute_code_in_container(code_str, plots_df)
    finally:
        _EXECUTION_SLOTS.release()


def _execute_code_in_container(code_str: str, plots_df: pd.DataFrame) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run MPD code in the same bounded container as Cowork; never on the host.

    Only a disposable dataset and trusted runner are staged. Missing container
    prerequisites return an error rather than weakening isolation.
    """
    from pathlib import Path
    import tempfile
    from services.container_sandbox import run_code_in_container

    if not isinstance(code_str, str) or len(code_str.encode("utf-8")) > 65536:
        return None, "Masterplan code exceeds the 64 KB limit"
    try:
        payload = json.dumps({"code": code_str, "plots": plots_df.to_dict(orient="records")
                              if plots_df is not None else []})
        if len(payload.encode("utf-8")) > 8 * 1024 * 1024:
            return None, "Masterplan input exceeds the 8 MB limit"
        with tempfile.TemporaryDirectory(prefix="expo-mpd-task-") as directory:
            stage = Path(directory)
            (stage / "job.json").write_text(payload, encoding="utf-8")
            runner = Path(__file__).with_name("interpreter_runner.py").read_text(encoding="utf-8")
            (stage / "interpreter_runner.py").write_text(runner, encoding="utf-8")
            bootstrap = ("import runpy, sys\n"
                         "sys.argv = ['/input/interpreter_runner.py', '/input/job.json']\n"
                         "runpy.run_path('/input/interpreter_runner.py', run_name='__main__')\n")
            outcome = run_code_in_container(bootstrap, stage, timeout=15)
        if outcome.get("exit_code") != 0:
            return None, "Isolated MPD execution unavailable: " + str(outcome.get("stderr") or "execution failed")[:1000]
        parsed = json.loads(outcome.get("stdout") or "{}")
        if parsed.get("error"):
            return None, str(parsed["error"])[:1000]
        if isinstance(parsed.get("result"), dict):
            return parsed["result"], None
        return None, "No valid 'result' dictionary in interpreter response"
    except Exception as exc:
        logger.warning("Isolated MPD execution failed: {}", exc)
        return None, "Isolated MPD execution failed: " + str(exc)[:500]


class AutonomousCodeInterpreter:
    """
    Autonomous Behind-the-Scenes Python Code Interpreter for Masterplan AI.
    Mimics ChatGPT Advanced Data Analysis / Claude Artifacts execution.
    """

    def __init__(self, ollama_url: str = OLLAMA_HOST, model: str = CODE_MODEL):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def build_system_prompt(self, plots_df: pd.DataFrame, project_id: str) -> str:
        sectors = sorted([s for s in plots_df["sector"].unique() if s])
        land_uses = sorted([lu for lu in plots_df["land_use"].unique() if lu])
        
        min_x, max_x = plots_df["x"].min(), plots_df["x"].max()
        min_y, max_y = plots_df["y"].min(), plots_df["y"].max()

        row_plots = plots_df[plots_df["land_use"].str.contains("ROW|road|way", case=False, na=False) | plots_df["plot_id"].str.contains("ROW", case=False, na=False)]
        mid_row_x = row_plots["x"].mean() if not row_plots.empty else 481826.0
        major_row = row_plots[row_plots["area_sqm"] > 5000]
        first_row_x = major_row["x"].min() if not major_row.empty else 480778.3

        return (
            "You are the Masterplan Autonomous Python Code Interpreter for Expo Design AI.\n"
            f"Project: {project_id} ({len(plots_df)} total plots).\n\n"
            "You have access to a pandas DataFrame named `plots_df` with columns:\n"
            "  - `plot_id` (str, e.g. 'P-5214982', 'P-5210747')\n"
            "  - `sector` (str, one of " + json.dumps(sectors) + ")\n"
            "  - `land_use` (str, one of " + json.dumps(land_uses) + ")\n"
            "  - `area_sqm` (float), `permitted_gfa` (float), `achieved_gfa` (float), `far` (float), `max_far` (float)\n"
            "  - `max_coverage_pct` (float), `front_setback_m` (float), `rear_setback_m` (float), `side_setback_m` (float)\n"
            "  - `parking_required` (int), `parking_provided` (int), `status` ('compliant', 'warning', 'violation')\n"
            f"  - `x` (float, centroid Easting coordinate in meters: smaller X = West/Left < {mid_row_x:,.0f}m < East/Right)\n"
            f"  - `y` (float, centroid Northing coordinate in meters: smaller Y = South/Bottom < North/Top)\n"
            f"Corridor Landmarks: 1st (Westmost) RoW Corridor: X ≈ {first_row_x:,.0f}m; Central RoW Corridor: X ≈ {mid_row_x:,.0f}m.\n\n"
            "SPATIAL REASONING GUIDELINES:\n"
            "- For spatial queries mentioning 'top of', 'above', 'north of', 'below', 'under', 'south of', 'left of', 'west of', 'right of', 'east of' a plot or corridor:\n"
            "  Always use the geographic coordinate columns: `y` for North/South (top/above/north: y > ref_y, below/south/bottom: y < ref_y), and `x` for East/West (left/west: x < ref_x, right/east: x > ref_x).\n"
            "  Do NOT filter by plot_id string comparisons for spatial terms like 'top' or 'above'; look up the reference plot row first (e.g. `ref = plots_df[plots_df['plot_id'].str.contains('5214982')].iloc[0]`) to get its `x` or `y` coordinate.\n\n"
            "Write a clean, concise Python snippet to answer the user query.\n"
            "Assign the final answer to a dictionary variable named `result` with one of these actions:\n\n"
            "1. Isolate/Filter Plots (e.g. 'show only...', 'plots above plot X', 'plots left of RoW', 'plots with FAR > 3', 'hospitality plots'):\n"
            "   result = {\n"
            "       'action': 'isolate',\n"
            "       'plot_ids': filtered_df['plot_id'].tolist(),\n"
            "       'label': 'Descriptive Title',\n"
            "       'explanation': 'Human engineering summary of what was matched'\n"
            "   }\n\n"
            "2. Canvas Scene Layer Visibility & Hatch Styling (e.g. 'hide cad line', 'turn off lines', 'hide all text', 'show lines', 'change hatch pattern', 'change hatch to diagonal/crosshatch/dots/solid'):\n"
            "   result = {\n"
            "       'action': 'set_layers',\n"
            "       'show_cad_linework': False | True | None,\n"
            "       'text_mode': 'off' | 'all' | None,\n"
            "       'hatch_pattern': 'diagonal' | 'crosshatch' | 'dots' | 'solid' | None,\n"
            "       'explanation': 'Clear explanation of the layer or hatch style applied, plus other available options.'\n"
            "   }\n"
            "   NOTE: If the user asks to 'change hatch pattern' without naming a pattern, set hatch_pattern='diagonal' and mention in explanation that 'crosshatch', 'dots', and 'solid' are also supported.\n\n"
            "3. Recolor / Heatmap (e.g. 'color by sector', 'unique colors for each plot', 'color red if far > 4'):\n"
            "   result = {\n"
            "       'action': 'recolor',\n"
            "       'color_mode': 'by_sector' | 'by_land_use' | 'by_status' | 'unique_per_plot' | 'custom_map',\n"
            "       'color_map': {pid: '#color'} (if custom_map),\n"
            "       'explanation': 'Human explanation'\n"
            "   }\n\n"
            "4. Distribution Charts (e.g. 'show donut chart of area by sector', 'pie chart of land use'):\n"
            "   result = {\n"
            "       'action': 'chart',\n"
            "       'chart_type': 'donut' | 'pie' | 'bar',\n"
            "       'group_by': 'sector' | 'land_use',\n"
            "       'metric': 'area_sqm' | 'achieved_gfa' | 'plot_count',\n"
            "       'explanation': 'Chart summary'\n"
            "   }\n\n"
            "5. Excel / Schedule Export (e.g. 'export hospitality to excel', 'change pie chart to excel'):\n"
            "   result = {\n"
            "       'action': 'export_excel',\n"
            "       'plot_ids': filtered_plots_or_None,\n"
            "       'explanation': 'Export summary'\n"
            "   }\n\n"
            "6. Technical Engineering Answer / Guidance / General Explanations:\n"
            "   When the user asks open-ended, procedural, or architectural questions (e.g. 'how to edit drawing', 'what is FAR', 'explain project zoning'):\n"
            "   Provide a comprehensive, professional, helpful markdown answer just like ChatGPT or Claude:\n"
            "   result = {\n"
            "       'action': 'answer',\n"
            "       'text': 'Thorough, well-formatted markdown response answering the user with actionable insights and engineering context.'\n"
            "   }\n\n"
            "GUIDELINES:\n"
            "- When an action (filtering, layers, hatch, recolor, chart, export) is requested, write a clean Python snippet inside ```python ``` that defines `result = {...}`.\n"
            "- You can also include a friendly, articulate conversational explanation.\n"
            "- If a query is purely conversational or explanatory, you can answer directly in markdown without code.\n"
        )

    async def run(
        self,
        query: str,
        project_id: str,
        plots_df: pd.DataFrame,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Sends query + chat history to local Qwen 3.5 9B via Ollama /api/chat,
        autonomously writing and executing Python scripts in the sandbox.
        """
        system_prompt = self.build_system_prompt(plots_df, project_id)

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for h in history[-6:]:
                if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                    # Strip out massive html/tables from history to keep context clean
                    c_text = str(h["content"]).split("<div")[0].split("<table")[0].strip()[:300]
                    if c_text:
                        messages.append({"role": h["role"], "content": c_text})
        messages.append({"role": "user", "content": query})

        try:
            async with httpx.AsyncClient(timeout=24.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 1000},
                    },
                )
                if resp.status_code != 200:
                    return None
                raw_response = resp.json().get("message", {}).get("content", "").strip()
                if not raw_response:
                    return None

                code = extract_python_code(raw_response)
                prose = re.sub(r"```(?:python)?[\s\S]*?```", "", raw_response).strip()

                if code:
                    logger.info(f"Code Interpreter generated code:\n{code}")
                    result, err = execute_sandboxed_code(code, plots_df)
                    if err or not result:
                        logger.warning(f"Code Interpreter execution error: {err}")
                        retry_messages = list(messages)
                        retry_messages.append({"role": "assistant", "content": f"```python\n{code}\n```"})
                        retry_messages.append({
                            "role": "user",
                            "content": f"The Python code resulted in error: {err}. Please fix the script and output only valid Python code inside ```python ``` block."
                        })
                        retry_resp = await client.post(
                            f"{self.ollama_url}/api/chat",
                            json={
                                "model": self.model,
                                "messages": retry_messages,
                                "stream": False,
                                "options": {"temperature": 0.0, "num_predict": 1000},
                            },
                        )
                        if retry_resp.status_code == 200:
                            retry_text = retry_resp.json().get("message", {}).get("content", "")
                            retry_code = extract_python_code(retry_text)
                            if retry_code:
                                logger.info(f"Code Interpreter self-healing code:\n{retry_code}")
                                result, _ = execute_sandboxed_code(retry_code, plots_df)
                                code = retry_code

                    if result and isinstance(result, dict):
                        result["_generated_code"] = code
                        if prose:
                            result["_prose"] = prose
                        return result

                # If no code was generated, treat as pure conversational response
                return {
                    "action": "answer",
                    "text": raw_response,
                    "_generated_code": "",
                    "_prose": raw_response,
                }
        except Exception as exc:
            logger.warning(f"Code Interpreter exception: {exc}")
            return None
