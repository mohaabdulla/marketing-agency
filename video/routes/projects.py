"""Projects, revision history and human creative review."""
from fastapi import APIRouter, HTTPException

from video.editor import validate_sources
from video.projects import Project, migrate_project, save
from video.review import RUBRIC_CATEGORIES, ReviewRequest, RubricRequest, review_record, set_review, set_rubric
from video.revisions import get_revision, get_revisions, redo, restore_revision, undo
from video.routes.common import guard
from video.storage import DATA, identifier, listing, read

router = APIRouter()


# ------------------------------------------------------------------ projects

@router.post('/projects')
def create_project(body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body, actor='user', instruction='Initial project creation')


@router.get('/projects')
def projects():
    return [migrate_project(p) for p in listing('projects')]


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    raw = guard(read, 'projects', project_id)
    return migrate_project(raw)


@router.put('/projects/{project_id}')
def save_project_endpoint(project_id: str, body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body, project_id, actor='user', instruction='Manual timeline edits')


@router.post('/projects/{project_id}/duplicate')
def duplicate_project(project_id: str):
    old = guard(read, 'projects', project_id)
    migrated = migrate_project(old)
    body = Project(**{k: v for k, v in migrated.items() if k not in ('id', 'created', 'updated')})
    body.name = (body.name[:110] + ' copy')
    return guard(save, body, actor='user', instruction=f"Duplicated from {project_id}")


@router.delete('/projects/{project_id}')
def delete_project(project_id: str):
    guard(read, 'projects', project_id)
    (DATA / 'projects' / (identifier(project_id) + '.json')).unlink()
    return dict(deleted=True)


# ------------------------------------------------------------------ revisions

@router.get('/projects/{project_id}/revisions')
def list_revisions(project_id: str):
    guard(read, 'projects', project_id)
    return {'revisions': get_revisions(project_id)}


@router.get('/projects/{project_id}/revisions/{revision_id}')
def get_revision_snapshot(project_id: str, revision_id: str):
    guard(read, 'projects', project_id)
    rev = get_revision(project_id, revision_id)
    if not rev:
        raise HTTPException(404, f"Revision {revision_id} not found")
    return rev


@router.post('/projects/{project_id}/revisions/{revision_id}/restore')
def restore_revision_endpoint(project_id: str, revision_id: str):
    guard(read, 'projects', project_id)
    return guard(restore_revision, project_id, revision_id)


@router.post('/projects/{project_id}/undo')
def undo_endpoint(project_id: str):
    guard(read, 'projects', project_id)
    res = undo(project_id)
    if not res:
        raise HTTPException(400, 'Cannot undo: already at the earliest revision')
    return res


@router.post('/projects/{project_id}/redo')
def redo_endpoint(project_id: str):
    guard(read, 'projects', project_id)
    res = redo(project_id)
    if not res:
        raise HTTPException(400, 'Cannot redo: already at the latest revision')
    return res


# ------------------------------------------------------------------ human review of rendered videos

@router.get('/assets/{asset_id}/review')
def get_asset_review(asset_id: str):
    return guard(review_record, asset_id)


@router.post('/assets/{asset_id}/review')
def update_asset_review(asset_id: str, body: ReviewRequest):
    return guard(set_review, asset_id, body)


@router.post('/assets/{asset_id}/rubric')
def save_creative_rubric(asset_id: str, body: RubricRequest):
    return guard(set_rubric, asset_id, body)


@router.get('/creative-review/rubric')
def creative_rubric():
    return dict(categories=RUBRIC_CATEGORIES, scale=[1, 2, 3, 4, 5], basis='HUMAN_REVIEW_ONLY',
                notice='Ratings describe a person\'s judgment, not an automated professional quality score.')
