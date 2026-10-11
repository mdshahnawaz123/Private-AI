# Current RAG architecture: forensic audit only

8 October 2026. **No production code, authentication, models, embeddings or OCR backend changed. No installation or model download. No synthetic PDF created. BIM/CAD/Reporting workflows skipped.**

## A. Current architecture and method

The existing Documents UI uses `/ask_stream`. This is not simply vector retrieval followed by a model: it first attempts deterministic sidecar lookups, then project-wide hybrid retrieval, then selected-page context injection, then the local model, then mechanical publication checks and one bounded repair. A second `/api/query_document` endpoint uses a different document classifier/structured-query chain; its document branch was inspected but the 20 questions below target the actual Documents UI endpoint.

Evidence was collected in two distinct runs: (1) 20 real HTTP requests to the running service on port 8090; (2) the unchanged on-disk production route executed against a consistent SQLite/index/source snapshot with observing wrappers that forwarded actual calls and captured context, raw model output and guard results. The latter made actual local model calls. The live server itself does not expose its full prompt/raw rejected answer; snapshot traces must not be represented as a wire-level capture of the live requests. Temperature 0.1 permits different generations. No services were restarted.

The 3/5/10 top-K probe uses the unchanged retrieval function. Identical candidate/query/top-5 inputs were asserted before reusing actual cross-encoder scores from the observed route, avoiding repeated expensive deterministic inference. Query vectors were computed once per question. This is a diagnostic cache only. Three exact-answer questions (5, 9, 18) never ran retrieval in the actual route: their hypothetical unreranked fallback probes are explicitly labeled, not claimed as reranker tests.

| Stage | Actual implementation | File / function |
|---|---|---|
| Upload | Permission-managed folder; bounded staging write, content validation and atomic file replacement | [main.py:2808](<C:/3EH/ExpoDesignAI - Copy/main.py:2808>) `upload_document` |
| Registration | documents row set PROCESSING, chunks 0; project/folder IDs and source path | [db.py:507](<C:/3EH/ExpoDesignAI - Copy/db.py:507>) `record_document` |
| Durable dispatch | Separate ingestion-jobs.sqlite3 jobs; immutable source hash; bounded 3 attempts; one runner | [services/jobs.py:22](<C:/3EH/ExpoDesignAI - Copy/services/jobs.py:22>) `JobQueue` |
| PDF extraction | PyMuPDF native text + line geometry tables; text strategy only if no line tables; heading band | [extract.py:123](<C:/3EH/ExpoDesignAI - Copy/extract.py:123>) `extract_pdf` |
| Native table reconstruction | Markdown tables; table_row_units flattens rows with title/entity/headers; raw text also retained | [intelligence/table_evidence.py:29](<C:/3EH/ExpoDesignAI - Copy/intelligence/table_evidence.py:29>) `table_row_units` |
| Full-page OCR | Offline OCR child for sparse/scanned page; skipped on this native text page | [services/page_ocr.py:13](<C:/3EH/ExpoDesignAI - Copy/services/page_ocr.py:13>) `supplement_pages` |
| Visual extraction | Dense-table/large-image gate in extract_pdf; embedded-image supplemental pipeline; EasyOCR then Qwen fallback | [services/pipeline.py:118](<C:/3EH/ExpoDesignAI - Copy/services/pipeline.py:118>) `process_document_pipeline` |
| Structure storage | ScheduleRow, StructuredRecord, Quantity; native/image source/confidence distinctions | [services/ingestion.py:220](<C:/3EH/ExpoDesignAI - Copy/services/ingestion.py:220>) `extract_structured_tables` |
| Chunking / metadata | Table rows remain atomic; other text uses hardcoded 800/80 character splitter; uncertainty labels preserved | [main.py:1885](<C:/3EH/ExpoDesignAI - Copy/main.py:1885>) `index_structured` |
| Embedding | Local Ollama bge-m3; batched /api/embed and /api/embeddings fallback; query embedding separately | [local_embed.py:26](<C:/3EH/ExpoDesignAI - Copy/local_embed.py:26>) `LocalOllamaEmbeddings` |
| Index storage | Per-project FAISS, index.pkl docstore, generation manifest; previous generations retained | [main.py:1652](<C:/3EH/ExpoDesignAI - Copy/main.py:1652>) `_persist_index_generation` |
| Source replacement | Prepare embeddings, remove chunks matching exact source filename, publish candidate, invalidate BM25 cache | [main.py:1684](<C:/3EH/ExpoDesignAI - Copy/main.py:1684>) `_replace_source_chunks` |
| Query entry | Focus validation, ready/folder permissions; exact answer first; endpoint retrieval minimum k=8 | [main.py:3163](<C:/3EH/ExpoDesignAI - Copy/main.py:3163>) `ask_stream` |
| Exact route | Sidecar native table rows; recognized unique scalar answers; some deterministic calculations | [intelligence/exact_answers.py:51](<C:/3EH/ExpoDesignAI - Copy/intelligence/exact_answers.py:51>) `exact_answer` |
| Retrieval | Vector candidates + cached per-project BM25; reciprocal rank fusion; ready/folder post-filter | [main.py:1952](<C:/3EH/ExpoDesignAI - Copy/main.py:1952>) `retrieve_context` |
| Keyword search | In-memory BM25 over project docstore; k1=1.5, b=0.75 | [intelligence/retrieval.py:49](<C:/3EH/ExpoDesignAI - Copy/intelligence/retrieval.py:49>) `BM25Index` |
| Reranking | BAAI/bge-reranker-v2-m3 cross-encoder on CPU, input clipped to first 500 characters; top 5 then fill to k from pre-rerank order | [intelligence/reranker.py:23](<C:/3EH/ExpoDesignAI - Copy/intelligence/reranker.py:23>) `Reranker` |
| Focused context | Query-ranked table rows, raw tables, raw native text, then visual observations; 4000 chars/page, 16000 total | [intelligence/page_context.py:6](<C:/3EH/ExpoDesignAI - Copy/intelligence/page_context.py:6>) `select_page_context` |
| Prompt assembly | Context in system message; document-only instruction, source/page citation rule; last 4 history messages when context exists | [main.py:2934](<C:/3EH/ExpoDesignAI - Copy/main.py:2934>) `build_messages` |
| LLM | Configured chat qwen3.5:9b; 16384 context option, 3072 generated-token limit, temperature 0.1, think false | [main.py:3017](<C:/3EH/ExpoDesignAI - Copy/main.py:3017>) `get_llm` |
| Publication | Numbers, unit pairs, tags and citation eligibility; one repair and deterministic auto-citation; not semantic engineering proof | [intelligence/answer_guard.py:190](<C:/3EH/ExpoDesignAI - Copy/intelligence/answer_guard.py:190>) `guarded_answer_with_repair` |
| Citation / source UI | Filename/page links; revision inferred from filename, not internal printed revision | [main.py:2362](<C:/3EH/ExpoDesignAI - Copy/main.py:2362>) `resolve_sources` |

### Actual models and retrieval settings

```json

{
  "settings": {
    "embed_model": "bge-m3",
    "chat_model": "qwen3.5:9b",
    "vision_model": "qwen2.5vl:7b",
    "reranker_model": "bge-reranker-v2-m3",
    "reranker_enabled": true,
    "rerank_candidates": 20,
    "rerank_keep": 5,
    "retrieval_k": 8,
    "enable_hybrid_bm25": true,
    "enable_metadata_prefilter": false,
    "not_found_threshold": 0.0,
    "chunk_size": 800,
    "chunk_overlap": 80,
    "num_ctx": 16384,
    "pdf_vision_all": false,
    "enable_legacy_schedule_context": false
  },
  "roles": {
    "chat": {
      "model": "qwen3.5:9b",
      "base_url": "http://127.0.0.1:11434"
    },
    "embed": {
      "model": "bge-m3",
      "base_url": "http://127.0.0.1:11434"
    },
    "vision": {
      "model": "qwen2.5vl:7b",
      "base_url": "http://127.0.0.1:11434"
    }
  },
  "python": "C:\\Users\\RE&DBIM\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
  "main_sha256": "4788ce26b653d94cb960038eacbb4f1b11a61e172a0dc2c39e84407789fe913c",
  "source_sha256": "905a5d07c5b310110d7de330dd7ac7d37f695df7b760db8efd5cb64f9429878f",
  "reranker": {
    "enabled": true,
    "loaded_in_observed_route": true,
    "measured_calls": 17
  },
  "diagnostic_replay_note": "Production code unchanged. Exact identical reranker inputs reuse captured deterministic scores; query embeddings computed once per question. Exact-route hypothetical fallback is explicitly marked unreranked, not an actual reranker measurement."
}

```

FAISS is a project directory, not a database collection service. The active project has 2026 1024-dimensional vectors: 218 for this sheet and 1808 for its fire report. The shared `__codes__` index is absent. Vector distances below are squared L2 distances, not probabilities. BM25 and vector rankings are fused with RRF constant 60. Metadata discipline/doctype prefilter is disabled. Reranking was actually loaded and used in all 17 model-backed observed questions. `not_found_threshold=0.0` disables its score threshold; other publication gates still operate. Low-score and unverified candidates can still enter the prompt.

### Metadata creation and loss

Upload registration holds document_id=22, project_id=7 and folder_id=45 in SQLite. Source sidecars hold page text/tables/vision, source SHA-256 and completion flags. Structured tables have page/revision/entity fields, but this PDF has no stored internal revision or document metadata record. Vector metadata is reduced to source filename, folder_id, source_sha256, evidence_state and page. Printed revision 3 survives as text, not a revision field. Section and table titles survive only inside some chunk strings. There is no typed parent relationship to distinguish a combined total from an F&B-only subtotal. Retrieval converts chunk metadata to source/page pairs, losing folder/hash/state/revision fields from source entries; uncertainty is preserved in text. UI source revisions come from filenames.

## Ingestion and actual storage

| Property | Observed |
|---|---|
| Document ID | 22 |
| Application project ID / name | 7 / C3085 - 3EH -Expo |
| Printed project ID | C3045; different from container project name |
| Printed revision | 3 |
| Filename/sidecar revision | Not populated; STAGE 4 is not a revision |
| Page count | 1 |
| Native text | 13958 characters |
| Geometry table text | 11742 characters |
| Visual text | 17162 characters; unverified |
| Tables | 14 extract_pdf tables; PageRecord native_table_count=15 from separate finder |
| Section count | Not stored |
| Atomic table-row units | 164 |
| Chunks / embeddings for this source | 218 / 218 |
| State distribution | 184 INTERPRETED, 34 REVIEW_REQUIRED |
| StructuredRecord / ScheduleRow / Quantity | 670 / 146 / 0 |
| Index | data/faiss_index/C3085 - 3EH -Expo |
| Document status | ready |
| PageRecord status | REVIEW_REQUIRED; vision PARTIAL |
| Source SHA-256 | 905a5d07c5b310110d7de330dd7ac7d37f695df7b760db8efd5cb64f9429878f |

The durable upload job completed on attempt 1. Full-page OCR status is NATIVE_TEXT_AVAILABLE. Two embedded images have vision COMPLETED, structured REVIEW_REQUIRED, but OCR remains PENDING and ocr_text is empty. Therefore full-page OCR was skipped and image OCR execution cannot be certified from these persisted fields. EasyOCR is the available offline backend in code; no claim is made that it produced every visual transcription. Structured records include 206 PDF_NATIVE/HIGH, 19 PDF_NATIVE/AMBIGUOUS and 445 PDF_IMAGE/AMBIGUOUS records. The ready flag is processing availability, not engineering verification.

| Required chunk field | Present in metadata |
|---|---|
| document_id | 0/218 |
| project_id | 0/218 |
| revision | 0/218 |
| page | 218/218 |
| section | 0/218 |
| table_id | 0/218 |
| chunk_id | 0/218 |
| content_hash | 0/218 |
| embedding_version | 0/218 |
| source_sha256 | 218/218 |
| folder_id | 218/218 |
| evidence_state | 218/218 |

Docstore UUIDs supply chunk identity outside metadata. Project isolation comes from separate directories and authorization, not a project_id field on chunks. Source hash is present; embedding model name is on the generation manifest only, without a pinned model digest or extraction/chunker version.

### Duplicate and stale-index check

Manifest file hashes match; all 218 source chunks have the current PDF hash; current native text and table extraction exactly match the stored sidecar. No duplicate UUIDs. One text occurs twice: the identical Retail 2000 m² summary appears beneath two different parent metrics, but the parent context is lost. This is semantic duplication, not evidence that reprocessing accumulated embeddings. Previous index directories retain older 205/218-chunk generations but are not merged into current retrieval. The loader may recover a preceding generation if the active index is missing; recovery does not compare each indexed source hash with the current source at query time.

The first isolated real-document re-index attempt failed at `_persist_index_generation` with Windows WinError 5 during directory publication; old generation was restored. The fresh-directory repeat succeeded twice: 218 source chunks and 2026 total vectors each time, identical content counts, zero first-run UUIDs retained after the second replacement. Production index hashes remain unchanged. This supports replacement for the same filename; it does not certify publication against every Windows filesystem/locking condition. No live re-upload or revision invention was performed.

[Raw storage inventory](inventory.json), [storage findings](storage-findings.json), [replacement results](reindex-results.json), [initial publication failure](reindex-run.log), [all stored chunks](actual-chunks.json), [selected actual chunk text](ACTUAL_CHUNKS.md).

## B. Primary root cause

**A successful upload proves processing/index availability, not that every field relationship was preserved.** This sheet mixes clean atomic native rows, shuffled native reading-order text, malformed parent labels and uncertain visual transcriptions. They all compete in retrieval/context. The model receives correct values alongside incorrect associations, while publication checks largely validate occurrence on a cited page rather than the specific field/entity/qualification relationship. The wrong FAR and F&B answers passed even though their correct rows were ranked first.

## C. Secondary root causes and first incorrect stages

| Finding | First incorrect stage | Actual evidence |
|---|---|---|
| FAR inherits area units, plus misleading raw text | TABLE_RECONSTRUCTION_FAILURE; raw reading-order extraction contributes | Q04 has `(SQ.M): 2.77`; raw chunk has `FAR Allowed:\n3`, although 3 is printed revision elsewhere. Rank-1 correct FAR row and the erroneous 3 both reach the prompt. |
| Combined retail + F&B total mislabeled as F&B total | TABLE_RECONSTRUCTION_FAILURE | Q14 rank 1 is F&B 5; rank 3 is `Table: F&B Units / TOTAL / NO.: 10`; the PDF shows 5 retail + 5 F&B. |
| Correct balcony answer refused | PARSING_FAILURE | Q12 rank-1 row contains EXCL. BALCONY / SQ.M.: 116.64. Both raw model calls answer correctly. quantity_pairs detects SQ.FT pairs but not the composite SQ.M label. |
| Comparison silently downgraded to scalar lookup | PARSING_FAILURE | Q18 exact route returns only Proposed GFA 105175.30; no retrieval or LLM call. Both source operands exist. |
| Focused source is not a retrieval filter | DOCUMENT_FILTER_FAILURE | ask_stream validates the focus path but calls project-wide retrieve_context without passing source identity; Q20 context contains six fire-report pages. |
| Text-only consultant rows lost and native context clipped | CHUNKING_FAILURE, then CONTEXT_ASSEMBLY_FAILURE | Native geometry has consultants; table_row_units emits no consultant names; 4000-character focus cap excludes the native table. Q15 native eligible excerpts contain none of the nine names, while visual candidates contain them. |
| Unsupported text can pass a page citation | CITATION_FAILURE (semantic support gap) | Q15 names/roles published without REVIEW_REQUIRED despite only visual evidence in its actual prompt. Guard tests numbers/tags/approval but not all factual text. FAR and F&B numbers merely occur on page 1. |
| Occasional live refusal not fully observable | NOT PROVEN | Q06 live refuses; observed route answers correctly. No live raw answer retained. Do not classify it as LLM error without evidence. |

## D. What is already working

Native geometry captures the principal area figures and balcony columns. Atomic row chunks keep many titles/headers/values together. Source/page/hash/folder metadata is present. FAISS and local embeddings work; hybrid BM25 and cross-encoder reranking are active. Ready/folder/project authorization gates operate. Same-source replacement does not accumulate chunks in the successful isolated repeat. Revision warnings expressly avoid treating highest filename as approved. GFA and residential-unit exact answers work. The 5th-floor question correctly lists BUA, GFA and NSA rather than collapsing them. Missing proposed FAR is acknowledged. Publication gates withhold unsupported numeric output and perform bounded repair.

## E. What is broken or limited

Semantic table-parent relationships, ratio units, composite unit validation, comparison intent and focused document isolation need correction. Text-only tables are not faithfully represented in atomic chunks. A page citation is not proof of a field relationship, and an apparently accurate consultant answer can still rely solely on uncertain visual text. Processing readiness and per-page review states are inconsistent at the overview level. Embedding/extraction versions are insufficiently pinned for reproducibility. Windows publication had one failure. The live rejected-answer cause cannot always be reconstructed from logs.

## A-Q failure-point investigation

| Requested concern | Finding |
|---|---|
| A stale embeddings | No stale native/table structure found for this active source. All hashes match. Version/digest pinning absent; fallback to old generation is a code-derived risk. |
| B duplicate embeddings | No UUID duplication or accumulation after two replacements. One identical Retail row loses its differing GFA/NSA parent. |
| C document filter | Confirmed missing source restriction in general retrieval even with focus_doc. |
| D project filter | Per-project index and membership/folder checks are implemented. This PDF was actually uploaded into the C3085 container; printed C3045 is source content. No cross-project leakage is established by same-project contamination. |
| E revision filter | No hard revision selector in retrieve_context; filename warnings only. Internal revision 3 absent from metadata. |
| F boundaries | Native raw text is still split at 800/80 characters and can preserve misleading adjacent labels; table rows atomic. |
| G headers lost | Multirow headers partly preserved; ratio rows inherit area headings and combined totals inherit wrong subsection. |
| H rows separated | Atomic table rows are not split. Raw text is. Consultant rows are dropped, rather than split correctly. |
| I top-K too small | Correct FAR, balcony and F&B rows already rank first. Increasing k does not repair semantics and can add misleading raw text/other documents. |
| J vector-only | False: current main path is hybrid. |
| K lack of keyword/BM25 | False: current main path builds BM25 and RRF-fuses it. |
| L similarity threshold | Score threshold is zero. Distances/scores must not be guessed into a replacement threshold; several defects occur despite high correct-row scores. |
| M reranker | Loaded locally on CPU. Keeps five, clips input to 500 chars, then main refills from unreranked fused candidates. Mapping uses content equality rather than chunk ID. |
| N truncation | Focus page is capped at 4000 chars. Native textual consultant rows are excluded; final model context includes visual fallback. |
| O prompt | Focus is prefixed to project-wide evidence; no strict selected-source-only instruction/filter. Unverified text is labeled but nonnumeric publication may still appear factual. |
| P hallucination | Wrong associations and unsupported additions occur. Correct-only controls recover key answers; model is not independently infallible. |
| Q citation mismatch | Numeric/page checks catch some errors, but a correct page can still contain a wrong field association. Filename citation revision misses internal revision. |

## Document and revision isolation

General retrieval searches all ready accessible documents in the chosen project, regardless of focus. Exact lookup is focus-restricted before retrieval. Native focused excerpts are prepended; other sources are removed only from duplicate source-list entries, not from the remaining context. Thus the fire report stays searchable and enters data-sheet questions. Global codes would also be added if installed; absent here.

Same filename replacement removes old chunks. A different revision filename does not match that predicate and its older counterpart remains searchable unless its document is deleted/archived/excluded. `revision_notice` groups filename labels and warns; it does not filter to an approved issue. Printed revision 3 on this sheet is not parsed into chunk/sidecar revision metadata. Revision 01/02/03 uploads and conflicting revised real PDFs were not available in this corpus and were not fabricated; the retention behavior is code-derived, not a live three-revision test.

## Failure matrix: real running application

PASS requires the requested answer and preservation of the available evidence qualification. A safe refusal on an available field is a completeness failure, not an unsafe fabricated answer. Q15 is content-correct but fails grounding/uncertainty. Q06 cause remains explicitly unlocalized. Ground truth was established from the visually inspected PDF, not from model output.

| Q | Exact question | Expected (page 1) | Actual live answer (summary) | Retrieval / final context in observed route | Result / first incorrect stage |
|---|---|---|---|---|---|
| [Q01](questions/Q01.md) | What is the project ID? | C3045 | The Project ID is **C3045**.<br><br>[SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1] | Correct requested evidence present | PASS: NONE |
| [Q02](questions/Q02.md) | What is the document revision number? | 3 | The document revision number is **3**.<br><br>This information is found in the "PROJECT DATA" table within the project data sheet for Project ID C3045.<br><br>[SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1] | Correct requested evidence present | PASS: NONE |
| [Q03](questions/Q03.md) | What is the Plot Area in square meters? | 39,681.19 m² | The **Plot Area** is **39,681.19 SQ.M.**<br><br>This value is found in the "AREA STATEMENT SUMMARY" table in the document [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]. | Correct requested evidence present | PASS: NONE |
| [Q04](questions/Q04.md) | What is the FAR Allowed value? | 2.77 (dimensionless FAR; not an area) | Based on the provided documents, the **FAR Allowed** values are as follows:<br><br>*   **2.77** (in SQ.M units) [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]<br>*   **3** (unit not explicitly specified in the snippet, but… | Correct row + misleading raw text and inherited unit | FAIL: TABLE_RECONSTRUCTION_FAILURE |
| [Q05](questions/Q05.md) | What is the GFA Proposed in square meters? | 105,175.30 m² | - **Proposed GFA:** 105,175.30 sqm. [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1] | N/A: exact route; no LLM | PASS: NONE |
| [Q06](questions/Q06.md) | What is the total BUA Proposed in square meters? | 173,494.10 m² | I could not verify the generated answer against the retrieved source pages. Please review the listed sources or ask for a specific field and page. | Correct requested evidence present | FAIL: NOT PROVEN FOR LIVE REQUEST |
| [Q07](questions/Q07.md) | What is the podium BUA in square meters? | 37,809.20 m² | Based on the provided document context, the Podium Built-Up Area (BUA) is **37,809.20 sq.m.**<br><br>This value is found in the "AREA STATEMENT SUMMARY" table within the project data sheet.<br><br>[SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STA… | Correct requested evidence present | PASS: NONE |
| [Q08](questions/Q08.md) | What is the towers BUA in square meters? | 135,684.90 m² | Based on the provided documents, the **Built-Up Area (BUA)** for the **Towers** is:<br><br>*   **135,684.90 SQ.M.**<br><br>This value is found in the "AREA STATEMENT SUMMARY" table within the document `260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4… | Correct requested evidence present | PASS: NONE |
| [Q09](questions/Q09.md) | How many residential units are there? | 804 residential units | - **Total residential units:** 804 units. [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1] | N/A: exact route; no LLM | PASS: NONE |
| [Q10](questions/Q10.md) | How many 1-bedroom units are there? | 227 | Based on the provided documents, there are **227** 1-bedroom units.<br><br>*   **Source:** [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]<br>    *   In the "Residential Units" table, the row for "ITEM: 1" (1 Bedroom) lists… | Correct requested evidence present | PASS: NONE |
| [Q11](questions/Q11.md) | What is the 5th floor area in square meters? | Ambiguous area type: BUA 11,811.89 m²; GFA 9,567.31 m²; NSA 9,663.88 m². Ask which area type or identify the type explicitly. | Based on the provided documents, here are the area values for the **5th Floor** in square meters:<br><br>*   **Built-Up Area:** 11,811.89 SQ.M. [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]<br>*   **Gross Floor Area (GFA)… | Correct requested evidence present | PASS: NONE |
| [Q12](questions/Q12.md) | What is the 2BR-Type 2 unit size excluding balcony? | 116.64 m² (1,255.50 sq.ft.), 2BR-Type 2 (Square) | I could not verify the generated answer against the retrieved source pages. Please review the listed sources or ask for a specific field and page. | Correct requested evidence present | FAIL: PARSING_FAILURE |
| [Q13](questions/Q13.md) | How many retail units are there? | 5 retail units (visitor toilets are a separate row, not a sixth retail unit) | Based on the provided document context, there are **5** retail units.<br><br>*   **Source:** [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]<br>    *   Under the table "Retail Units", the row shows: `ITEM: Retail Units; NO.… | Correct requested evidence present | PASS: NONE |
| [Q14](questions/Q14.md) | How many F&B units are there? | 5 F&B units | Based on the provided documents, there are **10** F&B units in total.<br><br>*   **Total Count:** The document lists "TOTAL" for F&B Units as **NO.: 10**. [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1]<br>*   **Breakdown:*… | Correct 5 + wrongly labeled combined total 10 | FAIL: TABLE_RECONSTRUCTION_FAILURE |
| [Q15](questions/Q15.md) | What consultants are listed? | SSH; Inhabit (Acoustic); Fencon (Façade & BMU); Design Confidence (Fire & Life Safety); LET (Lighting); The Design Company (Signage & Wayfinding); Platinum (Sustainability); Al Turath (Traffic Impact); Dunbar & Boardman (Vertical Transportation). Several other roles are blank. SSH covers Main Consultant, Architect-of-Record, Infrastructure, Interior Design, Landscape, MEP, Security, Structural and Supervision Consultant. | Based on the provided document context, the following **Consultants** are listed under the "DESIGN" and "CONSTRUCTION" categories:<br><br>**Design Consultants:**<br>*   **Main Consultant:** SSH<br>*   **Architect-of-Record:** SSH<br>*   **Acoustic:**… | Names only in unverified visual excerpts; native absent | FAIL: CHUNKING_FAILURE |
| [Q16](questions/Q16.md) | What is the project description? | 8 residential buildings on partial podium area and one basement floor with 2000 sq.m. retail area including 804 units. | Based on the provided documents, here is the project description:<br><br>*   **Project Description:** 8 residential buildings on partial podium area and one basement floor with 2000 sq.m. retail area including 804 units.<br>    *   [SOURCE: 260… | Correct requested evidence present | PASS: NONE |
| [Q17](questions/Q17.md) | What is the maximum allowed GFA? | 110,000.00 m²; this is a source limit, not proof of approval | Based on the provided documents, the **Maximum Allowed GFA** is:<br><br>*   **110,000 sq.m.** (or 1,184,029.00 sq.ft.)<br><br>This value is found in the "AREA STATEMENT SUMMARY" table under the item "GFA Allowed" and is also listed under "Affectio… | Correct requested evidence present | PASS: NONE |
| [Q18](questions/Q18.md) | Is the GFA Proposed within the GFA Allowed limit? | Yes numerically: 105,175.30 m² <= 110,000.00 m²; margin 4,824.70 m². Not a general compliance or approval certification. | - **Proposed GFA:** 105,175.30 sqm. [SOURCE: 260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf \| PAGE 1] | N/A: exact route; no LLM | FAIL: PARSING_FAILURE |
| [Q19](questions/Q19.md) | Is the FAR Proposed within the FAR Allowed limit? | Cannot establish from a stated FAR Proposed: FAR Proposed is '-', FAR Allowed is 2.77. Do not invent a proposed FAR. | Based on the provided document context, **I could not determine if the FAR Proposed is within the FAR Allowed limit** because the specific value for "FAR Proposed" is missing from the data.<br><br>*   **FAR Allowed:** The document states the… | Correct requested evidence present | PASS: NONE |
| [Q20](questions/Q20.md) | What information is NOT available in this document regarding fire safety requirements? | The sheet does not provide detailed fire-safety requirements such as evacuation/egress design, fire ratings, alarm/suppression or strategy criteria. It names Design Confidence as Fire & Life Safety consultant and includes a Service Lift/Fireman's Lift row; these do not establish full fire compliance. Limit the answer to this sheet. | I could not verify the generated answer against the retrieved source pages. Please review the listed sources or ask for a specific field and page. | Wrong document scope; mixed fire-report evidence | FAIL: DOCUMENT_FILTER_FAILURE |

**Live content completeness/accuracy: 14/20. Strict grounded/qualified answers: 13/20. HTTP success: 20/20, which is not answer correctness.** Observed route content: 15/20; stricter grounding 14/20. The differing Q06 result shows generation/validation variability, not evidence that one run supersedes the other. [Full exact answers and judgments](failure-matrix.json).

## Top-K and context comparison

The HTTP route enforces max(8, request.k), so asking k=3 or k=5 over that endpoint does not test three/five chunks. Direct retrieval probes vary k=3,5,10. With reranking active, k=3 still returns five kept documents; k=10 keeps five then fills five from pre-rerank order. Source counts are deduplicated page/source pairs, not chunk counts.

FAR 2.77 remains available at every tested k. Its misleading raw `FAR Allowed: 3` snippet enters the actual k=8 context through the refill path. Balcony 116.64 remains available at every k and is rank 1; the refusal occurs after model reasoning. Both the correct F&B 5 and incorrectly parented TOTAL 10 remain in the kept five; top-K cannot repair their relationship. Consultant names are retrieved principally as unverified visual text. Fire questions retrieve the fire report at every k because no focused-source filter is applied.

Observed final contexts are 7524-9931 characters for model-backed questions; focus itself is about 4116 including markers and the excerpt-end notice, with source content capped at 4000. No model-window overflow was established. The confirmed loss is earlier focused-page clipping and chunk serialization, not assumed token truncation. Each Q appendix contains retrieved context, final model context, complete prompts, raw initial/repair answers and guard issues. [All top-K traces](top-k-traces.json).

## Controlled local-model tests

Same configured qwen3.5:9b, local endpoint, temperature 0.1; no model replacement. Correct-evidence-only prompts recover FAR 2.77 without the false 3, F&B 5, podium BUA, all three 5th-floor areas, balcony 116.64, consultant names, GFA numerical comparison and missing proposed FAR. Several outputs omit the required exact citation syntax or add unnecessary caveats, so these are content demonstrations, not verified publication passes. The initial Q20 minimal control included an auditor-written absence assertion and is excluded as a literal-source-only ground-truth test. Its later control uses the complete native PDF tables, explicitly identifies consultant names as names, and describes missing detailed fire requirements. Prompt differences are retained, not hidden. This demonstrates that scoped native evidence and clearer relationship context help, without proving the model error-free.

[Controlled prompts and raw answers](controlled-results.json), [Q20 native-table-only follow-up](controlled-full-page-20.json).

## F. Evidence and reproducibility

[Current code hashes/function locations](code-inventory.json), [effective settings](runtime.json), [visually established ground truth](ground_truth.json), [live HTTP answers](live-results.json), [observed route prompts/output](route-traces.json), [exact stored chunk text](ACTUAL_CHUNKS.md), [top-K replay](top-k-traces.json), [storage checks](storage-findings.json), [reindex repeat](reindex-results.json).

Production files unchanged during recorded collection: True. Production FAISS hashes unchanged after replacement probes: True. The audit creates reports/scripts and isolated data only. Snapshots contain private project/database data and are not release-package artifacts. Authentication configuration and default admin credentials were not modified. Local reranker cache was used offline; no downloads/installations. Existing live question auditing writes normal audit-log entries. No broad old test-suite result is reused as a result of this audit.

## G-I. Highest priorities (recommendations only)

1. **Repair semantic evidence and publication validation.** Preserve parent/subtotal relationships, treat FAR as a ratio, keep textual table rows, and validate every answer against its field/entity/unit/qualification rather than merely numbers anywhere on a page. Make composite unit headers parse consistently without weakening the evidence gate. Re-test the fixed ground truth including F&B 5, FAR 2.77 and balcony 116.64.

2. **Enforce selected document and authoritative revision scope throughout retrieval/context.** Propagate document identity through exact, structured, vector, BM25, rerank and citation stages. Preserve review qualification; do not treat latest filename as approved. For source-only questions, do not silently combine another report or global codes.

3. **Preserve intent and make the pipeline reproducible/observable.** Route the GFA comparison to verified compatible operands and deterministic arithmetic; do not answer it as one scalar. Persist document/revision/table/chunk/model-version provenance, safe rejected-answer diagnostics and release version. Recheck Windows index publication and version freshness. Calibrate score thresholds only after evaluating relevant/irrelevant distributions; changing a threshold alone does not fix these demonstrated high-score semantic failures.

## J. Recommended target architecture

Retain the existing upload queue, native PDF geometry, EasyOCR, local Qwen, bge-m3, FAISS, SQLite and hybrid reranking for the current workstation scope. Incrementally make its evidence contract consistent: source/page/table/parent/column/entity/unit/revision/qualification → semantic chunks and structured rows → permission + selected-source + authority scope → hybrid candidates and reranking → bounded native-first context → deterministic calculations where applicable → local-model narration → semantic evidence/citation validation. The exact and model paths should share this contract. This is a target for later remediation, not an implemented redesign.

## Architecture score (requested, limited to this real-document audit)

This is an engineering assessment rubric, not a calibrated benchmark or production certificate. An untested model-version/revision scenario does not receive full credit.

| Component | Score | Evidence basis |
|---|---:|---|
| Extraction | 8/10 | Complete native page, geometry, hashes; raw reading-order relationships unreliable |
| Table reconstruction | 5/10 | Principal rows correct; combined parent totals, ratio units and textual rows fail |
| Chunking | 5/10 | Atomic numeric rows work; raw noise/text-only omissions remain |
| Metadata | 4/10 | Source/page/hash/folder present; document/revision/table/version identities missing |
| Embedding | 8/10 | Actual local bge-m3 vectors work; version digest not pinned |
| Indexing | 8/10 | Integrity and successful replacement repeat; one Windows publication failure and unproven fallback freshness |
| Retrieval | 9/15 | Active hybrid/reranker retrieves key correct rows; source scope and refill quality fail |
| Context assembly | 5/10 | Native-first ranked rows help; clipping and mixed-source/noisy context remain |
| LLM | 7/10 | Correct-only controls help; mixed associations and citation variation remain |
| Citation | 2/5 | Mechanical page checks operate; semantic field support and nonnumeric uncertainty incomplete |
| **Total** | **61/100** | **This PDF and observed paths only** |

## Release decision

**NO-GO for unrestricted engineering production.** The current audit found incorrect published answers and incomplete/refused answers even though the upload is ready. This first pass intentionally implements no fixes. Clean-machine deployment, wider workloads and independent engineering verification remain separate release gates; they are not newly certified here.