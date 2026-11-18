"""Brand guidelines on a video project: attaching a reviewed guideline, brand-edit plans
(preview, apply, reject) and the brand compliance report."""
from fastapi import APIRouter, HTTPException
from pydantic import Field

from brand import guidelines
from video import brand_editing as edits
from video.projects import Strict, save
from video.routes.common import guard
from video.storage import read

router = APIRouter()


class Association(Strict):
    guideline_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')


@router.post('/projects/{project_id}/guidelines')
def attach(project_id: str, body: Association):
    project = edits.model(guard(read, 'projects', project_id))
    if body.guideline_id:
        doc = guard(guidelines.get, body.guideline_id)
        if not doc['confirmed']:
            raise HTTPException(409, 'Review and confirm the extracted rules before applying them')
        project.guideline_id, project.guideline_version, project.brand_rules = doc['id'], doc['version'], doc['rules']
    else:
        project.guideline_id = project.guideline_version = project.brand_rules = None
    return guard(save, project, project_id, 'user', 'Updated guideline association')


class PlanRequest(Strict):
    instruction: str = Field('Apply the reviewed brand guidelines with clean, subtle styling.', min_length=1, max_length=1000)
    engine: str = Field('rule_engine', pattern=r'^(rule_engine|local_ai)$')
    repair_only: bool = False


@router.post('/projects/{project_id}/brand-edit/preview')
def preview(project_id: str, body: PlanRequest):
    return guard(edits.preview, project_id, body.instruction, body.engine, body.repair_only)


class Apply(Strict):
    plan_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirm_conflicts: bool = False


@router.post('/projects/{project_id}/brand-edit/apply')
def apply(project_id: str, body: Apply):
    return guard(edits.apply, project_id, body.plan_id, body.confirm_conflicts)


@router.delete('/projects/{project_id}/brand-edit/plans/{plan_id}')
def reject(project_id: str, plan_id: str):
    return guard(edits.reject, project_id, plan_id)


@router.get('/projects/{project_id}/brand-compliance')
def compliance(project_id: str):
    return guard(edits.compliance, edits.model(guard(read, 'projects', project_id)))
