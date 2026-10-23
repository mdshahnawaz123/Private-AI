---
name: pdf
description: Local offline PDF manipulation: split, merge, combine drawing sets, extract vector tables, fill form fields, and stamp engineering approvals.
keywords: pdf, split pdf, merge pdf, combine drawings, drawing set, extract tables, fill form, stamp approval, watermark, annotate pdf, markup pdf, reorder sheets
---

# AEC PDF Manipulation & Processing (100% Offline)

Use this skill when manipulating drawing packages, splitting multi-discipline packages, merging addenda into master drawing sets, extracting vector tables, or applying engineering review stamps.

## 1. Local Processing Engine
- All operations execute locally in the Python runtime using PyMuPDF (`fitz`), `pdfplumber`, or PyPDF2.
- Completely air-gapped and safe for confidential engineering contracts, tender packages, and proprietary design files.

## 2. Core AEC Workflows

### A. Splitting Multi-Discipline Drawing Sets
When given a combined 50+ page project submission:
1. Scan page title blocks to identify discipline prefixes:
   - `A-` / `AR-` = Architectural
   - `S-` / `ST-` = Structural
   - `M-` / `MEP-` = Mechanical / HVAC
   - `E-` = Electrical
   - `P-` / `PL-` = Plumbing & Drainage
   - `C-` / `CIV-` = Civil / Infrastructure
2. Split and save into discipline-specific PDF files named by project convention: `<Project>_<Discipline>_Rev<X>.pdf`.

### B. Merging & Combining Drawing Packages
- Merge updated addendum sheets into the master drawing set replacing superseded revisions.
- Preserve vector scale, layers, and embedded font bookmarks.

### C. Extracting Vector Tables to Structured Data
- Locate schedule boundaries on drawing sheets (Door schedules, Luminaire schedules, Rebar bending schedules).
- Extract table grid cells with line coordinates and text alignment.
- Format extracted output ready for piping into the `xlsx` skill.

### D. Filling Form Fields & Inspection Checklists
- Identify fillable PDF AcroForm fields (Checkboxes, Text Fields, Signature blocks).
- Complete field values programmatically (e.g., Project Number, Inspection Date, Inspector Name, Pass/Fail checkboxes).

### E. Engineering Status Stamps & Markups
- Add visual status stamps to sheet covers or review blocks:
  - **APPROVED**: Green border `#16a34a`, timestamp, reviewer license number.
  - **APPROVED AS NOTED**: Blue border `#2563eb`, bulleted comments reference.
  - **REVISE & RESUBMIT**: Red border `#dc2626`, non-conformance flag.
  - **DRAFT / FOR INFORMATION ONLY**: Neutral charcoal `#52525b`.
