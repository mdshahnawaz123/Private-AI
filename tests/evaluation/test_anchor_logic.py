import re
import sys

def trace_placement(lines_by_id, placement_id):
    placement_line = lines_by_id.get(placement_id)
    if not placement_line: return None
    
    # IFCLOCALPLACEMENT(PlacementRelTo, RelativePlacement)
    match = re.search(r"IFCLOCALPLACEMENT\([^,]*,\s*#(\d+)\s*\)", placement_line)
    if not match: return None
    
    relative_placement_id = int(match.group(1))
    rel_placement_line = lines_by_id.get(relative_placement_id)
    if not rel_placement_line: return None
    
    # IFCAXIS2PLACEMENT3D(Location, Axis, RefDirection)
    match = re.search(r"IFCAXIS2PLACEMENT3D\(\s*#(\d+)", rel_placement_line)
    if not match: return None
    
    location_id = int(match.group(1))
    return location_id

def extract_and_patch(ifc_path, out_path):
    with open(ifc_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
        
    lines_by_id = {}
    for i, line in enumerate(lines):
        match = re.match(r"^#(\d+)\s*=\s*(.*)", line)
        if match:
            lines_by_id[int(match.group(1))] = line

    # Find Map Conversion first
    map_conv_anchor = None
    for line in lines:
        if "IFCMAPCONVERSION" in line:
            # IFCMAPCONVERSION(SourceCRS, TargetCRS, Eastings, Northings, OrthogonalHeight, XAxisAbscissa, XAxisOrdinate, Scale)
            # Simplified match
            match = re.search(r"IFCMAPCONVERSION\([^,]+,[^,]+,([^,]+),([^,]+),([^,]+)", line)
            if match:
                map_conv_anchor = (float(match.group(1)), float(match.group(2)), float(match.group(3)))
                print(f"Found IFCMAPCONVERSION: {map_conv_anchor}")
                break
                
    # Find Site
    site_id = None
    site_placement_id = None
    for line in lines:
        if "IFCSITE" in line:
            match = re.match(r"^#(\d+)\s*=\s*IFCSITE", line)
            if match:
                site_id = int(match.group(1))
                # IFCSITE(GlobalId, OwnerHistory, Name, Description, ObjectType, ObjectPlacement, Representation, ...)
                m2 = re.search(r"IFCSITE\([^,]+,[^,]+,[^,]+,[^,]+,[^,]+,\s*#(\d+)", line)
                if m2:
                    site_placement_id = int(m2.group(1))
                    break

    if not site_placement_id:
        print("No IFCSITE placement found")
        return None

    location_id = trace_placement(lines_by_id, site_placement_id)
    if not location_id:
        print("Could not trace site location")
        return None

    loc_line = lines_by_id[location_id]
    print(f"Site Location Line: {loc_line.strip()}")
    
    # Parse Cartesian point
    match = re.search(r"IFCCARTESIANPOINT\(\(([^)]+)\)\)", loc_line)
    if not match:
        print("Not a cartesian point")
        return None
        
    coords = [float(x) for x in match.group(1).split(',')]
    print(f"Site Anchor Coordinates: {coords}")
    
    anchor = map_conv_anchor if map_conv_anchor else coords
    
    # Patch the line
    for i, line in enumerate(lines):
        if line.startswith(f"#{location_id}="):
            lines[i] = f"#{location_id}=IFCCARTESIANPOINT((0.0,0.0,0.0));\n"
            print(f"Patched line {i}: {lines[i].strip()}")
            break
            
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
        
    return anchor

if __name__ == "__main__":
    ifc_file = "../../data/docs/C3045 - Expo Valley Views/Models/C3085-MDL-3EH6117-AR-0000001.ifc"
    out_file = "patched_test.ifc"
    anchor = extract_and_patch(ifc_file, out_file)
    print("Final Anchor:", anchor)
