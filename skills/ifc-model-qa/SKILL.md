---
name: ifc-model-qa
description: Use when the user asks about elements, properties, storeys, or data quality in the loaded 3D/IFC model itself (not uploaded documents).
keywords: ifc, model, storey, storeys, level, levels, element, property, space, column, beam, wall, selected element, 3d model, viewer
---

# IFC / 3D Model Question Answering

When answering from MODEL DATA (the IFC-derived summary, not documents):
1. Map the user's everyday wording to the correct IFC type before answering (walls -> IfcWall, rooms/spaces -> IfcSpace, floors/levels/storeys -> IfcBuildingStorey, etc.) and say which IFC type you used, so a mismatch is visible to the user rather than silently wrong.
2. If a property the user asked about was not exported to IFC for that element (common for fire rating, manufacturer, cost data), say plainly "that property was not exported to IFC for this element" rather than estimating a plausible-sounding value — IFC exports are frequently incomplete and this is the single most common way this tool fabricates answers if not careful.
3. When reporting counts or areas from the model, state whether you're counting all elements of that type model-wide or only within a currently-selected scope (a storey, a selected element) if the model data indicates a scope is active.
4. Never claim to have visually inspected the model's geometry — you only have the extracted property/quantity data, not an image of the rendered 3D view, unless a screenshot was separately provided.
5. If the model has multiple federated sub-models loaded (a multi-model project), and an element or count could come from more than one, say which model(s) it's drawn from if that's available in the model data.
