"""
Senior Masterplan Engineering Audit Suite for ExpoDesignAI MPD.
Tests 120+ realistic civil engineering and urban planning questions against
Project 'C3085 - 3EH -Expo Hills' (CAD DWG geometry + Excel register schedule).

Evaluates:
- Area and footprint filtering (>, <, between, ranges)
- GFA capacity analysis and thresholds
- FAR density violations and high-density clustering
- RoW corridor topology (identification, left/west vs right/east spatial partitioning)
- Sector and zoning allocation (Expo Hills, Downtown, Fields, Business)
- Land use breakdown (Residential, Commercial, Mixed Use, Open Space, Hospitality, etc.)
- Multi-source CAD <-> Excel reconciliation & Ground Truth stabilization
- Parking capacity and deficit calculations
- Spatial compliance, setback regulations, and height envelopes
- Plot inspection, ranking, and audit rollback
- CAD canvas visual controls and conditional hatch coloring
"""
import asyncio
import json
import os
import sys
import time
from typing import Dict, Any, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from services.masterplan.agent import MasterplanAIAgent
from services.masterplan.models import MasterplanAIQueryRequest
from services.masterplan import db

PROJECT_ID = "C3085 - 3EH -Expo Hills"

# 122 Structured Civil / Urban Planning Engineering Questions across 11 Technical Categories
AUDIT_QUESTIONS = [
    # -------------------------------------------------------------
    # Category 1: Parcel Footprint Area Thresholds & Filtering (12)
    # -------------------------------------------------------------
    {"id": "Q001", "cat": "Footprint Area", "query": "show me only plots area more then 10000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q002", "cat": "Footprint Area", "query": "show plots with area less than 5000 sqm", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q003", "cat": "Footprint Area", "query": "plots where footprint area is greater than 15000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q004", "cat": "Footprint Area", "query": "which parcels have area exceeding 25,000 sqm?", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q005", "cat": "Footprint Area", "query": "filter plots with area below 3000 m2", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q006", "cat": "Footprint Area", "query": "show me plots with area <= 2000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q007", "cat": "Footprint Area", "query": "show me plots with area >= 30000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q008", "cat": "Footprint Area", "query": "which plots have footprint under 2,500 sqm?", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q009", "cat": "Footprint Area", "query": "plots with area between 5000 and 15000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q010", "cat": "Footprint Area", "query": "parcels with area from 10000 to 20000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q011", "cat": "Footprint Area", "query": "show residential plots with area more than 8000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},
    {"id": "Q012", "cat": "Footprint Area", "query": "show commercial plots with area > 15000", "min_highlights": 1, "expected_intent": "QUERY_AREA_THRESHOLD"},

    # -------------------------------------------------------------
    # Category 2: Achieved & Permitted GFA Capacities (12)
    # -------------------------------------------------------------
    {"id": "Q013", "cat": "GFA Capacity", "query": "show plots with GFA less than 20000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q014", "cat": "GFA Capacity", "query": "show plots with GFA more than 50000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q015", "cat": "GFA Capacity", "query": "parcels where achieved GFA is greater than 30,000 sqm", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q016", "cat": "GFA Capacity", "query": "plots with GFA below 10,000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q017", "cat": "GFA Capacity", "query": "highlight plots with GFA exceeding 75,000 sqm", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q018", "cat": "GFA Capacity", "query": "parcels with achieved GFA >= 60000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q019", "cat": "GFA Capacity", "query": "plots with GFA <= 5000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q020", "cat": "GFA Capacity", "query": "show residential plots with GFA more than 20000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q021", "cat": "GFA Capacity", "query": "show commercial plots with GFA < 30000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q022", "cat": "GFA Capacity", "query": "parcels with achieved GFA between 20000 and 50000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q023", "cat": "GFA Capacity", "query": "plots with GFA from 10000 to 40000", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},
    {"id": "Q024", "cat": "GFA Capacity", "query": "which mixed use plots have GFA exceeding 40,000?", "min_highlights": 1, "expected_intent": "QUERY_GFA_THRESHOLD"},

    # -------------------------------------------------------------
    # Category 3: Floor Area Ratio (FAR) Density & Over-Development (12)
    # -------------------------------------------------------------
    {"id": "Q025", "cat": "FAR Density", "query": "which plots have FAR greater than 3.0?", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q026", "cat": "FAR Density", "query": "show plots exceeding max FAR", "min_highlights": 1, "expected_intent": ["QUERY_DENSITY", "SPATIAL_AUDIT"]},
    {"id": "Q027", "cat": "FAR Density", "query": "plots with FAR > 2.5", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q028", "cat": "FAR Density", "query": "identify high density parcels with FAR > 3.5", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q029", "cat": "FAR Density", "query": "parcels where FAR is above 4.0", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q030", "cat": "FAR Density", "query": "parcels with FAR greater than 5.0", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q031", "cat": "FAR Density", "query": "show parcels with FAR exceeding 6.0", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q032", "cat": "FAR Density", "query": "which parcels exceed permissible FAR limits?", "min_highlights": 1, "expected_intent": ["QUERY_DENSITY", "SPATIAL_AUDIT"]},
    {"id": "Q033", "cat": "FAR Density", "query": "show me plots with highest FAR", "min_highlights": 1, "expected_intent": "QUERY_RANKINGS"},
    {"id": "Q034", "cat": "FAR Density", "query": "show me top plots by FAR", "min_highlights": 1, "expected_intent": "QUERY_RANKINGS"},
    {"id": "Q035", "cat": "FAR Density", "query": "parcels with FAR > 1.5", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},
    {"id": "Q036", "cat": "FAR Density", "query": "list all high density development plots", "min_highlights": 1, "expected_intent": "QUERY_DENSITY"},

    # -------------------------------------------------------------
    # Category 4: Right-of-Way (RoW), Roads & Spatial Corridor Topology (12)
    # -------------------------------------------------------------
    {"id": "Q037", "cat": "Infrastructure & RoW", "query": "show only plots that are RoW", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},
    {"id": "Q038", "cat": "Infrastructure & RoW", "query": "show only plots that are RoW of left", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q039", "cat": "Infrastructure & RoW", "query": "show only plots that are RoW of right", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q040", "cat": "Infrastructure & RoW", "query": "parcels to the west of the central RoW corridor", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q041", "cat": "Infrastructure & RoW", "query": "parcels to the east of the central RoW corridor", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q042", "cat": "Infrastructure & RoW", "query": "which development plots are situated left of the road network?", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q043", "cat": "Infrastructure & RoW", "query": "which development plots are situated right of the road network?", "min_highlights": 50, "expected_intent": "SPATIAL_ROW_DIRECTIONAL"},
    {"id": "Q044", "cat": "Infrastructure & RoW", "query": "show road network parcels", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},
    {"id": "Q045", "cat": "Infrastructure & RoW", "query": "how many plots are dedicated to roads and parking?", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},
    {"id": "Q046", "cat": "Infrastructure & RoW", "query": "what is the total area of Right-of-Way in the masterplan?", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},
    {"id": "Q047", "cat": "Infrastructure & RoW", "query": "show roads and parking plots", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},
    {"id": "Q048", "cat": "Infrastructure & RoW", "query": "list all dedicated infrastructure and RoW parcels", "min_highlights": 50, "expected_intent": "QUERY_ROW_INFRASTRUCTURE"},

    # -------------------------------------------------------------
    # Category 5: Sector & Zoning Distribution (12)
    # -------------------------------------------------------------
    {"id": "Q049", "cat": "Sectors & Zoning", "query": "show all plots in Expo Business sector", "min_highlights": 5, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q050", "cat": "Sectors & Zoning", "query": "list plots in Expo Downtown", "min_highlights": 10, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q051", "cat": "Sectors & Zoning", "query": "show plots in Expo Fields", "min_highlights": 10, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q052", "cat": "Sectors & Zoning", "query": "plots in Expo Hills sector", "min_highlights": 50, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q053", "cat": "Sectors & Zoning", "query": "how many parcels are in Expo Business?", "min_highlights": 5, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q054", "cat": "Sectors & Zoning", "query": "breakdown of parcels in Expo Downtown", "min_highlights": 10, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q055", "cat": "Sectors & Zoning", "query": "what is the total area of Expo Fields sector?", "min_highlights": 10, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q056", "cat": "Sectors & Zoning", "query": "expo hills sector development parcels", "min_highlights": 50, "expected_intent": "QUERY_SECTOR"},
    {"id": "Q057", "cat": "Sectors & Zoning", "query": "show commercial parcels in Expo Hills", "min_highlights": 5, "expected_intent": ["QUERY_SECTOR", "QUERY_LAND_USE"]},
    {"id": "Q058", "cat": "Sectors & Zoning", "query": "show mixed use plots in Expo Downtown", "min_highlights": 10, "expected_intent": ["QUERY_SECTOR", "QUERY_LAND_USE"]},
    {"id": "Q059", "cat": "Sectors & Zoning", "query": "show residential plots in Expo Fields", "min_highlights": 5, "expected_intent": ["QUERY_SECTOR", "QUERY_LAND_USE"]},
    {"id": "Q060", "cat": "Sectors & Zoning", "query": "list development parcels in Sector Expo Business", "min_highlights": 5, "expected_intent": "QUERY_SECTOR"},

    # -------------------------------------------------------------
    # Category 6: Land Use Allocation & Permitted Use Audits (12)
    # -------------------------------------------------------------
    {"id": "Q061", "cat": "Land Use Mix", "query": "show residential plots", "min_highlights": 10, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q062", "cat": "Land Use Mix", "query": "show commercial plots", "min_highlights": 10, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q063", "cat": "Land Use Mix", "query": "show mixed use plots", "min_highlights": 50, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q064", "cat": "Land Use Mix", "query": "show open space and park plots", "min_highlights": 20, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q065", "cat": "Land Use Mix", "query": "show civic plots", "min_highlights": 5, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q066", "cat": "Land Use Mix", "query": "show utilities parcels", "min_highlights": 50, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q067", "cat": "Land Use Mix", "query": "show hospitality plots", "min_highlights": 3, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q068", "cat": "Land Use Mix", "query": "show public facilities plots", "min_highlights": 1, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q069", "cat": "Land Use Mix", "query": "what is the total residential GFA in Expo Hills?", "min_highlights": 10, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q070", "cat": "Land Use Mix", "query": "what percentage of masterplan area is dedicated to open space?", "min_highlights": 20, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q071", "cat": "Land Use Mix", "query": "show open space parcels", "min_highlights": 20, "expected_intent": "QUERY_LAND_USE"},
    {"id": "Q072", "cat": "Land Use Mix", "query": "list all utility plots and substations", "min_highlights": 50, "expected_intent": "QUERY_LAND_USE"},

    # -------------------------------------------------------------
    # Category 7: Multi-Source Reconciliation & Ground Truth Parity (12)
    # -------------------------------------------------------------
    {"id": "Q073", "cat": "Reconciliation", "query": "check files and stabilize the relation", "expected_intent": ["RECONCILE_DISCREPANCIES", "STABILIZE_RELATION", "QUERY_RELATION"]},
    {"id": "Q074", "cat": "Reconciliation", "query": "what is the relation between CAD and Excel?", "expected_intent": "QUERY_RELATION"},
    {"id": "Q075", "cat": "Reconciliation", "query": "show file status", "expected_intent": "QUERY_RELATION"},
    {"id": "Q076", "cat": "Reconciliation", "query": "show files", "expected_intent": "QUERY_RELATION"},
    {"id": "Q077", "cat": "Reconciliation", "query": "list files", "expected_intent": "QUERY_RELATION"},
    {"id": "Q078", "cat": "Reconciliation", "query": "reconcile discrepancies between CAD and Excel register", "expected_intent": ["RECONCILE_DISCREPANCIES", "STABILIZE_RELATION", "QUERY_RELATION"]},
    {"id": "Q079", "cat": "Reconciliation", "query": "are there any discrepancies in plot area between CAD hatch and Excel schedule?", "expected_intent": ["RECONCILE_DISCREPANCIES", "STABILIZE_RELATION", "QUERY_RELATION"]},
    {"id": "Q080", "cat": "Reconciliation", "query": "adopt cad for plot P-5210747", "min_highlights": 1, "expected_intent": "STABILIZE_RELATION"},
    {"id": "Q081", "cat": "Reconciliation", "query": "adopt excel for plot P-5210753", "min_highlights": 1, "expected_intent": "STABILIZE_RELATION"},
    {"id": "Q082", "cat": "Reconciliation", "query": "adopt cad for plot 5210754", "min_highlights": 1, "expected_intent": "STABILIZE_RELATION"},
    {"id": "Q083", "cat": "Reconciliation", "query": "show stabilized ground truth", "expected_intent": "QUERY_RELATION"},
    {"id": "Q084", "cat": "Reconciliation", "query": "cross reference CAD drawing with Excel schedule", "expected_intent": ["RECONCILE_DISCREPANCIES", "STABILIZE_RELATION", "QUERY_RELATION"]},

    # -------------------------------------------------------------
    # Category 8: Parking Capacity & Infrastructure Adequacy (8)
    # -------------------------------------------------------------
    {"id": "Q085", "cat": "Parking Capacity", "query": "show parcels with parking deficit", "expected_intent": "QUERY_PARKING"},
    {"id": "Q086", "cat": "Parking Capacity", "query": "what is the total parking required vs provided?", "expected_intent": "QUERY_PARKING"},
    {"id": "Q087", "cat": "Parking Capacity", "query": "which plots fail to meet minimum parking requirements?", "expected_intent": "QUERY_PARKING"},
    {"id": "Q088", "cat": "Parking Capacity", "query": "calculate total parking capacity across Expo Hills", "expected_intent": "QUERY_PARKING"},
    {"id": "Q089", "cat": "Parking Capacity", "query": "are there any parking deficit plots in the masterplan?", "expected_intent": "QUERY_PARKING"},
    {"id": "Q090", "cat": "Parking Capacity", "query": "parking bay demand and supply balance", "expected_intent": "QUERY_PARKING"},
    {"id": "Q091", "cat": "Parking Capacity", "query": "how many total parking bays are required?", "expected_intent": "QUERY_PARKING"},
    {"id": "Q092", "cat": "Parking Capacity", "query": "parking requirements analysis", "expected_intent": "QUERY_PARKING"},

    # -------------------------------------------------------------
    # Category 9: Building Heights, Setbacks & Spatial Compliance (10)
    # -------------------------------------------------------------
    {"id": "Q093", "cat": "Heights & Setbacks", "query": "run spatial compliance audit", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q094", "cat": "Heights & Setbacks", "query": "check compliance", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q095", "cat": "Heights & Setbacks", "query": "list all plots with violations", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q096", "cat": "Heights & Setbacks", "query": "show parcels with setback buffer non-compliance", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q097", "cat": "Heights & Setbacks", "query": "what are the standard setback requirements in Expo Hills?", "expected_intent": "QUERY_REGULATIONS"},
    {"id": "Q098", "cat": "Heights & Setbacks", "query": "show standard setback buffers", "expected_intent": "QUERY_REGULATIONS"},
    {"id": "Q099", "cat": "Heights & Setbacks", "query": "building height envelope regulations", "expected_intent": "QUERY_REGULATIONS"},
    {"id": "Q100", "cat": "Heights & Setbacks", "query": "check masterplan setback compliance", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q101", "cat": "Heights & Setbacks", "query": "identify encroaching parcels", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},
    {"id": "Q102", "cat": "Heights & Setbacks", "query": "audit plot setbacks and site coverage", "min_highlights": 1, "expected_intent": "SPATIAL_AUDIT"},

    # -------------------------------------------------------------
    # Category 10: Specific Plot Inspections, Top Rankings & Actions (10)
    # -------------------------------------------------------------
    {"id": "Q103", "cat": "Plot Inspection", "query": "inspect plot P-5210747", "min_highlights": 1, "expected_intent": "INSPECT_PLOT"},
    {"id": "Q104", "cat": "Plot Inspection", "query": "details of plot P-5210753", "min_highlights": 1, "expected_intent": "INSPECT_PLOT"},
    {"id": "Q105", "cat": "Plot Inspection", "query": "what is the FAR and GFA of plot 5210754?", "min_highlights": 1, "expected_intent": "INSPECT_PLOT"},
    {"id": "Q106", "cat": "Plot Inspection", "query": "inspect plot 5210766", "min_highlights": 1, "expected_intent": "INSPECT_PLOT"},
    {"id": "Q107", "cat": "Plot Inspection", "query": "show details for Plot P-5211026", "min_highlights": 1, "expected_intent": "INSPECT_PLOT"},
    {"id": "Q108", "cat": "Plot Inspection", "query": "show me the top 5 largest plots", "min_highlights": 5, "expected_intent": "QUERY_RANKINGS"},
    {"id": "Q109", "cat": "Plot Inspection", "query": "which plot has the smallest footprint?", "min_highlights": 1, "expected_intent": "QUERY_RANKINGS"},
    {"id": "Q110", "cat": "Plot Inspection", "query": "show me the largest parcels", "min_highlights": 5, "expected_intent": "QUERY_RANKINGS"},
    {"id": "Q111", "cat": "Plot Inspection", "query": "show all plots", "min_highlights": 10, "expected_intent": "LIST_PLOTS"},
    {"id": "Q112", "cat": "Plot Inspection", "query": "undo last action", "expected_intent": "UNDO_ACTION"},

    # -------------------------------------------------------------
    # Category 11: CAD Drawing Canvas & Visual Color Controls (10)
    # -------------------------------------------------------------
    {"id": "Q113", "cat": "CAD Visual Actions", "query": "change the ccolor of plots for GFA less then 20000 to blue", "expected_intent": "VIEW_ACTION"},
    {"id": "Q114", "cat": "CAD Visual Actions", "query": "change the color of plots for GFA less than 20000 to blue", "expected_intent": "VIEW_ACTION"},
    {"id": "Q115", "cat": "CAD Visual Actions", "query": "color plots with area more than 15000 to red", "expected_intent": "VIEW_ACTION"},
    {"id": "Q116", "cat": "CAD Visual Actions", "query": "make plots where far is greater than 3.0 orange", "expected_intent": "VIEW_ACTION"},
    {"id": "Q117", "cat": "CAD Visual Actions", "query": "change the color of residential plots to green", "expected_intent": "VIEW_ACTION"},
    {"id": "Q118", "cat": "CAD Visual Actions", "query": "change the color of commercial plots to yellow", "expected_intent": "VIEW_ACTION"},
    {"id": "Q119", "cat": "CAD Visual Actions", "query": "color open space plots green", "expected_intent": "VIEW_ACTION"},
    {"id": "Q120", "cat": "CAD Visual Actions", "query": "hide plot labels", "expected_intent": "VIEW_ACTION"},
    {"id": "Q121", "cat": "CAD Visual Actions", "query": "show cad text", "expected_intent": "VIEW_ACTION"},
    {"id": "Q122", "cat": "CAD Visual Actions", "query": "zoom to fit", "expected_intent": "VIEW_ACTION"},
]


async def run_audit():
    print("=" * 80)
    print("🚀 EXPO DESIGN AI — MPD 100+ MASTERPLAN QUESTION AUDIT SUITE")
    print(f"Target Project: '{PROJECT_ID}'")
    print("=" * 80)

    bak_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "masterplan.db.bak")
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "masterplan.db")
    if os.path.exists(bak_path):
        import shutil
        shutil.copyfile(bak_path, db_path)
    agent = MasterplanAIAgent()
    all_plots = db.get_plots(PROJECT_ID)
    print(f"Verified Database: {len(all_plots)} parcels loaded in project '{PROJECT_ID}'.")
    print(f"Total Questions Queued: {len(AUDIT_QUESTIONS)}")
    print("-" * 80)

    results = []
    category_metrics = {}
    total_passed = 0
    total_failed = 0
    latencies = []

    for item in AUDIT_QUESTIONS:
        qid = item["id"]
        cat = item["cat"]
        query = item["query"]
        expected_intent = item.get("expected_intent")
        min_highlights = item.get("min_highlights", 0)

        if cat not in category_metrics:
            category_metrics[cat] = {"total": 0, "passed": 0, "failed": 0, "latencies": []}
        category_metrics[cat]["total"] += 1

        t0 = time.perf_counter()
        try:
            req = MasterplanAIQueryRequest(project_id=PROJECT_ID, query=query)
            res = await agent.process_query(req)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)
            category_metrics[cat]["latencies"].append(elapsed_ms)

            # Verification Logic
            passed = True
            failure_reasons = []

            # 1. Answer presence
            if not res.answer:
                passed = False
                failure_reasons.append("Empty answer received")

            # 2. Intent validation
            if expected_intent:
                if isinstance(expected_intent, list):
                    if res.intent not in expected_intent:
                        passed = False
                        failure_reasons.append(f"Intent '{res.intent}' not in {expected_intent}")
                else:
                    if res.intent != expected_intent:
                        passed = False
                        failure_reasons.append(f"Intent '{res.intent}' != expected '{expected_intent}'")

            # 3. Highlight count validation
            if min_highlights > 0 and len(res.highlight_plots) < min_highlights:
                passed = False
                failure_reasons.append(f"Highlight plots count {len(res.highlight_plots)} < min required {min_highlights}")

            # 4. View action validation for CAD canvas actions
            if res.intent == "VIEW_ACTION" and not res.view_actions:
                passed = False
                failure_reasons.append("VIEW_ACTION returned with empty view_actions")

            status_str = "✅ PASS" if passed else "❌ FAIL"
            hl_count = len(res.highlight_plots)
            act_info = f"Actions: {len(res.view_actions)}" if res.view_actions else f"Plots: {hl_count}"

            print(f"[{qid}] {status_str} | {cat:20s} | {elapsed_ms:5.1f}ms | Intent: {res.intent:22s} | {act_info:12s} | Query: \"{query[:45]}\"")

            if not passed:
                print(f"      ↳ ⚠️ Forensics: {'; '.join(failure_reasons)}")
                total_failed += 1
                category_metrics[cat]["failed"] += 1
            else:
                total_passed += 1
                category_metrics[cat]["passed"] += 1

            results.append({
                "id": qid,
                "category": cat,
                "query": query,
                "passed": passed,
                "latency_ms": round(elapsed_ms, 2),
                "intent": res.intent,
                "tools_called": res.tools_called,
                "highlight_count": hl_count,
                "view_actions": res.view_actions,
                "failure_reasons": failure_reasons,
                "answer_excerpt": res.answer[:120].replace("\n", " ")
            })

        except Exception as ex:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            print(f"[{qid}] 💥 CRASH | {cat:20s} | {elapsed_ms:5.1f}ms | Exception: {ex} | Query: \"{query}\"")
            total_failed += 1
            category_metrics[cat]["failed"] += 1
            results.append({
                "id": qid,
                "category": cat,
                "query": query,
                "passed": False,
                "latency_ms": round(elapsed_ms, 2),
                "error": str(ex),
                "failure_reasons": [f"Exception: {ex}"]
            })

    # Summary Report
    pass_pct = (total_passed / len(AUDIT_QUESTIONS)) * 100.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0

    print("=" * 80)
    print("📊 SENIOR CIVIL/MASTERPLAN AUDIT RESULTS")
    print("=" * 80)
    print(f"Total Questions Tested: {len(AUDIT_QUESTIONS)}")
    print(f"Passed:                 {total_passed} ({pass_pct:.1f}%)")
    print(f"Failed:                 {total_failed}")
    print(f"Latency (Avg / Min / Max): {avg_latency:.1f}ms / {min_latency:.1f}ms / {max_latency:.1f}ms")
    print("-" * 80)
    print(f"{'Category':<25} | {'Total':<6} | {'Passed':<6} | {'Pass Rate':<10} | {'Avg Latency'}")
    print("-" * 80)

    for cat, m in category_metrics.items():
        cat_pct = (m["passed"] / m["total"]) * 100.0 if m["total"] > 0 else 0.0
        cat_avg = sum(m["latencies"]) / len(m["latencies"]) if m["latencies"] else 0.0
        print(f"{cat:<25} | {m['total']:<6} | {m['passed']:<6} | {cat_pct:6.1f}%    | {cat_avg:5.1f}ms")

    print("=" * 80)

    # Save structured audit results JSON
    report_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "masterplan_questions_audit_results.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "project_id": PROJECT_ID,
            "total_questions": len(AUDIT_QUESTIONS),
            "passed": total_passed,
            "failed": total_failed,
            "pass_rate_pct": round(pass_pct, 2),
            "latency": {
                "avg_ms": round(avg_latency, 2),
                "min_ms": round(min_latency, 2),
                "max_ms": round(max_latency, 2)
            },
            "category_metrics": category_metrics,
            "audit_trail": results
        }, f, indent=2)

    print(f"Detailed Forensic JSON saved to: {report_file}")
    return total_failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_audit())
    sys.exit(0 if success else 1)
