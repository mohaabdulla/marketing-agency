"""Helpers shared by the video route modules: safe error mapping, tool checks and project loading."""
from fastapi import HTTPException

from video.ffmpeg import binary
from video.projects import Project, migrate_project, save
from video.storage import read


def guard(function, *args, **kwargs):
    """Call a service and turn its failures into safe HTTP errors; messages never carry local paths."""
    try:
        return function(*args, **kwargs)
    except FileNotFoundError:
        raise HTTPException(404, 'Item not found')
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Media operation failed'
        if '\\' in message or '/' in message:
            message = 'Invalid media operation; see local diagnostics'
        raise HTTPException(400, message)


def require_ffmpeg(action):
    """Answer 503 before any work is queued when the local media tools are missing."""
    if not binary('ffmpeg') or not binary('ffprobe'):
        raise HTTPException(503, f'Install FFmpeg and FFprobe before {action}')


def as_project(raw):
    """A stored project dict as a validated Project; bookkeeping fields such as id are left out."""
    return Project.model_validate({key: value for key, value in raw.items() if key in Project.model_fields})


def stored_project(project_id):
    """The stored project dict, migrated to the current schema."""
    return migrate_project(guard(read, 'projects', project_id))


def load_project(project_id):
    return as_project(stored_project(project_id))


def save_plan(project, project_id, plan, actor, instruction, label):
    """Store the result of an edit plan as one labelled revision with its reasons and operation ids."""
    return save(project, project_id, actor=actor, instruction=instruction,
                reason='; '.join(op.reason for op in plan.operations if op.reason),
                operation_ids=[op.operation_id for op in plan.operations], label=label)
