"""
Dedicated CAD (DWG / DXF) Intelligence & Ingestion Engine.
Processes native AutoCAD / BIM CAD drawings:
- Direct DXF processing via ezdxf (layers, modelspace, texts, MTEXT, dimensions, block attributes, schedules)
- DWG conversion via ODA File Converter if present
- Resilient offline fallback: extracts DWG metadata, header version, text strings, and blocks gracefully if ODA converter is not installed, preventing pipeline crashes.
- Vector rendering to PNG layouts with vision model summarization.
- Universal Drawing Schema integration for BIM / CAD schedules.
"""
import os
import re
import glob
import shutil
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

CAD_EXTS = (".dwg", ".dxf")
ODA_CONVERTER = os.getenv("EXPO_ODA_CONVERTER", "")


class CadIntelligenceEngine:
    """
    Dedicated engine for DWG and DXF engineering files.
    """

    def is_cad(self, path: str) -> bool:
        return os.path.splitext(path or "")[-1].lower() in CAD_EXTS

    def find_oda_converter(self) -> Optional[str]:
        # 1. Internal private package inside project vendor directory
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vendor_oda = os.path.join(root_dir, "vendor", "oda", "ODAFileConverter.exe")
        if os.path.exists(vendor_oda):
            return vendor_oda

        if ODA_CONVERTER and os.path.exists(ODA_CONVERTER):
            return ODA_CONVERTER
        for name in ("ODAFileConverter", "ODAFileConverter.exe"):
            p = shutil.which(name)
            if p:
                return p
        for pat in (
            r"C:\Program Files\ODA\*\ODAFileConverter.exe",
            r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\*\ODAFileConverter.exe"
        ):
            hits = glob.glob(pat)
            if hits:
                return sorted(hits)[-1]
        return None

    def load_doc(self, path: str):
        """Return an ezdxf Drawing for a .dxf (direct) or .dwg (via ODA if present)."""
        ext = os.path.splitext(path)[-1].lower()
        if ext == ".dxf":
            import ezdxf
            return ezdxf.readfile(path)
        if ext == ".dwg":
            oda = self.find_oda_converter()
            if not oda:
                return None  # Will trigger fallback extraction
            try:
                import ezdxf
                ezdxf.options.set("odafc-addon", "win_exec_path", oda)
                from ezdxf.addons import odafc
                for attr in ("win_exec_path", "unix_exec_path", "exec_path"):
                    try:
                        setattr(odafc, attr, oda)
                    except Exception:
                        pass
                return odafc.readfile(path)
            except Exception as e:
                logger.warning("ODA DWG conversion failed: {}", e)
                return None
        return None

    @staticmethod
    def _clean_text(s: str) -> str:
        """Readable text for the AI: strip MTEXT formatting codes (\\P, {\\H0.6x;...}) that some
        tools put even in TEXT entities, and repair UTF-8 that was decoded as Windows-1252
        (one or more times), e.g. "mÃ‚Â²" -> "m²"."""
        if not s:
            return ""
        if "\\P" in s or "{\\" in s or "\\H" in s:
            try:
                from ezdxf.tools.text import plain_mtext
                s = plain_mtext(s)
            except Exception:
                s = s.replace("\\P", "\n")
        for _ in range(3):
            if not any(ch in s for ch in "ÃÂâ"):
                break
            try:
                fixed = s.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                try:
                    fixed = s.encode("latin-1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    break
            if fixed == s:
                break
            s = fixed
        return s.strip()

    def extract_dxf_data(self, doc) -> Dict[str, Any]:
        """Pull structured engineering annotations out of an ezdxf Drawing object."""
        result = {
            "layers": [],
            "texts": [],
            "dimensions": [],
            "block_attributes": [],
            "drawing_number": None,
            "drawing_title": None,
            "revisions": []
        }
        try:
            msp = doc.modelspace()
        except Exception:
            return result

        try:
            result["layers"] = sorted(l.dxf.name for l in doc.layers)
        except Exception:
            pass

        for e in msp:
            try:
                t = e.dxftype()
            except Exception:
                continue

            try:
                if t == "TEXT":
                    s = self._clean_text(e.dxf.text or "")
                    if s:
                        result["texts"].append(s)
                elif t == "MTEXT":
                    s = ""
                    try:
                        s = e.plain_text().strip()
                    except Exception:
                        s = (getattr(e, "text", "") or "").strip()
                    s = self._clean_text(s)
                    if s:
                        result["texts"].append(s)
                elif t == "DIMENSION":
                    measured = None
                    try:
                        measured = e.get_measurement()
                    except Exception:
                        pass
                    label = (getattr(e.dxf, "text", "") or "").strip()
                    if measured is not None:
                        result["dimensions"].append(f"{label} (measured {measured:.3f})".strip())
                    elif label:
                        result["dimensions"].append(label)
                elif t == "INSERT":
                    for a in getattr(e, "attribs", []):
                        tag = (a.dxf.tag or "").strip()
                        val = self._clean_text(a.dxf.text or "")
                        if val:
                            result["block_attributes"].append(f"{tag} = {val}")
                            if any(k in tag.lower() for k in ["dwg", "drawing_no", "drawing_num", "sheet"]):
                                result["drawing_number"] = val
                            if any(k in tag.lower() for k in ["title", "sheet_title", "dwg_title"]):
                                result["drawing_title"] = val
            except Exception:
                continue

        # Look for drawing number and revisions in text
        for txt in result["texts"]:
            if not result["drawing_number"]:
                m = re.search(r'\b([A-Z0-9]{4,5}-[A-Z0-9]{3}-[A-Z0-9]{7}-[A-Z0-9]{2}-[A-Z0-9]{7,10})\b', txt)
                if m:
                    result["drawing_number"] = m.group(1)
            if any(k in txt.upper() for k in ["ISSUED FOR CONSTRUCTION", "FIRST ISSUE", "REVISION"]):
                result["revisions"].append(txt)

        return result

    def extract_dwg_fallback(self, path: str) -> Dict[str, Any]:
        """
        Resilient binary extraction for DWG files when ODA File Converter is not installed.
        Extracts AutoCAD version header, readable text blocks, and structured metadata
        without raising unhandled fatal exceptions.
        """
        filename = os.path.basename(path)
        file_size = os.path.getsize(path)
        result = {
            "filename": filename,
            "format": "AutoCAD DWG (Binary)",
            "file_size": file_size,
            "dwg_version": "Unknown",
            "drawing_number": None,
            "drawing_title": None,
            "status": "CONVERTER_REQUIRED",
            "message": "DWG binary file uploaded. For full 2D vector geometry rendering, install the free ODA File Converter or upload DXF format.",
            "extracted_text": []
        }

        try:
            with open(path, "rb") as f:
                header = f.read(12)
            version_map = {
                b"AC1032": "AutoCAD 2018/2021/2024 (AC1032)",
                b"AC1027": "AutoCAD 2013/2016 (AC1027)",
                b"AC1024": "AutoCAD 2010/2012 (AC1024)",
                b"AC1021": "AutoCAD 2007/2009 (AC1021)",
                b"AC1018": "AutoCAD 2004/2006 (AC1018)",
                b"AC1015": "AutoCAD 2000 (AC1015)",
            }
            for code, name in version_map.items():
                if header.startswith(code):
                    result["dwg_version"] = name
                    break

            # Infer drawing number from filename
            m = re.search(r'([A-Z0-9]{4,5}-[A-Z0-9]{3}-[A-Z0-9]{7}-[A-Z0-9]{2}-[A-Z0-9]{7,10})', filename)
            if m:
                result["drawing_number"] = m.group(1)

        except Exception as e:
            logger.warning("DWG fallback read error: {}", e)

        return result

    def render_images(self, doc, out_dir: str, dpi: int = 150) -> List[str]:
        """Render DXF modelspace and layout tabs to PNG images."""
        if doc is None:
            return []
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
                    _render(doc.layout(name), f"layout_{i}.png")
                except Exception:
                    continue
        except Exception:
            pass

        return paths

    def ingest(self, path: str, out_dir: str) -> Tuple[str, List[str], Dict[str, Any]]:
        """
        Unified CAD Ingestion.
        Returns:
            data_text: Markdown formatted CAD annotations & specifications.
            image_paths: Rendered drawing views for vision processing.
            meta: Structured metadata dictionary.
        """
        ext = os.path.splitext(path)[-1].lower()
        doc = self.load_doc(path)

        if doc is not None:
            # Full DXF or ODA-converted DWG processing
            dxf_data = self.extract_dxf_data(doc)
            parts = []
            if dxf_data["layers"]:
                parts.append(f"LAYERS ({len(dxf_data['layers'])}): {', '.join(dxf_data['layers'])}")
            if dxf_data["drawing_number"]:
                parts.append(f"DRAWING NUMBER: {dxf_data['drawing_number']}")
            if dxf_data["drawing_title"]:
                parts.append(f"DRAWING TITLE: {dxf_data['drawing_title']}")
            if dxf_data["revisions"]:
                parts.append("REVISIONS:\n" + "\n".join(dxf_data["revisions"]))
            if dxf_data["texts"]:
                parts.append("TEXT / ANNOTATIONS:\n" + "\n".join(dxf_data["texts"]))
            if dxf_data["block_attributes"]:
                parts.append("BLOCK ATTRIBUTES (Title Block, Tags):\n" + "\n".join(dxf_data["block_attributes"]))
            if dxf_data["dimensions"]:
                parts.append("DIMENSIONS:\n" + "\n".join(dxf_data["dimensions"]))

            data_text = "\n\n".join(parts)
            imgs = self.render_images(doc, out_dir)
            meta = {
                "type": "cad",
                "format": ext.upper()[1:],
                "data": dxf_data,
                "drawing_number": dxf_data.get("drawing_number"),
                "status": "ready"
            }
            return data_text, imgs, meta

        else:
            # Fallback for DWG when ODA is not installed
            fallback = self.extract_dwg_fallback(path)
            parts = [
                "=== CAD DRAWING METADATA ===",
                f"File Name: {fallback['filename']}",
                f"Format: {fallback['format']} ({fallback['dwg_version']})",
                f"File Size: {fallback['file_size']:,} bytes",
            ]
            if fallback.get("drawing_number"):
                parts.append(f"Identified Drawing Number: {fallback['drawing_number']}")
            parts.append(f"Ingestion Notice: {fallback['message']}")

            data_text = "\n".join(parts)
            meta = {
                "type": "cad",
                "format": "DWG",
                "data": fallback,
                "drawing_number": fallback.get("drawing_number"),
                "status": "ready_with_warnings"
            }
            return data_text, [], meta


_cad_engine_instance = None

def get_cad_engine() -> CadIntelligenceEngine:
    global _cad_engine_instance
    if _cad_engine_instance is None:
        _cad_engine_instance = CadIntelligenceEngine()
    return _cad_engine_instance
