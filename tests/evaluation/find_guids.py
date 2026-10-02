import re

def trace_absolute_z(lines_by_id, placement_id):
    z = 0.0
    current = placement_id
    while current:
        p_line = lines_by_id.get(current)
        if not p_line: break
        m = re.search(r"IFCLOCALPLACEMENT\([^,]*,\s*#(\d+)\s*\)", p_line)
        if not m: break
        rel_id = int(m.group(1))
        
        m_relto = re.search(r"IFCLOCALPLACEMENT\((#\d+)", p_line)
        rel_to_id = int(m_relto.group(1)[1:]) if m_relto else None
        
        r_line = lines_by_id.get(rel_id)
        if r_line:
            m2 = re.search(r"IFCAXIS2PLACEMENT3D\(\s*#(\d+)", r_line)
            if m2:
                loc_id = int(m2.group(1))
                l_line = lines_by_id.get(loc_id)
                if l_line:
                    m3 = re.search(r"IFCCARTESIANPOINT\(\(([^)]+)\)\)", l_line)
                    if m3:
                        coords = [float(x) for x in m3.group(1).split(',')]
                        z += coords[2]
                        
        current = rel_to_id
    return z

ifc_file = "../../data/docs/C3045 - Expo Valley Views/Models/C3085-MDL-3EH6117-AR-0000001.ifc"
with open(ifc_file, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
    
lines_by_id = {}
for line in lines:
    m = re.match(r"^#(\d+)\s*=\s*(.*)", line)
    if m: lines_by_id[int(m.group(1))] = line

elements = []
for line_id, line in lines_by_id.items():
    if "IFCSLAB(" in line or "IFCROOF(" in line or "IFCWALLSTANDARDCASE(" in line:
        m_guid = re.search(r"\('([^']+)'", line)
        m_place = re.search(r",\s*#(\d+)\s*,\s*(?:#|IFC)", line) # just grab the second to last obj usually, or just parse carefully
        
        # better regex for standard product placement (usually 6th or 7th arg)
        m_place = re.search(r"(?:IFCSLAB|IFCROOF|IFCWALLSTANDARDCASE)\([^,]+,[^,]+,[^,]+,[^,]+,[^,]+,\s*#(\d+)", line)
        if m_guid and m_place:
            guid = m_guid.group(1)
            p_id = int(m_place.group(1))
            z = trace_absolute_z(lines_by_id, p_id)
            elements.append((guid, line[:20], z))

elements.sort(key=lambda x: x[2])
print("Lowest:", elements[:3])
print("Middle:", elements[len(elements)//2 : len(elements)//2 + 3])
print("Highest:", elements[-3:])
