---
name: quantity-takeoff-check
description: Use when the user asks for counts, totals, areas, or a quantity takeoff across the model or documents (how many doors, total floor area, etc).
keywords: how many, count, total, quantity, takeoff, area, m2, sq ft, square feet, sum, tally, schedule count
---

# Quantity Takeoff / Counting

When the user asks "how many X" or for a total/area/sum:
1. State the exact count or sum as a number first, then the breakdown — don't bury the number in a sentence.
2. Say explicitly what you counted it FROM (e.g. "counted from the IfcDoor elements in the model" or "summed the Area column of the door schedule on sheet A-501") so the user can tell which data source grounds the number.
3. If the model/document has multiple instances of what looks like the same schedule (e.g. a schedule on one sheet and a different count in a room data sheet), and they disagree, report BOTH numbers and flag the discrepancy — never silently pick one as "the" answer.
4. Distinguish a scheduled/nominal quantity from an as-modeled/as-extracted quantity when both exist; state which one you are reporting.
5. Never round a count. Areas may be rounded only to the precision already shown in the source, and state the unit every time (m2 vs sq ft are not interchangeable without saying so).
6. If some elements in the model/document could plausibly be excluded or included depending on interpretation (e.g. "doors" — does that include overhead doors, gates?), state your inclusion criteria so the user can correct it if it's wrong.
