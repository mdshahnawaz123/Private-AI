---
name: pdf-reading
description: Local offline extraction of text, tables, specifications, and drawing notes from technical AEC PDF documents.
keywords: pdf-reading, technical drawing, architectural spec, mep drawing, structural drawing, construction spec, extract drawing, drawing titleblock, general notes, sheet specification, drawing set
---

# AEC PDF Reading — Technical Drawings & Specifications

Use this skill when reading, searching, or extracting technical data from construction drawings, architectural specifications, engineering standards, or multi-page project submittals.

## 1. Local Offline Extraction Rules
- All parsing is performed 100% locally using offline engines (PyMuPDF / layout engine / OCR).
- Never send document contents to external cloud services or third-party APIs.
- Preserve technical fidelity: retain exact dimensional units (mm, m, ft, in), engineering tolerances, rebar marks, room names, and material callouts.

## 2. Technical Drawing Extraction Guidelines
When reading architectural, structural, or MEP drawings:
1. **Title Block & Metadata First**:
   - Always extract: Project Name, Sheet Number (e.g. `A-101`, `S-201`, `M-501`), Drawing Title, Revision Number/Date, Author/Firm, and Scale (e.g. `1:100`, `1/4"=1'-0"`).
2. **General Notes & Keynotes**:
   - Extract discipline-specific General Notes verbatim.
   - Group by category: Design Loads, Material Strengths ($f'c$, $fy$), Setbacks, Fire-Resistance Ratings, and Testing Criteria.
3. **Schedules & Dimension Callouts**:
   - Extract schedules (Door/Window schedules, Room Finish schedules, Beam/Column schedules, Equipment schedules).
   - Report values in tabular format with exact headers.
4. **Discrepancy Detection**:
   - If a dimension on a plan conflicts with a schedule or general note, cite BOTH with sheet numbers and flag the coordination issue.

## 3. Architectural Specifications Extraction (CSI MasterFormat)
When reading technical specifications:
- Identify the CSI Division (e.g., Division 03 Concrete, Division 07 Thermal & Moisture, Division 08 Openings, Division 09 Finishes, Division 22 Plumbing, Division 23 HVAC).
- Structure extraction into:
  - **Part 1 - General**: Submittals, warranties, standards referenced (ASTM, BS, EN, Dubai Building Code).
  - **Part 2 - Products**: Acceptable manufacturers, material grades, physical properties.
  - **Part 3 - Execution**: Installation tolerances, surface preparation, quality control testing.

## 4. Citation Standard
Always provide strict provenance for every extracted fact:
`[Sheet/Doc: <Title>] [Page/Sheet No: <Number>] [Clause/Section: <Section>]`
