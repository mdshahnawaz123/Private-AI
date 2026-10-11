# Remaining release checks — 10 October 2026

This report supersedes the pending migration and verification statements in the earlier remediation report. Production Security = UNCHANGED. BIM/CAD/Reporting = SKIPPED. Clean-machine offline installation = UNCHANGED; NOT CERTIFIED, excluded by request.

## 1. Defects found and first incorrect stage

| Defect | First incorrect stage |
|---|---|
| Numeric data rows containing Proposed classified as headers | STRUCTURED_EXTRACTION |
| Combined commercial total inherited residential table scope | STRUCTURED_EXTRACTION |
| Revision No label mistaken for a revision value; inline status missed | SEMANTIC_RESOLUTION |
| Explicit project-code question could receive another project's selected-document value | DOCUMENT_RESOLUTION |
| Filename revision treated as source revision | REVISION_RESOLUTION |
| Re-upload registered another active document row despite stable chunks | STRUCTURED_DATABASE |
| Pressure units Pa/psi not covered by quantity validation | ANSWER_VALIDATION |
| Withheld answer displayed excessive confidence | ANSWER_VALIDATION |
| Previous index generations accumulated without retention bound | INDEX |
| Model cites project code instead of retrieved filename | LLM_REASONING; CITATION_VALIDATION correctly rejects |

## 2. Fixes applied

Fixed native revision/status parsing, project-code evidence matching, deterministic disposition answers, numeric-row classification, parent table scope, pressure-unit checks, refusal confidence, bounded index-generation retention and transactional document registration reuse. No expected source answers or evidence gates were weakened. Existing legacy duplicate rows were not deleted.

The tested schema migration was applied after a SQLite backup; user/project/document row fingerprints were preserved. Live schema is c3d4e5f6a7b8. The corrected datasheet index was backed up and republished: 218 source chunks, 2026 project vectors. Source SHA-256 remained 905a5d07c5b310110d7de330dd7ac7d37f695df7b760db8efd5cb64f9429878f. Live service restarted successfully on 8090.

A stricter citation-repair prompt was tried but still failed the synthetic pressure question. That prompt experiment was reverted. The model defect remains visible as a safe refusal, not a verified answer.

## 3. Tests added

Additional release regressions cover table scope, Proposed rows, source revisions, conflicting revisions, status, project scope, quantity units, refusal confidence and index retention. Database regression covers repeated registration and READY invalidation. Four actual child-process interruption tests cover upload staging, SQLite commit, index publication and durable job ownership. Eight fault-injected pipeline boundaries cover extraction through database/index publication. These are separate from real GPU/process interruption at every boundary, which was not demonstrated.

## 4. Test results

Final run: **127 Python tests passed, zero failed; JavaScript busy-stream regression passed**. See ../remaining-release-checks-2026-10-10/suite/results.json and individual logs. A sandboxed repeat timed out in test_audit_hardening; the subsequent complete run with normal local process access passed. Top-level tests/test_*.py were exercised. This is not a claim that every archived, nested or excluded BIM test ran.

The live 20-question source-key evaluation found one false residential conflict; its corrected live recheck returns **804 units, Revision 3, page 1**. The original evaluation and post-fix result are preserved separately. This small evaluation is not an independent held-out engineering benchmark.

## 5. Performance

Synthetic isolated workloads only; production project PDFs were not used for stress load. Deterministic questions at concurrency 4/8/16/32/64: 124/124 correct; P95 seconds 0.828/1.297/2.437/5.141/10.188, including client setup overhead. Initial four uploads and subsequent batches 8/16/32/64 returned HTTP 200 and drained their queues. Extraction, embedding and publication remained serialized; these results do not demonstrate 64 simultaneous OCR/vision operations.

Model-backed retrieval/questions: 4/4, 8/8 and 16/16 supported answers. At 32 concurrent requests, 16 succeeded and 16 returned HTTP 503 busy. Scaling stopped there; 64 model-backed requests were not tested. One actual image-only PDF exercised OCR/vision and remained READY_WITH_WARNINGS with review-required/interpreted evidence.

425 resource samples: server/child peak RSS approximately 3.87 GiB; host CPU peak 100%; minimum available host RAM approximately 35.7 GiB; queue peak 61; host GPU peak VRAM 7702 MiB and utilization 100%. GPU figures are host-wide. Disk free-space change approximately -297 MiB includes concurrent work and is not exclusive workload consumption. Disk throughput and SQLite lock latency were not measured.

## 6. Recovery and integrity

Actual killed synthetic processes retained old upload contents, rolled back an uncommitted READY transition, loaded the prior complete index generation and replayed a durable job once with bounded attempts. Fault-injected stages did not publish READY; retries completed. Repeated identical source publication kept chunk counts stable with no identical duplicate chunks. Database registration reuse has regression coverage; a fresh HTTP re-upload against the final deployed registration code remains unverified.

Read-only live audit: two active PDF sources and one project index had no source/manifest integrity issues. SQLite integrity was OK and foreign-key violations zero. This does not certify extraction accuracy of all pages. Historical failed jobs remain historical failures; retry budgets were not reset.

## 7. Clean-machine result

NOT CERTIFIED. Offline installation was deliberately left unchanged and not retested, as requested. No cloud calls, downloads or package installations were performed by these checks.

## 8. Remaining blockers

- Model citation reliability: the synthetic AHU pressure question is withheld after repeated incorrect filename citations, despite the correct value existing in evidence.
- Independent held-out engineering accuracy evaluation, broader conflicting-authority scenarios and manual review of uncertain image/OCR pages.
- Concurrent OCR/vision capacity, disk/locking measurements and longer sustained load remain uncharacterized.
- Real interruption at every model/GPU stage and final HTTP re-upload registration verification remain incomplete.
- Clean-machine certification remains outside this run.

## 9. Release decision

**NO-GO for unrestricted production.** Controlled internal evaluation with engineering review and existing evidence gates can continue. Demonstrated model-request capacity is 16 concurrent requests under this synthetic workload; 32 encountered backpressure. The successful deterministic 64-request result must not be presented as general model capacity.

Backups and snapshots may contain private project data. Distribute this report separately from those artifacts.
