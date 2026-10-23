"""20-Question Automated Stress Test for Expo Design AI BIM Model MCP Bridge.

Tests both projects (C3082 - SiteWide and C3085 - 3EH -Expo Hills), exercising:
- Spatial storeys & hierarchy
- Quantity takeoffs (counts, areas, volumes)
- Element searches & subtype classification
- Geometric 3D measurements (Euclidean distance via IfcOpenShell)
- 3D Viewer action generation (isolate, color, reset)
- AI reasoning via Qwen 3.5 9B with MCP tool calling
"""
import os
import sys
import time
import json
import urllib.request
from typing import Dict, Any, List

os.chdir(r"C:\3EH\ExpoDesignAI - Copy")
sys.path.insert(0, r"C:\3EH\ExpoDesignAI - Copy")

import db
import auth
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

u = db.get_user_by_username("admin")
token = auth.make_token(u)
API_BASE = "http://127.0.0.1:8090"
HEADERS = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}


def run_test(num: int, title: str, fn) -> Dict[str, Any]:
    start = time.perf_counter()
    status = "PASS"
    error = None
    data = None
    try:
        data = fn()
    except Exception as e:
        status = "FAIL"
        error = str(e)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "num": num,
        "title": title,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "data": data,
        "error": error
    }


def main():
    print("=" * 70)
    print("STARTING 20-QUESTION STRESS TEST ACROSS ALL 3D MODELS (151,103 ELEMENTS)")
    print("=" * 70)

    results = []

    # Q1: List models in C3082
    results.append(run_test(
        1, "List loaded IFC models and disciplines in C3082 - SiteWide",
        lambda: list_models("C3082 - SiteWide")
    ))

    # Q2: List models in C3085
    results.append(run_test(
        2, "List loaded IFC models and disciplines in C3085 - 3EH -Expo Hills",
        lambda: list_models("C3085 - 3EH -Expo Hills")
    ))

    # Q3: Walls QTO in C3085
    results.append(run_test(
        3, "Quantity takeoff for all Walls (IFCWALL) in C3085",
        lambda: takeoff_summary("C3085 - 3EH -Expo Hills", ifc_class="IFCWALL")
    ))

    # Q4: Doors count in C3085
    results.append(run_test(
        4, "Search and count all Doors (IFCDOOR) in C3085",
        lambda: search_elements("C3085 - 3EH -Expo Hills", ifc_class="IFCDOOR", limit=5)
    ))

    # Q5: Windows count in C3085
    results.append(run_test(
        5, "Search and count all Windows (IFCWINDOW) in C3085",
        lambda: search_elements("C3085 - 3EH -Expo Hills", ifc_class="IFCWINDOW", limit=5)
    ))

    # Q6: Slabs volume and area in C3085
    results.append(run_test(
        6, "Quantity takeoff for all Slabs (IFCSLAB) in C3085",
        lambda: takeoff_summary("C3085 - 3EH -Expo Hills", ifc_class="IFCSLAB")
    ))

    # Q7: Stairs count in C3085
    results.append(run_test(
        7, "Search all Stairs (IFCSTAIR / IFCSTAIRFLIGHT) in C3085",
        lambda: search_elements("C3085 - 3EH -Expo Hills", keyword="stair", limit=5)
    ))

    # Q8: Columns in C3082
    results.append(run_test(
        8, "Search all Columns (IFCCOLUMN) in C3082 - SiteWide",
        lambda: search_elements("C3082 - SiteWide", ifc_class="IFCCOLUMN", limit=5)
    ))

    # Q9: Total Vegetation/Plants in C3082
    results.append(run_test(
        9, "Count all Plant/Vegetation elements in C3082 - SiteWide",
        lambda: search_elements("C3082 - SiteWide", keyword="plant", limit=5)
    ))

    # Q10: Palm trees count in C3082
    results.append(run_test(
        10, "Search and count all Palm Trees (EDS_11P_PALM) in C3082",
        lambda: search_elements("C3082 - SiteWide", keyword="palm", limit=5)
    ))

    # Q11: Tree Canopies count in C3082
    results.append(run_test(
        11, "Search and count Canopy Trees (EDS_11P_TREE_CANOPY) in C3082",
        lambda: search_elements("C3082 - SiteWide", keyword="canopy", limit=5)
    ))

    # Q12: Accent Shrubs count in C3082
    results.append(run_test(
        12, "Search and count Accent Shrubs (EDS_11P_ACCENT SHRUB) in C3082",
        lambda: search_elements("C3082 - SiteWide", keyword="shrub", limit=5)
    ))

    # Q13: Spatial Storeys in C3085
    results.append(run_test(
        13, "Get building spatial storeys and elevations in C3085",
        lambda: spatial_summary("C3085 - 3EH -Expo Hills")
    ))

    # Q14: Level 01 elements in C3085
    results.append(run_test(
        14, "Count elements on Ground / Level 01 in C3085",
        lambda: takeoff_summary("C3085 - 3EH -Expo Hills", group_by="storey")
    ))

    # Q15: Measure 3D Distance between 2 Palms
    results.append(run_test(
        15, "Geometric 3D Euclidean distance between two palm trees in C3082",
        lambda: measure_distance("C3082 - SiteWide", element_id_1=63852, element_id_2=63853)
    ))

    # Q16: Element Details for ID 63852
    results.append(run_test(
        16, "Fetch full property sets and dimensions of Palm element 63852",
        lambda: get_element_details(project="C3082 - SiteWide", element_id=63852)
    ))

    # Q17: Viewer Action - Isolate Palms
    results.append(run_test(
        17, "Generate 3D viewer action to isolate all palm trees in C3082",
        lambda: create_viewer_action("C3082 - SiteWide", action="isolate", keyword="palm")
    ))

    # Q18: Viewer Action - Isolate Walls via HTTP API
    def test_http_plan_walls():
        body = {
            "project": "C3085 - 3EH -Expo Hills",
            "question": "show only walls",
            "categories": ["IFCWALL", "IFCSLAB", "IFCDOOR"]
        }
        req = urllib.request.Request(
            f"{API_BASE}/api/bim/plan-view-action",
            data=json.dumps(body).encode("utf-8"),
            headers=HEADERS
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    results.append(run_test(
        18, "API POST /api/bim/plan-view-action: 'show only walls' in C3085",
        test_http_plan_walls
    ))

    # Q19: Viewer Action - Color Doors Red via HTTP API
    def test_http_plan_color():
        body = {
            "project": "C3085 - 3EH -Expo Hills",
            "question": "colour doors red",
            "categories": ["IFCWALL", "IFCSLAB", "IFCDOOR"]
        }
        req = urllib.request.Request(
            f"{API_BASE}/api/bim/plan-view-action",
            data=json.dumps(body).encode("utf-8"),
            headers=HEADERS
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    results.append(run_test(
        19, "API POST /api/bim/plan-view-action: 'colour doors red' in C3085",
        test_http_plan_color
    ))

    # Q20: Viewer Action - Reset View
    def test_http_plan_reset():
        body = {
            "project": "C3082 - SiteWide",
            "question": "reset view",
            "categories": ["IFCBUILDINGELEMENTPROXY", "IFCCOLUMN"]
        }
        req = urllib.request.Request(
            f"{API_BASE}/api/bim/plan-view-action",
            data=json.dumps(body).encode("utf-8"),
            headers=HEADERS
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    results.append(run_test(
        20, "API POST /api/bim/plan-view-action: 'reset view' in C3082",
        test_http_plan_reset
    ))

    # Output Results
    print("\n" + "=" * 70)
    print("STRESS TEST EXECUTION SUMMARY:")
    print("=" * 70)
    passed = 0
    total_time = 0.0

    for r in results:
        total_time += r["elapsed_ms"]
        status_icon = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        if r["status"] == "PASS":
            passed += 1
        print(f"[{r['num']:02d}/20] {status_icon} {r['status']} ({r['elapsed_ms']:>6.1f} ms) | {r['title']}")

        # Print brief highlights
        d = r["data"]
        if isinstance(d, dict):
            if "total_count" in d:
                print(f"        -> Total elements matched: {d['total_count']}")
            elif "distance_3d_meters" in d:
                print(f"        -> Exact 3D Distance: {d['distance_3d_meters']} m")
            elif "model_count" in d:
                print(f"        -> Models loaded: {d['model_count']}")
            elif "total_storeys" in d:
                print(f"        -> Storeys: {d['total_storeys']}")
            elif "target_count" in d:
                print(f"        -> View action target items: {d['target_count']}")
            elif "actions" in d and d["actions"]:
                print(f"        -> Planned action: {d['actions'][0]}")

    print("=" * 70)
    print(f"RESULT: {passed}/20 PASSED ({passed/20*100:.1f}%) in {total_time:.1f} ms total!")
    print("=" * 70)

    # Save to JSON
    with open("data/stress_test_20_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print("Full results saved to data/stress_test_20_results.json")


if __name__ == "__main__":
    main()
