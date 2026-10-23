---
name: architectural-render-prompting
description: How to write render prompts for FLUX 3 Image Klein (local AI Design Studio) - concept renders, sketch-to-render and render enhancement.
keywords: render, rendering, visualization, visualisation, concept image, image generation, flux, facade render, sketch to render, enhance render, design studio, generate image
---
FLUX 3 Image Klein reads natural-language prose through a Qwen3-VL text encoder. Write prompts for it like this:

1. ORDER (most important first): building type and massing (storeys as "ground floor plus 10 upper floors" when G+10 is given) -> facade system and materials with how they are built (panel joints, fin depth, slab edges, reveals) -> camera (eye-level 1.7 m, aerial 45-degree, street corner, interior; lens 24-35 mm; verticals straight) -> light and time of day -> context (site, landscape, people for scale, Dubai / Expo City climate cues).
2. ONE PARAGRAPH of 60-120 words of plain descriptive sentences. No keyword lists, no weights like (word:1.3), no "8k / masterpiece / trending" tags.
3. POSITIVE PHRASING ONLY. FLUX 3 runs at guidance 1.0 and ignores negative prompts; writing "no X" can add X. Say "straight vertical columns, crisp slab edges" instead of "no distorted columns".
4. HARD CONSTRAINTS VERBATIM: floor counts, typology, named materials, colours, site and any number the user gave appear unchanged in every option.
5. USER CHOICES WIN: if the user gives a camera, lighting, palette or style, use it. Only fill in what they left open; do not force golden hour or eye level every time - pick what suits the brief (overcast daylight for material studies, dusk for lighting design, aerial for masterplans).
6. TEXT IN IMAGE: signage or lettering goes in double quotes, e.g. a sign reading "EXPO CITY".
7. EDITS (a reference image is attached): start with what must stay ("keep the building shape, floor count, openings, structure and camera exactly"), then state only the change ("replace the facade screen with bronze perforated panels"), then light/finish. Do not redescribe the whole scene.
8. THREE OPTIONS must differ in substance - facade system, massing or climate strategy (e.g. deep shading fins vs mashrabiya screen vs terraced planting) - while sharing every hard constraint. Titles describe that difference, not a generic style label.
