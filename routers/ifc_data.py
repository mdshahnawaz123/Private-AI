import csv, io
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
import auth
from services import ifc_index, ifc_query as Q

router = APIRouter(prefix="/api/ifc", tags=["IFC data"])


def _p(request: Request, project: str):
    auth.require_project(request, project)
    return project


@router.get("/status")
def status(request: Request, project: str):
    _p(request, project)
    s = Q.status(project)
    s["files"] = len(ifc_index.find_ifc_files(project))
    return s


@router.post("/index")
def index(request: Request, project: str, force: bool = False):
    _p(request, project)
    return {"started": ifc_index.start_background(project, force)}


@router.get("/summary")
def summary(request: Request, project: str):
    _p(request, project)
    return Q.summary(project)


def _filters(cls, storey, phase, type, model, material, category, q):
    return dict(cls=cls, storey=storey, phase=phase, type=type, model=model, material=material, category=category, q=q)


@router.get("/qto")
def qto(request: Request, project: str, group: str = "class", cls: Optional[str] = None, storey: Optional[str] = None,
        phase: Optional[str] = None, type: Optional[str] = None, model: Optional[str] = None,
        material: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None):
    _p(request, project)
    return Q.qto(project, group, **_filters(cls, storey, phase, type, model, material, category, q))


@router.get("/qto.csv")
def qto_csv(request: Request, project: str, group: str = "class", cls: Optional[str] = None, storey: Optional[str] = None,
            phase: Optional[str] = None, type: Optional[str] = None, model: Optional[str] = None,
            material: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None):
    _p(request, project)
    d = Q.qto(project, group, **_filters(cls, storey, phase, type, model, material, category, q))
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow([group, "count", "area_m2", "volume_m3", "length_m"])
    for r in d["rows"]:
        w.writerow([r["key"], r["count"], r["area"], r["volume"], r["length"]])
    t = d["total"]; w.writerow(["TOTAL", t["count"], t["area"], t["volume"], t["length"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="qto_by_{group}.csv"'})


@router.get("/elements")
def elements(request: Request, project: str, cls: Optional[str] = None, storey: Optional[str] = None,
             phase: Optional[str] = None, type: Optional[str] = None, model: Optional[str] = None,
             material: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None, limit: int = 5000):
    _p(request, project)
    return {"elements": Q.elements(project, min(limit, 20000), **_filters(cls, storey, phase, type, model, material, category, q))}


@router.get("/spaces")
def spaces(request: Request, project: str):
    _p(request, project)
    return Q.spaces(project)


@router.get("/storeys")
def storeys(request: Request, project: str):
    _p(request, project)
    return {"storeys": Q.storeys(project)}


@router.get("/prop-names")
def prop_names(request: Request, project: str):
    _p(request, project)
    return {"props": Q.prop_names(project)}


@router.get("/search")
def search(request: Request, project: str, q: str = "", prop: str = "", value: str = "", cls: str = "", limit: int = 500):
    _p(request, project)
    if not (q or prop or value):
        raise HTTPException(400, "Provide q, prop or value")
    return {"results": Q.search(project, q, prop, value, cls, min(limit, 5000))}


@router.get("/element-props")
def element_props(request: Request, project: str, id: int):
    _p(request, project)
    return {"props": Q.element_props(id)}
