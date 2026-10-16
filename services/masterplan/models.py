"""
Data models for the Masterplan Processing Division (MPD).
Supports spatial geometry, plot schedules, zoning parameters, and audit logging.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class PlotGeometry(BaseModel):
    label_anchor: Optional[List[float]] = Field(default=None, description="Verified leader arrow tip in scaled drawing coordinates")
    coordinates: List[List[float]] = Field(default_factory=list, description="Polygon vertices [[x, y], ...]")
    centroid: Optional[List[float]] = Field(default=None, description="[x, y] centroid")
    bbox: Optional[List[float]] = Field(default=None, description="[min_x, min_y, max_x, max_y]")
    setback_envelope: Optional[List[List[float]]] = Field(default=None, description="Inner setback boundary coordinates")


class MasterplanPlot(BaseModel):
    plot_id: str = Field(..., description="Unique Plot Identifier, e.g. P-101")
    project_id: str = Field(default="C3085 - 3EH -Expo Hills", description="Parent project ID")
    sector: str = Field(default="Sector 1", description="Sector or sub-district name")
    land_use: str = Field(default="Residential", description="Zoning land use category")
    area_sqm: float = Field(default=0.0, description="Plot footprint area in square meters")
    permitted_gfa: float = Field(default=0.0, description="Permitted Gross Floor Area (GFA) in sqm")
    achieved_gfa: float = Field(default=0.0, description="Achieved/Designed GFA in sqm")
    far: float = Field(default=0.0, description="Floor Area Ratio (achieved_gfa / area_sqm)")
    max_far: float = Field(default=2.5, description="Maximum permitted Floor Area Ratio")
    max_height: str = Field(default="G+4", description="Maximum building height / stories")
    max_coverage_pct: float = Field(default=50.0, description="Maximum site coverage percentage")
    front_setback_m: float = Field(default=6.0, description="Front setback requirement in meters")
    rear_setback_m: float = Field(default=4.5, description="Rear setback requirement in meters")
    side_setback_m: float = Field(default=3.0, description="Side setback requirement in meters")
    parking_required: int = Field(default=0, description="Required parking bays")
    parking_provided: int = Field(default=0, description="Provided parking bays")
    status: str = Field(default="compliant", description="Status: compliant, warning, violation, under_review")
    violations: List[str] = Field(default_factory=list, description="List of rule violation descriptions")
    geometry: Optional[PlotGeometry] = Field(default=None, description="Spatial 2D polygon")
    notes: Optional[str] = Field(default="", description="Design review notes")
    updated_at: Optional[str] = Field(default=None, description="ISO timestamp of last update")


class MasterplanProject(BaseModel):
    project_id: str
    name: str
    total_area_sqm: float = 0.0
    total_plots: int = 0
    total_gfa_sqm: float = 0.0
    average_far: float = 0.0
    compliant_plots: int = 0
    warning_plots: int = 0
    violation_plots: int = 0
    land_use_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    boundary: Optional[List[List[float]]] = Field(default=None)


class AuditLogEntry(BaseModel):
    id: str
    project_id: str
    timestamp: str
    action_type: str
    plot_id: Optional[str] = None
    description: str
    previous_state: Optional[Dict[str, Any]] = None
    new_state: Optional[Dict[str, Any]] = None
    author: str = "Design Review Meeting"


class MasterplanAIQueryRequest(BaseModel):
    query: str
    project_id: str = "C3085 - 3EH -Expo Hills"
    selected_plot_id: Optional[str] = None


class MasterplanAIQueryResponse(BaseModel):
    view_actions: List[Dict[str, Any]] = Field(default_factory=list)
    answer: str
    intent: str
    tools_called: List[str] = Field(default_factory=list)
    highlight_plots: List[str] = Field(default_factory=list)
    highlight_color: Optional[str] = None
    kpis: Optional[Dict[str, Any]] = None
    confidence: float = 1.0
    action_performed: Optional[str] = None
    html: Optional[str] = None
    reconciliation: Optional[Dict[str, Any]] = None
