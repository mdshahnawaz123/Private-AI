# -*- coding: utf-8 -*-
"""
Phase 13 - Step 2: Forensic Benchmark Runner
Runs every question through the REAL production pipeline and records traces.
"""
import sys, os, json, time, csv, re

sys.path.insert(0, r"C:\3EH\ExpoDesignAI - Copy")
os.environ["PYTHONIOENCODING"] = "utf-8"

import intelligence.structured_query as sq

# ---- Mock functions ----
def mock_retrieve(proj, q, k=5, user=None):
    """Mock RAG: return empty so we isolate structured pipeline failures."""
    return ([], "")

def mock_qwen(prompt):
    """Mock Qwen: return the structured data as-is for verification."""
    return f"[MOCK_QWEN]", 0.001

# ---- Evaluation helpers ----
def check_numeric(expected, actual_answer, provenance):
    """Check if expected numeric value appears in answer or provenance."""
    try:
        exp_val = float(str(expected).replace(",", ""))
    except (ValueError, TypeError):
        return False
    # Check provenance first (most reliable)
    for p in (provenance or []):
        pv = p.get("value")
        if pv is not None:
            try:
                if abs(float(pv) - exp_val) < 0.01:
                    return True
            except (ValueError, TypeError):
                pass
        # Check calculation result
    return False

def check_numeric_in_answer(expected, actual_answer):
    """Check if expected numeric value appears in the answer string."""
    try:
        exp_val = float(str(expected).replace(",", ""))
    except (ValueError, TypeError):
        return False
    # Find numbers in answer
    nums = re.findall(r'[\d,]+\.?\d*', str(actual_answer).replace(",", ""))
    for n in nums:
        try:
            if abs(float(n) - exp_val) < 0.5:
                return True
        except ValueError:
            pass
    return False

def check_not_found(status, answer):
    """Check if the system correctly returned NOT_FOUND."""
    if status in ("NOT_FOUND", "UNSUPPORTED", "AMBIGUOUS"):
        return True
    ans_lower = str(answer).lower()
    nf_phrases = ["not found", "not available", "no verified", "no data",
                  "does not exist", "cannot find", "could not find"]
    return any(p in ans_lower for p in nf_phrases)

def check_multi_value(expected_str, provenance):
    """Check if all expected values appear in provenance."""
    # expected_str: "Floor GFA=2407.0, Floor GA=2111.0"
    pairs = expected_str.split(", ")
    for pair in pairs:
        if "=" not in pair:
            continue
        field_name, val_str = pair.split("=", 1)
        try:
            exp_val = float(val_str)
        except ValueError:
            continue
        found = False
        for p in (provenance or []):
            pv = p.get("value")
            if pv is not None:
                try:
                    if abs(float(pv) - exp_val) < 0.5:
                        found = True
                        break
                except (ValueError, TypeError):
                    pass
        if not found:
            return False
    return True

def classify_failure(q, trace):
    """Classify the primary failure reason for a failed question."""
    cat = q["category"]
    exp_type = q["expected_type"]
    classifier_result = trace["classifier_result"]
    parsed = trace["parsed"]
    status = trace["status"]
    route = trace["route"]

    # NOT_FOUND questions that system answered (should have said NOT_FOUND)
    if exp_type == "NOT_FOUND":
        if status == "SUCCESS":
            return "N_NOT_FOUND_HANDLING_FAILURE"
        return "P_OTHER"

    # Misrouted to MODEL_QA
    if classifier_result == "MODEL_QA":
        return "A_QUESTION_CLASSIFICATION_FAILURE"

    # Parser returned None (fell to RAG) for a structured question
    if parsed is None and q.get("deterministic", True):
        # Why did parser fail? Check if field is in fields_def
        ql = q["question"].lower()
        known_fields = ["gfa", "ga", "nisa", "nsa", "bua", "balcon", "efficiency"]
        has_field = any(f in ql for f in known_fields)
        bed_match = re.search(r'\d+\s*bed', ql)
        if bed_match:
            return "C_FIELD_MAPPING_FAILURE"
        if not has_field:
            return "C_FIELD_MAPPING_FAILURE"
        return "B_ENTITY_EXTRACTION_FAILURE"

    # Parser returned something but status was NOT_FOUND
    if parsed and status == "NOT_FOUND":
        # Check if the record actually exists in DB
        return "D_STRUCTURED_RECORD_NOT_FOUND"

    # Parser returned something but status was AMBIGUOUS
    if parsed and status == "AMBIGUOUS":
        # Usually missing tower specification
        return "B_ENTITY_EXTRACTION_FAILURE"

    # Wrong value returned
    if parsed and status == "SUCCESS":
        return "E_STRUCTURED_RETRIEVAL_FAILURE"

    # Fell to RAG
    if route == "rag":
        return "F_RAG_RETRIEVAL_FAILURE"

    return "P_OTHER"


# ---- Main runner ----
def run_benchmark():
    QUESTIONS_FILE = r"C:\3EH\ExpoDesignAI - Copy\tests\evaluation\phase13_questions.json"
    OUTPUT_DIR = r"C:\3EH\ExpoDesignAI - Copy\tests\evaluation"

    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions = json.load(f)

    results = []
    traces = []
    total = len(questions)

    print(f"Phase 13 Forensic Benchmark")
    print(f"Total questions: {total}")
    print("=" * 70)

    for i, q in enumerate(questions):
        qid = q["id"]
        question = q["question"]
        expected = q["expected_answer"]
        exp_type = q["expected_type"]

        # Stage 1: Classify
        classifier_result = sq.classify_query(question)

        # Stage 2: Parse
        parsed = sq.robust_parse_query(question)

        # Stage 3: Run through production pipeline
        t0 = time.perf_counter()
        resp, latencies = sq.query_document(
            question=question,
            project_id=1,
            retrieve_context_func=mock_retrieve,
            call_qwen_func=mock_qwen,
            user_context={}
        )
        elapsed = time.perf_counter() - t0

        status = resp.get("status", "")
        route = resp.get("route", "")
        answer = resp.get("answer", "")
        provenance = resp.get("provenance", [])
        calculation = resp.get("calculation", {})

        # Evaluate correctness
        passed = False
        if exp_type == "NUMERIC":
            passed = check_numeric(expected, answer, provenance)
            if not passed:
                passed = check_numeric_in_answer(expected, answer)
            # Also check calculation result
            if not passed and calculation:
                calc_result = calculation.get("result")
                if calc_result is not None:
                    try:
                        if abs(float(calc_result) - float(str(expected).replace(",",""))) < 0.5:
                            passed = True
                    except (ValueError, TypeError):
                        pass
        elif exp_type == "NOT_FOUND":
            passed = check_not_found(status, answer)
        elif exp_type == "MULTI_VALUE":
            passed = check_multi_value(expected, provenance)
        elif exp_type == "TEXT":
            passed = str(expected).lower() in str(answer).lower()

        # Classify failure
        failure_class = ""
        if not passed:
            trace_info = {
                "classifier_result": classifier_result,
                "parsed": parsed,
                "status": status,
                "route": route,
            }
            failure_class = classify_failure(q, trace_info)

        result = {
            "id": qid,
            "category": q["category"],
            "question": question,
            "expected_answer": expected,
            "expected_type": exp_type,
            "actual_answer": answer[:300],
            "actual_status": status,
            "actual_route": route,
            "passed": passed,
            "failure_class": failure_class,
            "classifier_result": classifier_result,
            "parsed_towers": parsed.get("towers", []) if parsed else None,
            "parsed_levels": parsed.get("levels", []) if parsed else None,
            "parsed_fields": parsed.get("fields", []) if parsed else None,
            "parsed_calc": parsed.get("calc") if parsed else None,
            "provenance_count": len(provenance),
            "latency_ms": round(elapsed * 1000, 2),
            "deterministic": q.get("deterministic", True),
            "paraphrase_group": q.get("paraphrase_group", ""),
        }
        results.append(result)

        trace_entry = {
            "id": qid,
            "question": question,
            "classifier_result": classifier_result,
            "parsed": parsed,
            "resp_status": status,
            "resp_route": route,
            "resp_answer": answer[:500],
            "resp_provenance": provenance[:3],
            "resp_calculation": calculation,
            "resp_warnings": resp.get("warnings", []),
            "latencies": latencies,
        }
        traces.append(trace_entry)

        mark = "PASS" if passed else "FAIL"
        if (i+1) % 20 == 0 or not passed:
            print(f"[{mark}] {qid}: {question[:55]}... -> {status}/{route}")

    # ---- Compute summary ----
    total_passed = sum(1 for r in results if r["passed"])
    total_failed = total - total_passed

    cats = {}
    for r in results:
        c = r["category"]
        if c not in cats:
            cats[c] = {"total": 0, "passed": 0, "failed": 0}
        cats[c]["total"] += 1
        if r["passed"]:
            cats[c]["passed"] += 1
        else:
            cats[c]["failed"] += 1

    failure_dist = {}
    for r in results:
        if not r["passed"] and r["failure_class"]:
            fc = r["failure_class"]
            failure_dist[fc] = failure_dist.get(fc, 0) + 1

    # Paraphrase consistency
    para_groups = {}
    for r in results:
        pg = r.get("paraphrase_group", "")
        if pg:
            if pg not in para_groups:
                para_groups[pg] = []
            para_groups[pg].append(r["passed"])

    para_consistent = 0
    para_total = 0
    for pg, statuses in para_groups.items():
        para_total += 1
        if all(statuses) or not any(statuses):
            para_consistent += 1

    summary = {
        "total_questions": total,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "accuracy_pct": round(total_passed / total * 100, 1) if total else 0,
        "by_category": {c: {
            "total": v["total"],
            "passed": v["passed"],
            "failed": v["failed"],
            "accuracy_pct": round(v["passed"] / v["total"] * 100, 1) if v["total"] else 0
        } for c, v in sorted(cats.items())},
        "failure_distribution": dict(sorted(failure_dist.items())),
        "paraphrase_consistency": {
            "total_groups": para_total,
            "consistent_groups": para_consistent,
            "consistency_pct": round(para_consistent / para_total * 100, 1) if para_total else 0
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # ---- Write outputs ----
    # 1. phase13_results.json
    with open(os.path.join(OUTPUT_DIR, "phase13_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    # 2. phase13_results.csv
    with open(os.path.join(OUTPUT_DIR, "phase13_results.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "category", "question", "expected_answer", "expected_type",
            "actual_answer", "actual_status", "actual_route", "passed",
            "failure_class", "classifier_result", "latency_ms"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({k: r[k] for k in writer.fieldnames})

    # 3. phase13_summary.json
    with open(os.path.join(OUTPUT_DIR, "phase13_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 4. phase13_pipeline_trace.json
    with open(os.path.join(OUTPUT_DIR, "phase13_pipeline_trace.json"), "w", encoding="utf-8") as f:
        json.dump(traces, f, indent=2, ensure_ascii=False, default=str)

    # 5. phase13_failure_distribution.csv
    with open(os.path.join(OUTPUT_DIR, "phase13_failure_distribution.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["failure_type", "count", "percentage"])
        for fc, cnt in sorted(failure_dist.items()):
            writer.writerow([fc, cnt, round(cnt / total_failed * 100, 1) if total_failed else 0])

    # 6. phase13_failure_report.md
    with open(os.path.join(OUTPUT_DIR, "phase13_failure_report.md"), "w", encoding="utf-8") as f:
        f.write("# Phase 13 - Forensic Benchmark Failure Report\n\n")
        f.write(f"**Date:** {summary['timestamp']}\n\n")
        f.write("## Executive Summary\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Total Questions | {total} |\n")
        f.write(f"| Passed | {total_passed} |\n")
        f.write(f"| Failed | {total_failed} |\n")
        f.write(f"| Accuracy | {summary['accuracy_pct']}% |\n\n")

        f.write("## Category Breakdown\n\n")
        f.write("| Category | Total | Passed | Failed | Accuracy |\n|---|---|---|---|---|\n")
        for c, v in sorted(summary["by_category"].items()):
            f.write(f"| {c} | {v['total']} | {v['passed']} | {v['failed']} | {v['accuracy_pct']}% |\n")

        f.write("\n## Failure Distribution\n\n")
        f.write("| Failure Type | Count | % of Failures |\n|---|---|---|\n")
        for fc, cnt in sorted(failure_dist.items()):
            pct = round(cnt / total_failed * 100, 1) if total_failed else 0
            f.write(f"| {fc} | {cnt} | {pct}% |\n")

        f.write("\n## Paraphrase Consistency\n\n")
        f.write(f"- Total paraphrase groups: {para_total}\n")
        f.write(f"- Consistent groups (all pass or all fail): {para_consistent}\n")
        f.write(f"- Consistency: {summary['paraphrase_consistency']['consistency_pct']}%\n\n")

        f.write("## Failed Questions Detail\n\n")
        for r in results:
            if not r["passed"]:
                f.write(f"### {r['id']}: {r['question']}\n\n")
                f.write(f"- **Category:** {r['category']}\n")
                f.write(f"- **Expected:** {r['expected_answer']}\n")
                f.write(f"- **Actual Status:** {r['actual_status']}\n")
                f.write(f"- **Actual Route:** {r['actual_route']}\n")
                f.write(f"- **Actual Answer:** {r['actual_answer'][:200]}\n")
                f.write(f"- **Classifier:** {r['classifier_result']}\n")
                f.write(f"- **Parsed Towers:** {r['parsed_towers']}\n")
                f.write(f"- **Parsed Levels:** {r['parsed_levels']}\n")
                f.write(f"- **Parsed Fields:** {r['parsed_fields']}\n")
                f.write(f"- **Failure Class:** {r['failure_class']}\n")
                f.write(f"- **Latency:** {r['latency_ms']}ms\n\n")

    # ---- Print summary ----
    print("\n" + "=" * 70)
    print("  PHASE 13 FORENSIC BENCHMARK RESULTS")
    print("=" * 70)
    print(f"  Total:    {total}")
    print(f"  Passed:   {total_passed}")
    print(f"  Failed:   {total_failed}")
    print(f"  Accuracy: {summary['accuracy_pct']}%")
    print()
    print("  By Category:")
    for c, v in sorted(summary["by_category"].items()):
        print(f"    {c}: {v['passed']}/{v['total']} ({v['accuracy_pct']}%)")
    print()
    print("  Failure Distribution:")
    for fc, cnt in sorted(failure_dist.items()):
        pct = round(cnt / total_failed * 100, 1) if total_failed else 0
        print(f"    {fc}: {cnt} ({pct}%)")
    print()
    print(f"  Paraphrase Consistency: {para_consistent}/{para_total}")
    print("=" * 70)

    return summary, results


if __name__ == "__main__":
    run_benchmark()
