# Release remediation — 10 October 2026

Decision: **NO-GO for unrestricted production.** The verified answer fixes are deployed locally; remaining certification work is listed below. This is a targeted forensic remediation, not a claim that every code path has been certified.

Production Security = **UNCHANGED** by this remediation. Authentication configuration and default password were not edited. BIM/CAD/Reporting workflows = **SKIPPED**.

## 1. Defects found and first incorrect stages

| Defect | First incorrect stage established by inspection/reproduction |
|---|---|
| Combined retail/F&B total was labelled as F&B total | STRUCTURED_EXTRACTION |
| Composite table headers lost quantity units; FAR could be associated with area units | STRUCTURED_EXTRACTION / SEMANTIC_RESOLUTION, respectively |
| Generic floor-area question silently selected one of several metrics | SEMANTIC_RESOLUTION |
| Allowed/proposed comparison returned only one operand | QUERY_PARSER |
| Memory could verify a quote without verifying its asserted relationship; vision entered native verification text | EVIDENCE_GATE |
| Old source-hash memory rows could survive replacement | STRUCTURED_DATABASE |
| Focused retrieval identity relied on filename without folder identity | DOCUMENT_RESOLUTION |
| Absence questions could be answered from narrow retrieved excerpts | RETRIEVAL |
| Approval and unsupported affirmative units escaped validation | ANSWER_VALIDATION |
| Empty baseline migration could not provision the existing schema | STRUCTURED_DATABASE |

An isolated consultant-label encoding artifact remains (Façade). Its first incorrect stage has **not been isolated**; no speculative stage assignment is made.

## 2. Fixes applied

- Preserved table/category relationships and explicit units, including parking headers.
- Added source-derived category, plot, FAR and floor-metric resolution. FAR is a ratio. Generic floor area returns labelled BUA/GFA/NSA.
- Added deterministic allowed/proposed comparisons with Decimal operands, units, source/revision/qualification matching, formula and citations. Missing/conflicting/incompatible operands are rejected.
- Exact answers reject truncated/incomplete sidecars and stale source hashes.
- Memory verifies native page evidence and the claim within its quote, excludes vision from native verification, and revalidates current hashes and page identity.
- Focused retrieval requires filename and folder identity. Bounded native-document inspection handles absence questions, refuses incomplete coverage and discloses image/compliance limitations.
- Strengthened approval and quantity validation without treating model output as engineering authority.
- Replaced the empty baseline with a frozen schema and added a separate recycle-bin foreign-key migration.

The audited data-sheet index was backed up and republished: 217 source chunks, 2,025 project vectors, misleading combined-total chunk absent. The local service was restarted successfully. Other document indexes were not comprehensively rebuilt or certified.

The new schema migration was tested on isolated databases; **live migration remains pending**. The live database was not certified as being at the new migration head.

## 3. Regression tests added

`tests/test_evidence_remediation.py`: nine tests cover source/category relationships, units, FAR, floor metrics, comparisons, memory verification, focused identity, incomplete coverage and stale/truncated sources.

`tests/test_deployment_schema.py`: empty-database upgrade, synthetic populated upgrade, schema comparison, data preservation, foreign-key integrity and downgrade.

Existing ingestion/recovery fixtures were repaired to supply current dependencies. Expected assertions were not changed.

## 4. Verification results

- Selected Python core suite: **98 passed**, zero failures.
- Python hardening suite: **10 passed**, zero failures.
- JavaScript busy-response test: **passed**.
- Ten source-grounded data-sheet questions through the actual answer route: completed with supported substantive answers.
- Five post-restart HTTP checks: HTTP 200 and supported answers for FAR, floor metrics, F&B count, GFA comparison and missing fire-design information.
- Live SQLite integrity: `ok`; existing foreign-key violations: zero.

This is **108 Python tests plus one JavaScript test**, not every repository test. BIM/CAD workflow suites and broader nested evaluation suites were not executed. Ten questions on one source do not establish a general accuracy percentage.

Evidence: `tests.log`, `hardening.log`, `final-route-results.json`, `live-results.json`, `live-runtime.json`, `verified-source-hashes.json` and `publication.json` in this directory. Intermediate preliminary results are not counted as final verification.

## 5. Failures and stage attribution

The reproduced answer defects above passed their targeted regression checks after remediation. Clean-machine certification and full pipeline stress/recovery qualification are incomplete, rather than demonstrated passing stages. No first incorrect stage is invented for checks that were not performed.

## 6. Performance and recovery

Synthetic deterministic answer tests used concurrency limits 4, 8, 16, 32 and 64: **248/248 correct**. P95 latency in milliseconds was 220.47, 6.75, 12.97, 16.04 and 21.82 respectively. The first group includes cold initialization; these are not comparable steady-state model benchmarks.

This measured an in-process exact-answer path only. It does **not** certify HTTP, uploads, OCR, vision, embeddings, retrieval, GPU capacity or queue behaviour. Process CPU, before/after RSS and disk I/O were recorded in `synthetic-load.json`; peak RAM, GPU/VRAM, production queue depth and database contention were not measured. The live absence answer took approximately 33 seconds; this is an individual observation, not a capacity result.

Selected synthetic ingestion/publication/recovery regressions passed. Empty and populated snapshot migrations passed integrity checks with zero foreign-key violations. These do not replace process-kill/power-loss tests across every processing stage. Full interruption testing during OCR, vision, embeddings and index publication remains a release requirement.

## 7. Clean-machine result

**NOT CERTIFIED.** A fresh isolated Python environment on this host had no provisioned dependencies. No packages or models were downloaded or installed. This demonstrates that offline provisioning has not been validated; it does not mean the working host lacks its installed dependencies. A separate clean-machine install, offline startup, upload, query and restart were not demonstrated. See `deployment-check.json`.

## 8. Remaining blockers

1. Validate the existing offline deployment bundle on a clean machine with provisioned dependencies/models and no network access.
2. Run progressive full-pipeline synthetic load tests, including uploads/OCR/vision/embeddings/retrieval, with hardware, queues and database/index metrics.
3. Complete real interruption/restart/retry qualification at each ingestion stage; prove partial documents never become READY and publication is consistent.
4. Expand held-out document evaluation across scanned pages, drawings, tables, revisions, approval conflicts, exact identifiers and project isolation.
5. Apply the tested schema migration during backed-up maintenance and validate the live schema afterward.
6. Check other stored documents/indexes for legacy extraction defects and investigate the remaining encoding artifact.

The bounded evidence inspection added here is not a complete autonomous REA-style agent. Agent behaviour was not independently certified.

## 9. Final release decision

The audited defects have concrete fixes, regression evidence and successful local deployment checks. **Unrestricted production remains NO-GO** until the blockers above are evidenced. Controlled internal evaluation can continue with human engineering review and the existing evidence gates.

Database backups and test snapshots in this directory may contain private project information; distribute this report separately from those artifacts.
