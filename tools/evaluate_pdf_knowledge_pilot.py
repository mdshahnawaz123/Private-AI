"""Evaluate the isolated package engine against manually transcribed PDF facts."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engines.pdf_knowledge_engine import PDFKnowledgeEngine, lookup, validate_package


def normalized(value):
    return " ".join(str(value).split()).casefold()


def has_row(evidence, expected):
    for row in evidence.get("grid", []):
        # Empty source cells are preserved in the package. Ignore them only for
        # this assertion of an ordered, adjacent label/value tuple in one row.
        cells = [normalized(c) for c in row if normalized(c)]
        want = [normalized(c) for c in expected]
        if any(cells[i:i + len(want)] == want for i in range(len(cells) - len(want) + 1)):
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf-knowledge-pilot")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dataset = ROOT / "tests/fixtures/pdf_knowledge_pilot_v1.json"
    labels = json.loads(dataset.read_text(encoding="utf-8"))
    engine = PDFKnowledgeEngine(args.output / "packages")
    packages, records, builds = {}, {}, []
    for project, spec in labels["documents"].items():
        source = args.source_root / spec["filename"]
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != spec["sha256"]:
            raise ValueError("Independent ground-truth source hash mismatch: " + source.name)
        existing = {p.parent.resolve() for p in (args.output / "packages").glob("*/*/manifest.json")}
        before = time.perf_counter()
        package = engine.build(source, project=project)
        elapsed = time.perf_counter() - before
        manifest = validate_package(package, project=project)
        packages[project] = package
        records[project] = {e["id"]: e for e in json.loads((package / "db/structured.json").read_text(encoding="utf-8"))}
        builds.append({"project": project, "package": str(package.resolve()), "pages": manifest["pages"],
                       "evidence_records": manifest["evidence_records"], "review_required_pages": manifest["review_required_pages"],
                       "build_or_cache_validation_seconds": round(elapsed, 4),
                       "cache_hit": package.resolve() in existing})
    results = []
    for case in labels["cases"]:
        before = time.perf_counter()
        result = lookup(packages[case["project"]], case["question"], project=case["project"])
        elapsed = time.perf_counter() - before
        supported = []
        for match in result["matches"]:
            if match["page"] != case["page"]:
                continue
            evidence = records[case["project"]][match["evidence_id"]]
            if case.get("table_heading") and normalized(case["table_heading"]) not in normalized(evidence["quote"]):
                continue
            if has_row(evidence, case["row"]) if "row" in case else normalized(case["quote"]) in normalized(evidence["quote"]):
                supported.append(match["evidence_id"])
        results.append({"id": case["id"], "question": case["question"], "pass": bool(supported),
                        "supporting_evidence_ids": supported, "lookup_seconds": round(elapsed, 4),
                        "result": result})
    benchmark = ROOT / "output/claim-source-eval/benchmark_v1.json"
    baseline_hash = hashlib.sha256(benchmark.read_bytes()).hexdigest()
    if baseline_hash != "551c89d28d4e6af733ce769fc220bf5ad9257386b90ffe3771ad819f1fb9429b":
        raise ValueError("Frozen claim benchmark changed")
    spec = importlib.util.spec_from_file_location("frozen_claim_eval", ROOT / "output/claim-source-eval/evaluate_v1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RESULTS = args.output / "frozen-claim-results.json"
    module.SUMMARY = args.output / "frozen-claim-report.md"
    module.main()
    baseline = json.loads(module.RESULTS.read_text(encoding="utf-8"))
    payload = {"version": "1.0.0", "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
               "python": sys.version, "source_ground_truth": labels["ground_truth"], "packages": builds,
               "case_count": len(results), "passed": sum(c["pass"] for c in results),
               "failed": sum(not c["pass"] for c in results), "cases": results,
               "claim_benchmark_sha256": baseline_hash, "claim_benchmark_counts": baseline["counts"],
               "coverage": "Native extraction, artifact generation and source-excerpt retrieval only; no real-model or live-chat certification"}
    (args.output / "real-pdf-results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"], "packages": builds}, indent=2))
    return int(payload["failed"] > 0 or baseline["counts"]["false_accept"] > 0 or baseline["counts"]["false_reject"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
