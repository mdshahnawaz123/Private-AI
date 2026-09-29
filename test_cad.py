"""CAD ingestion smoke test. Run where requirements are installed: python test_cad.py"""
import sys
import cad

ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

check("is_cad detects dwg/dxf, not pdf", cad.is_cad("a.DWG") and cad.is_cad("b.dxf") and not cad.is_cad("c.pdf"))

try:
    import ezdxf
except Exception:
    print("INFO  ezdxf not installed yet - run `pip install -r requirements.txt`, then re-run.")
    sys.exit(0 if ok else 1)

doc = ezdxf.new()
doc.layers.add("A-WALL")
msp = doc.modelspace()
msp.add_text("ROOM 101", dxfattribs={"layer": "A-WALL"})
msp.add_mtext("GENERAL NOTE: verify egress width per code")
data = cad.extract_data(doc)
check("extracts layer name", "A-WALL" in data)
check("extracts TEXT",       "ROOM 101" in data)
check("extracts MTEXT note", "egress width" in data)

try:
    import matplotlib  # noqa
    print("INFO  matplotlib present - drawing render path available")
except Exception:
    print("INFO  matplotlib not installed - render-for-vision path will be skipped until installed")

print("\n" + ("ALL CAD TESTS PASSED" if ok else "SOME TESTS FAILED"))
sys.exit(0 if ok else 1)
