"""IFC data index: extracts elements / quantities / rooms / storeys / phases / types /
properties from project IFC files into SQLite so the 3D viewer panel, REST API and chat
can answer BIM questions deterministically (no LLM guessing).

Run standalone (own process, so heavy parsing never blocks the API):
    python -m services.ifc_index "<project>" [--force]
"""
import os, sys, glob, json, sqlite3, time, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DOCS_DIR = os.path.join(DATA_DIR, "docs")
DB_PATH = os.path.join(DATA_DIR, "ifc_index.db")

SKIP_PSETS = {"Graphics", "Analytical Properties"}
SKIP_PSET_PREFIX = ("Pset_ReinforcementBar",)
LENGTH_KEYS = {"Length", "Width", "Height", "Thickness", "Perimeter", "Unconnected Height", "Head Height", "Sill Height"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS elements(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, model TEXT, step_id INTEGER, gid TEXT,
  cls TEXT, name TEXT, type_name TEXT, storey TEXT, storey_elev REAL, phase TEXT, material TEXT,
  category TEXT, area REAL, volume REAL, length REAL, width REAL, height REAL);
CREATE INDEX IF NOT EXISTS ix_el_proj ON elements(project, cls);
CREATE INDEX IF NOT EXISTS ix_el_model ON elements(project, model);
CREATE TABLE IF NOT EXISTS props(element_id INTEGER, pset TEXT, name TEXT, value TEXT);
CREATE INDEX IF NOT EXISTS ix_pr_el ON props(element_id);
CREATE INDEX IF NOT EXISTS ix_pr_name ON props(name);
CREATE TABLE IF NOT EXISTS index_jobs(
  project TEXT PRIMARY KEY, state TEXT, done_files INTEGER, total_files INTEGER,
  current TEXT, message TEXT, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS indexed_files(project TEXT, model TEXT, size INTEGER, mtime REAL, n_elements INTEGER,
  PRIMARY KEY(project, model));
"""


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.executescript(SCHEMA)
    return con


def find_ifc_files(project):
    base = os.path.join(DOCS_DIR, project)
    seen, out = set(), []
    for p in glob.glob(os.path.join(base, "**", "*.ifc"), recursive=True):
        key = (os.path.basename(p).lower(), os.path.getsize(p))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return sorted(out)


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _storey_of(E, el):
    c = E.get_container(el)
    guard = 0
    while c is not None and not c.is_a("IfcBuildingStorey") and guard < 6:
        c = E.get_aggregate(c) if hasattr(E, "get_aggregate") else None
        guard += 1
    return c


def index_file(con, project, path):
    import ifcopenshell, ifcopenshell.util.element as E, ifcopenshell.util.unit as U
    model = os.path.basename(path)
    f = ifcopenshell.open(path)
    try:
        scale = U.calculate_unit_scale(f)
    except Exception:
        scale = 1.0
    len_mult = scale if abs(scale - 0.001) < 1e-9 else 1.0  # Revit psets: lengths in file units (mm)
    len_mult = 0.001 if abs(scale - 0.001) < 1e-9 else 1.0
    con.execute("DELETE FROM props WHERE element_id IN (SELECT id FROM elements WHERE project=? AND model=?)", (project, model))
    con.execute("DELETE FROM elements WHERE project=? AND model=?", (project, model))
    classes = ["IfcElement", "IfcSpace"]
    n = 0
    for base_cls in classes:
        for el in f.by_type(base_cls):
            if el.is_a("IfcOpeningElement") or el.is_a("IfcVirtualElement"):
                continue
            try:
                psets = E.get_psets(el)
            except Exception:
                psets = {}
            typ = None
            try:
                t = E.get_type(el)
                typ = t.Name if t is not None else None
            except Exception:
                pass
            st = None
            try:
                st = _storey_of(E, el)
            except Exception:
                pass
            if st is None and el.is_a("IfcSpace"):
                try:
                    dec = getattr(el, "Decomposes", None)
                    if dec:
                        par = dec[0].RelatingObject
                        st = par if par.is_a("IfcBuildingStorey") else None
                except Exception:
                    pass
            mat = None
            try:
                m = E.get_material(el)
                if m is not None:
                    if m.is_a("IfcMaterialLayerSetUsage"):
                        m = m.ForLayerSet
                    mat = getattr(m, "Name", None) or getattr(m, "LayerSetName", None)
                    if not mat and m.is_a("IfcMaterialLayerSet") and m.MaterialLayers:
                        mat = m.MaterialLayers[0].Material.Name
            except Exception:
                pass
            dims = psets.get("Dimensions", {}) or {}
            qto = psets.get("Pset_QuantityTakeOff", {}) or {}
            area = _num(dims.get("Area", qto.get("Area")))
            vol = _num(dims.get("Volume", qto.get("Volume")))
            ln = _num(dims.get("Length"))
            wd = _num(dims.get("Width"))
            ht = _num(dims.get("Height", dims.get("Unconnected Height")))
            if area is None and el.is_a("IfcSpace"):
                for ps in psets.values():
                    for k in ("Area", "NetFloorArea", "GrossFloorArea"):
                        if k in ps and _num(ps[k]) is not None:
                            area = _num(ps[k]); break
                    if area is not None:
                        break
            if ln is not None: ln *= len_mult
            if wd is not None: wd *= len_mult
            if ht is not None: ht *= len_mult
            phase = (psets.get("Phasing", {}) or {}).get("Phase Created")
            other = psets.get("Other", {}) or {}
            cat = other.get("Category")
            name = el.Name
            if el.is_a("IfcSpace"):
                name = el.LongName or el.Name
            cur = con.execute(
                "INSERT INTO elements(project,model,step_id,gid,cls,name,type_name,storey,storey_elev,phase,material,category,area,volume,length,width,height)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (project, model, el.id(), el.GlobalId, el.is_a().upper(), name, typ or (psets.get("Identity Data", {}) or {}).get("Type Name"),
                 st.Name if st is not None else None, _num(getattr(st, "Elevation", None)) if st is not None else None,
                 phase, mat, cat, area, vol, ln, wd, ht))
            eid = cur.lastrowid
            rows = []
            for pname, props in psets.items():
                if pname in SKIP_PSETS or pname.startswith(SKIP_PSET_PREFIX):
                    continue
                for k, v in props.items():
                    if k == "id" or v is None or isinstance(v, (dict, list, tuple)):
                        continue
                    rows.append((eid, pname.replace("(Type)", ""), k, str(v)[:200]))
            if el.Name and el.is_a("IfcSpace"):
                rows.append((eid, "Space", "Number", str(el.Name)))
            con.executemany("INSERT INTO props VALUES(?,?,?,?)", rows)
            n += 1
        con.commit()
    st = os.stat(path)
    con.execute("INSERT OR REPLACE INTO indexed_files VALUES(?,?,?,?,?)", (project, model, st.st_size, st.st_mtime, n))
    con.commit()
    return n


def run_index(project, force=False):
    con = connect()
    files = find_ifc_files(project)
    con.execute("INSERT OR REPLACE INTO index_jobs VALUES(?,?,?,?,?,?,?,?)",
                (project, "running", 0, len(files), "", "", time.time(), None))
    con.commit()
    done = 0
    try:
        for p in files:
            model = os.path.basename(p)
            row = con.execute("SELECT size, mtime FROM indexed_files WHERE project=? AND model=?", (project, model)).fetchone()
            st = os.stat(p)
            con.execute("UPDATE index_jobs SET current=?, done_files=? WHERE project=?", (model, done, project))
            con.commit()
            if row and not force and row[0] == st.st_size and abs(row[1] - st.st_mtime) < 1:
                done += 1
                continue
            try:
                index_file(con, project, p)
            except Exception as e:  # keep going on one bad file
                con.execute("UPDATE index_jobs SET message=? WHERE project=?", (f"{model}: {e}"[:300], project))
                con.commit()
            done += 1
        con.execute("UPDATE index_jobs SET state='done', done_files=?, finished=?, current='' WHERE project=?", (done, time.time(), project))
    except Exception as e:
        con.execute("UPDATE index_jobs SET state='error', message=? WHERE project=?", (str(e)[:300], project))
    con.commit()
    con.close()


_running = {}


def start_background(project, force=False):
    """Spawn the indexer in its own process (heavy CPU). Returns True if started."""
    import subprocess
    p = _running.get(project)
    if p is not None and p.poll() is None:
        return False
    cmd = [sys.executable, "-m", "services.ifc_index", project] + (["--force"] if force else [])
    _running[project] = subprocess.Popen(cmd, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


if __name__ == "__main__":
    run_index(sys.argv[1], "--force" in sys.argv)
