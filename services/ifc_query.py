"""Read-side queries over the IFC index (shared by the REST router and chat)."""
import sqlite3
from services.ifc_index import connect

GROUPS = {"class": "cls", "type": "type_name", "storey": "storey", "phase": "phase",
          "material": "material", "category": "category", "model": "model"}


def _where(project, f):
    w, a = ["project=?"], [project]
    for key, col in (("cls", "cls"), ("storey", "storey"), ("phase", "phase"), ("type", "type_name"),
                     ("model", "model"), ("material", "material"), ("category", "category")):
        v = f.get(key)
        if v:
            if key == "cls":
                c = v.upper()
                w.append("cls IN (?,?,?)")
                a += [c, c + "STANDARDCASE", c + "ELEMENTEDCASE"]
            else:
                w.append(f"{col} = ?")
                a.append(v)
    qtxt = f.get("q")
    if qtxt:
        like = f"%{qtxt}%"
        w.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
        a += [like] * 4
    if f.get("exclude_spaces", True) and not f.get("cls"):
        w.append("cls != 'IFCSPACE'")
    return " AND ".join(w), a


def rows(con, sql, args):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def status(project):
    con = connect()
    j = rows(con, "SELECT * FROM index_jobs WHERE project=?", (project,))
    n = con.execute("SELECT COUNT(*) FROM elements WHERE project=?", (project,)).fetchone()[0]
    con.close()
    return {"job": j[0] if j else None, "elements": n, "indexed": n > 0}


def summary(project):
    con = connect()
    out = {
        "models": rows(con, "SELECT model, COUNT(*) n FROM elements WHERE project=? GROUP BY model ORDER BY n DESC", (project,)),
        "classes": rows(con, "SELECT cls, COUNT(*) n FROM elements WHERE project=? GROUP BY cls ORDER BY n DESC", (project,)),
        "storeys": rows(con, "SELECT storey, MIN(storey_elev) elev, COUNT(*) n FROM elements WHERE project=? AND storey IS NOT NULL GROUP BY storey ORDER BY elev, storey", (project,)),
        "phases": rows(con, "SELECT phase, COUNT(*) n FROM elements WHERE project=? AND phase IS NOT NULL GROUP BY phase ORDER BY n DESC", (project,)),
        "materials": rows(con, "SELECT material, COUNT(*) n FROM elements WHERE project=? AND material IS NOT NULL GROUP BY material ORDER BY n DESC LIMIT 200", (project,)),
        "categories": rows(con, "SELECT category, COUNT(*) n FROM elements WHERE project=? AND category IS NOT NULL GROUP BY category ORDER BY n DESC", (project,)),
    }
    con.close()
    return out


def qto(project, group="class", **f):
    col = GROUPS.get(group, "cls")
    con = connect()
    w, a = _where(project, f)
    res = rows(con, f"SELECT COALESCE({col},'(none)') key, COUNT(*) count, ROUND(SUM(COALESCE(area,0)),2) area, "
                    f"ROUND(SUM(COALESCE(volume,0)),2) volume, ROUND(SUM(COALESCE(length,0)),2) length "
                    f"FROM elements WHERE {w} GROUP BY {col} ORDER BY count DESC LIMIT 500", a)
    tot = {"count": sum(r["count"] for r in res), "area": round(sum(r["area"] or 0 for r in res), 2),
           "volume": round(sum(r["volume"] or 0 for r in res), 2), "length": round(sum(r["length"] or 0 for r in res), 2)}
    con.close()
    return {"group": group, "rows": res, "total": tot}


def elements(project, limit=5000, **f):
    con = connect()
    w, a = _where(project, f)
    res = rows(con, f"SELECT id, model, step_id, gid, cls, name, type_name, storey, phase, material, area, volume, length "
                    f"FROM elements WHERE {w} ORDER BY model, step_id LIMIT ?", a + [limit])
    con.close()
    return res


def spaces(project):
    con = connect()
    res = rows(con, "SELECT e.id, e.model, e.step_id, e.name, e.storey, e.area, "
                    "(SELECT value FROM props WHERE element_id=e.id AND name='Number' AND pset='Space' LIMIT 1) number "
                    "FROM elements e WHERE project=? AND cls='IFCSPACE' ORDER BY storey, number, name", (project,))
    by = {}
    for r in res:
        s = by.setdefault(r["storey"] or "(none)", {"storey": r["storey"] or "(none)", "count": 0, "area": 0.0})
        s["count"] += 1; s["area"] += r["area"] or 0
    for s in by.values():
        s["area"] = round(s["area"], 2)
    con.close()
    return {"spaces": res, "by_storey": list(by.values()),
            "total_area": round(sum(r["area"] or 0 for r in res), 2)}


def storeys(project, model=None):
    con = connect()
    mw, ma = (" AND model=?", (model,)) if model else ("", ())
    res = rows(con, "SELECT storey, MIN(storey_elev) elev, COUNT(*) count, ROUND(SUM(COALESCE(area,0)),1) area, "
                    "ROUND(SUM(COALESCE(volume,0)),1) volume FROM elements WHERE project=? AND storey IS NOT NULL AND cls!='IFCSPACE'" + mw +
                    " GROUP BY storey ORDER BY elev, storey", (project,) + ma)
    for r in res:
        r["classes"] = rows(con, "SELECT cls, COUNT(*) n FROM elements WHERE project=? AND storey=? AND cls!='IFCSPACE' "
                                 "GROUP BY cls ORDER BY n DESC LIMIT 6", (project, r["storey"]))
    con.close()
    return res


def prop_names(project, limit=300):
    con = connect()
    res = rows(con, "SELECT p.pset, p.name, COUNT(*) n FROM props p JOIN elements e ON e.id=p.element_id "
                    "WHERE e.project=? GROUP BY p.pset, p.name ORDER BY n DESC LIMIT ?", (project, limit))
    con.close()
    return res


def search(project, q="", prop="", value="", cls="", limit=500):
    con = connect()
    w, a = ["e.project=?"], [project]
    if cls:
        w.append("e.cls=?"); a.append(cls.upper())
    if prop or value:
        sub, sa = [], []
        if prop:
            sub.append("p.name LIKE ?"); sa.append(f"%{prop}%")
        if value:
            sub.append("p.value LIKE ?"); sa.append(f"%{value}%")
        w.append(f"e.id IN (SELECT element_id FROM props p WHERE {' AND '.join(sub)})"); a += sa
    if q:
        w.append("(e.name LIKE ? OR e.type_name LIKE ? OR e.gid = ? OR e.id IN (SELECT element_id FROM props WHERE value LIKE ?))")
        a += [f"%{q}%", f"%{q}%", q, f"%{q}%"]
    res = rows(con, f"SELECT e.id, e.model, e.step_id, e.gid, e.cls, e.name, e.type_name, e.storey, e.phase, e.area, e.volume "
                    f"FROM elements e WHERE {' AND '.join(w)} LIMIT ?", a + [limit])
    con.close()
    return res


def element_props(eid):
    con = connect()
    res = rows(con, "SELECT pset, name, value FROM props WHERE element_id=? ORDER BY pset, name", (eid,))
    con.close()
    return res
