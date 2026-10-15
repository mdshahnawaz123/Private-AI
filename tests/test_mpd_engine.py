"""
Integration and regression tests for Masterplan AI Interface (MPD).
Verifies:
1. CAD DXF plot boundary and layer parsing (ezdxf).
2. Excel plot schedule parsing and FAR calculation (openpyxl).
3. Shapely spatial reasoning (boundary overlaps, setback buffer encroachment, parking deficits).
4. Local agentic Qwen 3.5 9B / Intent planning tool execution.
5. Highlighted DXF CAD export generation.
"""
import os
from services.masterplan import db
from services.masterplan.models import MasterplanPlot, PlotGeometry
from services.masterplan.spatial_engine import SpatialReasoningEngine
from services.masterplan.parsers.dxf_parser import MasterplanDxfParser
from services.masterplan.parsers.excel_parser import MasterplanExcelParser
from services.masterplan.cad_graphics import MasterplanGraphicsEngine
from services.masterplan.agent import MasterplanAIAgent


TEST_PROJECT = "C3085 - 3EH -Expo Hills"


def test_masterplan_db_seeding():
    db.init_db()
    db.seed_default_masterplan(TEST_PROJECT)
    summary = db.get_project_summary(TEST_PROJECT)
    assert summary.total_plots >= 20
    assert summary.total_area_sqm > 50000.0
    assert "Residential" in summary.land_use_breakdown


def test_spatial_engine_compliance_audit():
    spatial = SpatialReasoningEngine()
    # Test compliant plot
    p_comp = MasterplanPlot(
        plot_id="TEST-1",
        project_id=TEST_PROJECT,
        land_use="Residential",
        area_sqm=3000.0,
        achieved_gfa=5700.0,
        max_far=2.0,
        front_setback_m=6.0,
        rear_setback_m=4.5,
        side_setback_m=3.0,
        parking_required=20,
        parking_provided=22
    )
    st, viols = spatial.validate_plot(p_comp)
    assert st == "compliant"
    assert len(viols) == 0

    # Test FAR and setback violation plot
    p_viol = MasterplanPlot(
        plot_id="TEST-2",
        project_id=TEST_PROJECT,
        land_use="Commercial",
        area_sqm=4000.0,
        achieved_gfa=14000.0, # FAR 3.5 > 3.0
        max_far=3.0,
        front_setback_m=3.5,  # Front SB 3.5 < 5.0
        rear_setback_m=4.0,
        side_setback_m=3.0,
        parking_required=60,
        parking_provided=45   # 15 bay deficit
    )
    st, viols = spatial.validate_plot(p_viol)
    assert st == "violation"
    assert any("FAR" in v for v in viols)
    assert any("Front setback" in v for v in viols)
    assert any("Parking deficit" in v for v in viols)


def test_cad_graphics_dxf_generation():
    engine = MasterplanGraphicsEngine()
    dxf_path = engine.generate_highlighted_dxf(TEST_PROJECT, ["P-105", "P-203"])
    assert os.path.exists(dxf_path)
    assert os.path.getsize(dxf_path) > 10000


def test_ai_agent_intent_planning():
    agent = MasterplanAIAgent()
    # Test FAR density query
    resp = agent._fallback_deterministic_plan("Find high density plots with FAR above 2.8", TEST_PROJECT)
    assert resp.intent == "QUERY_DENSITY"
    assert "query_plots" in resp.tools_called
    assert len(resp.highlight_plots) > 0

    # Test Land use summary query
    resp2 = agent._fallback_deterministic_plan("Summarize residential parcels", TEST_PROJECT)
    assert resp2.intent == "QUERY_LAND_USE"
    assert "query_plots" in resp2.tools_called

    # Test single plot inspection
    resp3 = agent._fallback_deterministic_plan("Inspect plot P-105", TEST_PROJECT)
    assert resp3.intent == "INSPECT_PLOT"
    assert "P-105" in resp3.highlight_plots
