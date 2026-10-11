# OpenCompany Local Engineering AI — current code audit

Date: 2026-10-10. Decision: **NO-GO for unrestricted engineering production use.**

This is a targeted current-source review and local synthetic regression assessment, not a certification of every workflow. Production code and security configuration were not changed. BIM/CAD/Reporting/agent workflows were excluded. No model/package downloads, installations or cloud calls were performed. No fresh load test or clean-machine deployment was performed.

## What is already present

The existing architecture has native PDF extraction, geometry-derived tables, conditional OCR/vision, structured SQLite records, FAISS, BM25 hybrid retrieval, local reranking, deterministic answer routes, publication checks, durable ingestion jobs, source hashing, index publication/recovery checks and offline backup/restore tooling. There is a Windows dependency lockfile and Docker deployment scaffolding. These should be strengthened rather than replaced without evidence.

Document memory now also participates in answering, although its module introduction still says query-time behavior is not implemented. Its configuration initially scopes ingestion to two filenames; this is a pilot, not broad document coverage.

## Confirmed current defects and important risks

| Priority | Finding and evidence | First incorrect stage | Required closure |
|---|---|---|---|
| P0 | `document_memory._page_blob` combines native text, tables and vision. `verify_fact` returns VERIFIED for quote containment without retaining extraction origin. A synthetic page containing only vision text returned VERIFIED. | STRUCTURED_EXTRACTION | Retain native/OCR/vision provenance per span; quote matching must not upgrade interpreted vision into verified engineering evidence. |
| P0 | Memory verifies the quote, not the relationship between quote and generated claim. A synthetic quote `Allowed area 100 sqm.` with a claim `Proposed area 100 sqm.` returned VERIFIED; the publication guard also accepted that claim. | STRUCTURED_EXTRACTION | Validate property, entity, qualifier, value and unit against the same source relationship; abstain on mismatches. |
| P0 | Publication guard accepts units absent from evidence when no recognized conflicting pair exists. `Plot area 100 sqm` passed against evidence `Plot area 100`. | ANSWER_VALIDATION | Require affirmative unit provenance, including linked table headers; preserve unknown units rather than invent them. |
| P0 | Existing approval regressions fail: `Approved.` can promote conditional approval, and `The design is approved.` passes without sufficient authority. The narrowed approval-context expression omits these formulations. | ANSWER_VALIDATION | Enforce authority and qualification across all status assertions, not just selected surrounding words. |
| P1 | Memory stores `source_sha256`, but lookup does not compare it with the current source. Rebuild retains old facts omitted by the new extraction, even across changed source hashes. | STRUCTURED_DATABASE | Retain omitted facts only within an identical immutable source generation; invalidate all stale generations on source changes. |
| P1 | Memory lookup accepts a quote found on any page while returning the stored page citation. Its cache reads the extraction sidecar, not independent current-PDF evidence. | PAGE_RESOLUTION / CITATION_VALIDATION | Bind evidence to current source hash and exact resolved page; repair attribution or refuse. |
| P1 | Normal RAG retrieval still receives project/query/k/user, with no focused-document argument. A focused excerpt is added later. Memory and exact routes have focus restrictions, but ordinary RAG remains project-wide. | DOCUMENT_RESOLUTION | Apply document identity restrictions before candidate retrieval and ranking; test same-project documents with conflicting facts. |
| P1 | GFA exact-answer selection chooses `proposed` when the question contains both proposed and allowed, so a comparison can become a single-value answer. | QUERY_PARSER | Parse comparison intent and resolve both operands, units, source scopes and uncertainty before deterministic comparison. |
| P1 | Existing calculation regression receives None instead of UNSUPPORTED; parking conflict regression receives NOT_FOUND instead of AMBIGUOUS. | QUERY_PARSER / SEMANTIC_RESOLUTION | Reconcile real intent handling with existing regression contracts without changing expected answers merely to pass. Verify unsupported calculations cannot reach free-form arithmetic. |
| P1 | Two ingestion/recovery tests error because their fake database object lacks `set_progress`. They do not reach the publication/recovery assertions. | Test harness; runtime failure stage NOT ESTABLISHED | Update fixtures for the current interface and rerun the original assertions. Do not treat these errors as proof that live recovery is broken or passing. |
| P1 | Alembic baseline upgrade is empty; following migrations assume existing tables. Startup also uses create_all. Fresh deployment and existing-schema adoption need explicit validation. | STRUCTURED_DATABASE | Test new empty database, upgrade from prior releases, migration ownership and rollback/restore on disposable data. |

Current source locations: `intelligence/document_memory.py` (page rendering ~34, verification ~396, retained-memory rebuild ~519, cache ~583, lookup ~607 and ~919); `intelligence/answer_guard.py` (~162–196); `main.py` (~3275–3330); `intelligence/exact_answers.py` (~116 and calculated_answer ~231); `alembic/versions/ccc9bcc47ca6_initial.py`.

## Verification performed

The focused Python regression run executed 82 tests: **76 passed, 3 failed, 3 errors**. A separate hardening run passed another 9 tests. Combined completed results: **91 tests, 85 passed, 3 failed, 3 errors**. Full details are in `tests.log`, `tests.json` and `hardening-tests.log` next to this report. Drawing/BIM/CAD/Reporting/agent/cowork tests were excluded. The health-route test did not complete: a bounded separate run timed out after 45 seconds while Windows asyncio was creating a local socketpair in this sandbox. This is not a demonstrated application health-route failure. Nested evaluation suites and JavaScript tests were not run in this assessment.

Initial execution hit sandbox temporary-directory permissions. The reported run instead used an isolated workspace temporary directory. Those initial permission failures are not counted as application defects. The earlier combined run was interrupted after it stopped producing output; it is not a completed result.

Four small direct synthetic probes confirmed vision-only memory promotion, claim/quote relationship mismatch, acceptance of an unsupported unit, and acceptance of the same relationship mismatch by publication validation. They required no live model calls or source document edits.

The October 8 real-document forensic audit remains historical evidence, not a fresh model accuracy measurement after the memory changes. Its 14/20 content and 13/20 grounding results must not be presented as today's score. A new end-to-end benchmark is required after remediation.

## Recommended improvements, in order

1. **Close evidence and semantics defects first.** Use immutable document identity and extraction generations; preserve source hash, page, bounding box, table/header/cell relationships, entity, revision, status, units and qualifiers. Separate processing completion from engineering verification.
2. **Make all answer routes obey one publication contract.** Exact answers, memory and RAG should share scope, evidence, revision, calculation and citation checks. A route should not silently bypass stronger validation elsewhere.
3. **Add memory-specific regressions.** Cover vision-only quotes, wrong properties with the same number, changed hashes, omitted facts after revisions, duplicate filenames in different folders, ambiguous candidates, wrong-page quotes, missing units and partial extraction. No dedicated memory test module appeared in the reviewed top-level regression inventory.
4. **Add an engineer review screen.** Show the source crop and extracted relationship side by side, with interpreted/ambiguous/review-required states, reviewer identity and review history. Accepting an OCR transcription must not automatically approve a design.
5. **Add a trace for each answer.** Record selected route, source generation, candidates, rejected evidence, resolved scope, final citations, calculation operands/formula and abstention reason. Make the first incorrect stage visible for diagnosis.
6. **Strengthen the evaluation gate.** Keep independently reviewed ground truth immutable; evaluate correctness, completeness, page citation, qualifiers, units and refusal separately. Hold out unseen document templates and adversarial conflicting revisions. Compare memory-enabled and memory-disabled behavior on the same sources.
7. **Certify operation on synthetic workloads.** Exercise 4/8/16/32/64 concurrency where hardware permits; measure p50/p95/p99 latency, errors, queue depth, RAM/VRAM, CPU, disk and SQLite contention. Interrupt each ingestion stage on disposable instances; prove partial documents never become ready and generations remain consistent.
8. **Certify offline deployment and recovery.** Prepare versioned dependencies and model artifacts with checksums; verify startup, upload, extraction, query, restart, backup/restore and schema upgrades on a clean machine without downloads. Docker scaffolding and a lockfile alone do not establish this.

Optional additions after release blockers: source-grounded document comparison, a coverage view that distinguishes blank fields from unread fields, and a calculation explanation card exposing operands, units, formula and citations. Reuse existing modules and inspect their current UI coverage before implementing duplicates.

## Release recommendation

Keep the architecture for now. Prioritize trustworthy source relationships and validation rather than adding larger models, a new vector database or another OCR engine. Such replacements should require measured improvements on held-out documents and resource budgets.

Current production readiness is **not demonstrated**. Performance/recovery recertification is pending. Clean-machine deployment is **NOT CERTIFIED**. Production Security = **UNCHANGED**. BIM/CAD/Reporting = **SKIPPED**.
