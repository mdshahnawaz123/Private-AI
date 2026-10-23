from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
import re
from typing import Annotated
import auth
from services.bim_action_planner import plan_actions

router = APIRouter(prefix='/api/bim', tags=['BIM view tools'])

class PlanRequest(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    categories: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=250)

@router.post('/plan-view-action')
async def plan_view_action(body: PlanRequest, request: Request):
    auth.require_project(request, body.project)
    # Do not send arbitrary model text as system instructions or accept arbitrary tools.
    categories = sorted({c.upper() for c in body.categories if re.fullmatch(r'IFC[A-Z0-9_]{1,90}', c.upper())})
    return await plan_actions(body.question, categories, project=body.project)
