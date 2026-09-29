"""
CAD (DWG / DXF) ingestion for Expo Design AI - fully offline.

For each drawing we produce two things:
  1) DATA   - annotations pulled from the DXF with ezdxf: layers, TEXT / MTEXT
              notes, DIMENSION values, and block ATTRIB tags (title block, etc).
  2) VISION - the drawing rendered to PNG(s) with ezdxf's matplotlib backend,
              which are then read by the local vision model (see vision.py).

A .dxf is used directly. A .dwg is converted to DXF first via the free
ODA File Converter (offline). Point EXPO_ODA_CONVERTER at the executable, or
install it to a standard location that ezdxf's odafc add-on can find.

ezdxf / matplotlib are imported lazily so importing this module never fails,
letting the app start even before the CAD extras are installed.
"""
import os
import glob
import shutil

CAD_EXTS = (".dwg", ".dxf")
ODA_CONVERTER = os.getenv("EXPO_ODA_CONVERTER", "")

def is_cad(path):
    return os.path.splitext(path or "")[-1].lower() in CAD_EXTS

def _find_oda():
    if ODA_CONVERTER and os.path.exists(ODA_CONVERTER):
        return ODA_CONVERTER
    for name in ("ODAFileConverter", "ODAFileConverter.exe"):
        p = shutil.which(name)
        if p:
            return p
    for pat in (r"C:\Program Files\ODA\*\ODAFileConverter.exe",
                r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
                r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe"):
        hits = glob.glob(pat)
        if hits:
            return sorted(hits)[-1]
    return None

def load_doc(path):
    """Return an ezdxf Drawing for a .dxf (direct) or .dwg (via ODA)."""
    ext = os.path.splitext(path)[-1].lower()
    if ext == ".dxf":
        import ezdxf
        return ezdxf.readfile(path)
    if ext == ".dwg":
        try:
            from ezdxf.addons import odafc
        except Exception as e:
            raise RuntimeError("ezdxf odafc add-on unavailable: %s" % e)
        oda = _find_oda()
        if oda:
            # best-effort: configure the converter path across ezdxf versions
            for attr in ("win_exec_path", "unix_exec_path", "exec_path"):
                try:
                    setattr(odafc, attr, oda)
                except Exception:
                    pass
        try:
            return odafc.readfile(path)
        except Exception as e:
            raise RuntimeError(
                "Could not convert DWG to DXF. Install the free ODA File "
                "Converter and set EXPO_ODA_CONVERTER to its path, or upload a "
                "DXF instead. (%s)" % e)
    raise ValueError("Not a CAD file: " + path)

def extract_data(doc):
    """Pull readable annotation/data out of a drawing as plain text."""
    out = []
    try:
        msp = doc.modelspace()
    except Exception:
        return ""
    try:
        layers = sorted(l.dxf.name for l in doc.layers)
        if layers:
            out.append("LAYERS (%d): %s" % (len(layers), ", ".join(layers)))
    except Exception:
        pass

    texts, dims, attribs = [], [], []
    for e in msp:
        try:
            t = e.dxftype()
        except Exception:
            continue
        try:
            if t == "TEXT":
                s = (e.dxf.text or "").strip()
                if s:
                    texts.append(s)
            elif t == "MTEXT":
                s = ""
                try:
                    s = e.plain_text().strip()
                except Exception:
                    s = (getattr(e, "text", "") or "").strip()
                if s:
                    texts.append(s)
            elif t == "DIMENSION":
                measured = None
                try:
                    measured = e.get_measurement()
                except Exception:
                    pass
                label = (getattr(e.dxf, "text", "") or "").strip()
                if measured is not None:
                    dims.append(("%s (measured %.3f)" % (label, measured)).strip())
                elif label:
                    dims.append(label)
            elif t == "INSERT":
                try:
                    for a in e.attribs:
                        tag = (a.dxf.tag or "").strip()
                        val = (a.dxf.text or "").strip()
                        if val:
                            attribs.append("%s = %s" % (tag, val))
                except Exception:
                    pass
        except Exception:
            continue

    if texts:
        out.append("TEXT / NOTES:\n" + "\n".join(texts))
    if attribs:
        out.append("BLOCK ATTRIBUTES (title block, tags):\n" + "\n".join(attribs))
    if dims:
        out.append("DIMENSIONS:\n" + "\n".join(d for d in dims if d))
    return "\n\n".join(out)

def render_images(doc, out_dir, dpi=150):
    """Render modelspace (and up to a couple of paper layouts) to PNGs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    os.makedirs(out_dir, exist_ok=True)
    paths = []

    def _render(layout, name):
        fig = plt.figure(figsize=(16, 11))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        try:
            ctx = RenderContext(doc)
            Frontend(ctx, MatplotlibBackend(ax)).draw_layout(layout, finalize=True)
            outp = os.path.join(out_dir, name)
            fig.savefig(outp, dpi=dpi)
            paths.append(outp)
        finally:
            plt.close(fig)

    try:
        _render(doc.modelspace(), "model.png")
    except Exception:
        pass
    try:
        for i, name in enumerate(list(doc.layout_names_in_taborder())):
            if name.lower() == "model":
                continue
            if i > 3:
                break
            try:
                _render(doc.layout(name), "layout_%d.png" % i)
            except Exception:
                continue
    except Exception:
        pass
    return paths

def ingest(path, out_dir):
    """Load a CAD file; return (data_text, [image_paths]). Rendering failures
    are non-fatal - the extracted data is still returned."""
    doc = load_doc(path)
    data = extract_data(doc)
    try:
        imgs = render_images(doc, out_dir)
    except Exception:
        imgs = []
    return data, imgs
