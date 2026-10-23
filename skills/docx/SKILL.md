---
name: docx
description: Local creation and editing of technical specifications, engineering review reports, site inspection minutes, and compliance documentation.
keywords: docx, word, specification, technical report, meeting minutes, transmittal, method statement, python-docx, site inspection report
---

# AEC Technical Document Authoring & Editing (DOCX)

Use this skill when drafting, updating, or formatting engineering reports, construction specifications, tender addenda, site inspection minutes, or compliance evaluations.

## 1. Local Processing Engine
- Generated locally using Python `docx` (`python-docx`).
- Operates completely offline with full style, table, and heading hierarchy control.

## 2. Standard AEC Document Structures

### A. Engineering Review & Audit Reports
- **Cover Page / Header**: Project Title, Document Reference No., Client, Lead Engineer, Date, Revision Status.
- **Section 1: Executive Summary**: High-level verdict, critical path findings, and compliance status.
- **Section 2: Scope & Reference Documents**: Table listing all reviewed drawing numbers, revisions, and spec sections.
- **Section 3: Discipline Observations**:
  - Architectural: Life safety, egress width, fire compartments, accessibility.
  - Structural: Load path continuity, drift ratios, foundation considerations, deflection checks.
  - MEP: Capacity adequacy, equipment clearances, riser shaft sizing, clash points.
- **Section 4: Compliance Matrix**: Tabular checklist against Dubai Building Code, NFPA, IBC, or BS EN standards.
- **Section 5: Action Items & Recommendations**: Action, Responsible Party, Priority (Critical / Major / Minor), Deadline.

### B. CSI MasterFormat Technical Specifications
- Structure in 3-part format:
  - `PART 1 - GENERAL`
  - `PART 2 - PRODUCTS`
  - `PART 3 - EXECUTION`
- Use formal engineering imperative language ("Contractor shall...", "Provide...", "Install in accordance with manufacturer's written instructions").

### C. Site Inspection & Non-Conformance Reports (NCR)
- Document non-conformance item, exact grid line and elevation location, photo/drawing reference, required remedial action, and reinspection sign-off block.
