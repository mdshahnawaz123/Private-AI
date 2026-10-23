---
name: xlsx
description: Local creation and editing of construction takeoffs, material schedules, cost estimates, BOQ, and Excel workbooks with live formulas.
keywords: xlsx, excel, spreadsheet, takeoff, material list, schedule, boq, bill of quantities, cost estimate, openpyxl, pandas, construction estimate
---

# AEC Construction Spreadsheets & Takeoffs (XLSX)

Use this skill when converting PDF drawing data, BIM parameters, or specification tables into editable Excel workbooks (`.xlsx`) for material takeoffs, cost estimation, and procurement schedules.

## 1. Local Processing Engine
- Generated locally using Python `openpyxl` and `pandas`.
- Never uses cloud converters or online spreadsheet services.

## 2. Construction Takeoff (BOQ) Formatting Standards
When generating a Bill of Quantities or Material Takeoff:
1. **Standard Header Block**:
   - Project Name, Project Code (e.g. `C3085`), Date, Discipline, Prepared By, Revision.
2. **Standard Columns**:
   - `Item No.` | `CSI Division / Section` | `Description` | `Unit` (m, m2, m3, kg, No.) | `Quantity` | `Unit Rate (AED / USD)` | `Total Cost` | `Drawing Reference`
3. **Embedded Excel Formulas**:
   - Always write native Excel formulas instead of hardcoded numbers:
     - Total Cost row: `=E{row}*F{row}`
     - Subtotal: `=SUM(G{start}:G{end})`
     - Contingency (e.g. 5%): `=G{subtotal}*0.05`
     - Grand Total: `=G{subtotal}+G{contingency}`
4. **Professional Styling**:
   - Title & Category Header: Dark navy fill `#1e293b` with bold white text `#ffffff`.
   - Data Rows: Alternating zebra striping (`#f8fafc` and `#ffffff`) for readability.
   - Borders: Thin gray border `#cbd5e1` on all data cells; double underline on Grand Total.
   - Number Formatting: Currency (`$#,##0.00` or `AED #,##0.00`), quantities with commas (`#,##0.00`).

## 3. Supported AEC Schedule Types
- **Concrete & Rebar Takeoff**: Volume of slabs, beams, columns; rebar tonnage by bar size ($\phi 10, \phi 12, \phi 16, \phi 20, \phi 25, \phi 32$).
- **Door & Window Schedule**: Mark, Type, Width, Height, Material, Fire Rating, Glazing Type, Hardware Set.
- **MEP Equipment Schedule**: Tag (AHU-01, CH-01), Airflow (CFM / L/s), Static Pressure, Power (kW), Voltage.
- **Room Data & Finishes**: Room Number, Name, Floor Finish, Base, Wall Finish, Ceiling Height, Ceiling Type.
