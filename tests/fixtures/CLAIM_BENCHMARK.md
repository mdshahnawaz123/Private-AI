# Claim benchmark provenance

Version 1 was stored at `output/claim-source-eval/benchmark_v1.json`. It is missing, is not tracked in the available Git history, and was not recovered from the local workspace or attachments. Its expected SHA-256 remains `551c89d28d4e6af733ce769fc220bf5ad9257386b90ffe3771ad819f1fb9429b`. No claim is made that its original cases were executed or recovered.

Version 2 is a new synthetic acceptance benchmark stored with the test suite as `claim_support_v2.json`. It deliberately defines small, inspectable source spans and supported/unsupported candidate answers. Decisions were authored before running the tests; tests never generate their own expected decisions from application output. Existing CS identifiers are reused as scenario categories, not evidence of recovery of the old case text. This file is not derived from a project PDF and does not measure unseen-document accuracy.

Manual source review: read each `evidence`, `candidate_answer`, and `rationale`. Positive cases preserve the stated entity, property, value, unit, status, revision and qualification. Negative cases change one of those relationships, remove citations, use unverified OCR, select an unsupported page, invent a duration, or exploit a broad-summary bypass. Ambiguous cases lack a joint source span or a governing revision. Expected decisions are explicit; no LLM judges their truth. Cases CS027–CS031 add deadline, summary and table-header coverage.

The test pins the exact version 2 file hash. Missing data now fails collection instead of silently skipping this release check. A recovered version 1 file should be hash-checked and evaluated separately; do not overwrite version 2 with it.
