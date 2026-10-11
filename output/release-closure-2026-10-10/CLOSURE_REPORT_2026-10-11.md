# Local Engineering AI — release-gap closure, 11 October 2026

Scope: existing document ingestion, OCR/vision evidence handling, retrieval, engineering Q&A, recovery and bounded load. Production Security = UNCHANGED by this work. BIM/CAD/Reporting workflows = SKIPPED. Clean-machine installation = EXCLUDED by request; its certification remains NOT CERTIFIED.

This report supersedes the open citation, re-upload and OCR-recovery findings in the previous release-check report. It does not certify autonomous engineering decisions.

## 1. Defects found / first incorrect stage

| Finding | First incorrect stage | Final disposition |
|---|---|---|
| Model substituted project identifiers for source filenames, or emitted malformed citation wrappers | LLM_REASONING | Server-assigned source handles and exact syntax normalization; existing validation still applies |
| Correct source values could become unavailable after generated prose failed citation checks | ANSWER_VALIDATION | Conservative attributed native quotation fallback, only for an unambiguous matching identifier/property |
| A different equipment item's value on the same page could satisfy a page-wide numeric check | EVIDENCE_GATE | Explicit native entity/property/value associations now checked |
| Generated answers omitted source dispositions | ANSWER_VALIDATION | Native revision/status attached independently of generated prose |
| “Review” could be parsed as a revision because the label matcher accepted a word prefix | REVISION_RESOLUTION | Revision label must end at a word boundary |
| Interrupted jobs could exhaust retries without invalidating previously committed readiness | STRUCTURED_DATABASE | Restart invalidates interrupted job readiness before replay or terminal failure; invalidation failure stops startup |
| Unit checks did not cover common electrical, flow and thermal substitutions; SI prefix case could collapse | ANSWER_VALIDATION | Expanded unit matching, with milli/mega distinction |
| Repeated upload had previously duplicated the document row | STRUCTURED_DATABASE | Earlier transactional registration fix now verified through actual HTTP re-upload |

No project answers were hardcoded. Expected source answers were not changed. Unknown source handles, wrong pages, conflicting values, wrong units, absent identifiers and unverified visual observations still fail validation.

## 2. Fixes applied

The fixes are in the existing answer validation, source semantics, request handling and durable queue. New small modules manage request-local citation identity and a native quotation fallback. The fallback quotes source wording and retains qualifications; it does not invent or silently repair a source attribution. Ambiguous statements, revision/approval requests and unsupported calculations do not use that fallback.

The application was restarted using its existing local startup script after confirming that production ingestion had no active jobs. Default administrator credentials, authentication configuration, model installation and offline deployment were not changed by this work.

## 3. Tests added

Regression coverage now includes exact citation-handle/page resolution, malformed citation syntax, rejection of foreign handles and visual-only support, retained TBC status, “review” versus revision, entity/value mismatches, electrical/flow/thermal units and SI prefixes, ambiguous source quotations, missing authority, newer Draft versus older Approved documents, and interrupted-job invalidation failures.

Real integration workloads used newly generated synthetic PDFs: six distinct native documents with predetermined values and dispositions, plus image-only copies. The source key was written before ingestion. This is a source-key evaluation, not an independent engineer-certified benchmark.

## 4. Tests passed / failed

- **144 Python tests passed; zero failed**, across all 37 top-level `tests/test_*.py` modules. JavaScript busy-stream regression passed. Archived, nested and excluded BIM workflows were not represented as tested.
- **12/12 new native-document questions passed** across pressure, width, diameter, height and thickness.
- **6/6 final restart checks passed**: supported pressure; height retaining Revision C/TBC; missing equipment identifier refusal; Draft versus construction approval; wrong-project refusal; and withholding unverified scan-derived quantities.
- The original AHU pressure failure now returns 250 Pa with `native-a.pdf`, page 1.
- Actual repeated HTTP upload: active document count **6 before / 6 after**.
- Final synthetic index: **114 vectors, zero duplicate chunks**; six native sources retain one chunk each, and twelve scan sources retain nine each.
- SQLite integrity OK; zero foreign-key violations; zero duplicate active document identities in the synthetic workload.
- Live stored-source/index audit: two active PDFs and one project index checked, with no source/manifest integrity issues. Schema remains c3d4e5f6a7b8.
- Final live source-key rechecks returned plot area 39,681.19 sqm and 804 residential units, both Revision 3/page 1; missing comparison inputs were rejected, and the fire-requirements answer retained its inspected-evidence scope limitation.

Two earlier follow-up checks had failed against an older running revision. The final restart rerun passed both without changing their expected answers. A temporary-directory permission error affected an initial sandboxed test invocation; running the same tests with a workspace temporary directory passed.

## 5. Performance results

Previously recorded native upload and deterministic-question loads covered concurrency 4, 8, 16, 32 and 64. Deterministic questions were 124/124 correct; P95 seconds were 0.828, 1.297, 2.437, 5.141 and 10.188. Model-backed requests passed at 4, 8 and 16; at 32, 16 succeeded and 16 received explicit HTTP 503 backpressure. The admission limit remains 16. This is a bounded capacity result, not unlimited model concurrency.

New image-only PDF intake batches:

| Concurrent upload requests | Final documents | Queue drain time |
|---|---|---|
| 4 | 4 READY_WITH_WARNINGS | 339.97 seconds |
| 8 | 8 READY_WITH_WARNINGS | 746.89 seconds |

All twelve scans preserved EXTRACTED_REVIEW_REQUIRED / REVIEW_REQUIRED. Actual extraction, OCR, vision, embedding and index publication were serialized by the durable ingestion worker. No claim is made of eight simultaneous OCR engines, or of 16/32/64 simultaneous OCR/vision execution.

622 resource samples over 1,311 seconds: peak test-server/child RSS 5.48 GiB; host CPU peak 76%; minimum available host RAM 33.84 GiB; peak ingestion queue 8; maximum sampled SQLite write-lock acquisition probe 94 ms; zero probe errors. Host GPU peak was 7,702 MiB and 100% utilization. Host disk counters increased by approximately 17.59 GB read and 1.37 GB written. GPU and disk counters include concurrent local activity, including a separate recovery test; they are not exclusive workload consumption or disk-capacity benchmarks.

## 6. Recovery results

An actual OCR child was observed during a synthetic upload. Only its dedicated test server and child processes were killed. The document stayed PROCESSING with zero chunks before and immediately after termination. On restart, the durable job completed on attempt **2**, with its original SHA-256 unchanged, one document row and nine chunks. It ended READY_WITH_WARNINGS, preserving the scan's review requirement. SQLite integrity remained OK.

Existing passing process-kill tests cover partial upload staging, SQLite before READY commit, FAISS generation swap and durable queue ownership. Eight fault-injected processing boundaries cover extraction, OCR, vision, structured extraction/storage, embedding, index and DB commit. Fault injection is not represented as real GPU/power interruption at every boundary. The shared model server and unrelated processes were not terminated.

## 7. Clean-machine result

EXCLUDED / NOT CERTIFIED, as requested. No installation, model download or package installation was performed to close these findings.

## 8. Remaining limits and acceptance requirements

The reproduced software defects above are corrected and regression-tested. Scanned/vision-derived facts still require review; this is an enforced evidence boundary, not a claim of automatic verification. Broader unseen engineering documents and real GPU/power failures at every processing boundary have not been independently certified. Long-duration load beyond these bounded samples is not established. Historical terminal jobs were retained rather than resetting their retry budgets.

An accountable engineering owner must accept the intended document types, answer accuracy and review process before engineering decisions depend on this system. These tests cannot substitute for that acceptance.

## 9. Final release decision

**Technical closure PASS for the tested, bounded scope. Controlled internal document-Q&A use with source review is supported by these results. Unrestricted/autonomous engineering production certification is NOT established.** Clean-machine installation remains outside this decision. Capacity is bounded to the existing model admission limit and serialized document processing.

Evidence: `answers.json`, `post-answers.json`, `reupload.json`, `scan-load-4.json`, `scan-load-8.json`, `post-index.json`, `integrity.json`, `resource-summary.json`, `recovery/result.json`, and the final regression logs. Distribute this report separately from private source files and database backups.
