---
name: file-reading
description: Smart offline document inspection, type detection, and optimal parser routing for AEC drawings, BIM models, CAD files, spreadsheets, and specifications.
keywords: file-reading, read file, open file, detect document, dwg, dxf, ifc, bim data, document type, inspection, smart parser
---

# AEC Smart File Reading & Document Routing (100% Offline)

Use this skill when handling unknown, multi-format, or bulk document submissions to automatically detect the file type, discipline, and invoke the best local offline engine.

## 1. Local Offline Routing Architecture
Inspect the file extension, binary magic bytes, and internal metadata to route to the appropriate engine:

| File Type / Extension | AEC Category | Primary Local Engine | Extraction Target |
| :--- | :--- | :--- | :--- |
| `.pdf` (Vector / Scanned) | Drawings & Specs | PyMuPDF + Layout / OCR Engine | Title blocks, vector lines, schedules, general notes, text |
| `.ifc` | BIM Model | `ifcopenshell` + Spatial Engine | Storeys, IfcSpace, IfcWall, IfcDoor, spatial coordinates, properties |
| `.dwg`, `.dxf` | CAD Drawings | `cad_api` + `ezdxf` | Layers, polylines, hatches, block inserts, dimension entities |
| `.xlsx`, `.xls`, `.csv` | Schedules & BOQ | `pandas` + `openpyxl` | Grid data, formula calculation, takeoff quantities, equipment tags |
| `.docx`, `.doc`, `.rtf` | Specifications & Reports | `python-docx` | Structured sections, CSI divisions, clauses, bulleted requirements |
| `.png`, `.jpg`, `.jpeg` | Site Photos & Renders | Pillow + Local Vision Adapter | Visual defects, site conditions, construction progress |

## 2. Multi-File Package Triage Workflow
When processing a mixed folder of project documents:
1. **Catalog & Inventory**: Create a manifest of all files with size, discipline tag, and last modified date.
2. **Prioritize Ground-Truth Sources**:
   - For 3D geometries and spatial quantities: prioritize `.ifc` BIM models.
   - For legal contract and permit requirements: prioritize approved PDF drawings and signed specifications.
   - For cost and procurement data: prioritize `.xlsx` Bill of Quantities.
3. **Cross-Check Consistency**:
   - Compare BIM quantities against 2D drawing schedules and BOQ line items.
   - Flag discrepancies where modeled geometry differs from scheduled values.
