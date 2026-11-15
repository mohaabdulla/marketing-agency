"""Persistent, non-destructive revision history and undo/redo state for video projects."""
import hashlib
import json
import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from video_storage import DATA, LOCK, atomic, uid, identifier, read

ActorType = Literal['user', 'ai', 'rule_engine', 'migration', 'system']


class Revision(BaseModel):
    id: str = Field(default_factory=uid)
    project_id: str
    parent_id: Optional[str] = None
    revision_number: int = 1
    created_at: float = Field(default_factory=time.time)
    actor: ActorType = 'user'
    instruction: str = ''
    operation_ids: List[str] = Field(default_factory=list)
    reason: str = ''
    label: Optional[str] = None
    project_state: Dict[str, Any]
    state_hash: str = ''
    edit_plan: Optional[Dict[str, Any]] = None
    render_asset_id: Optional[str] = None
    qa_report: Optional[Dict[str, Any]] = None
    editorial_report: Optional[Dict[str, Any]] = None
    parent_render_revision_id: Optional[str] = None


def _hash_state(state: Dict[str, Any]) -> str:
    cleaned = {k: v for k, v in state.items() if k not in ('id', 'updated', 'created')}
    raw = json.dumps(cleaned, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:16]


def _revisions_dir(project_id: str):
    p = DATA / 'revisions' / identifier(project_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path(project_id: str):
    return _revisions_dir(project_id) / 'index.json'


def _load_index(project_id: str) -> Dict[str, Any]:
    idx_p = _index_path(project_id)
    if idx_p.is_file():
        try:
            return json.loads(idx_p.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {'active_revision_id': None, 'history': []}


def _save_index(project_id: str, data: Dict[str, Any]):
    atomic(_index_path(project_id), data)


def record_revision(
    project_id: str,
    project_state: Dict[str, Any],
    actor: ActorType = 'user',
    instruction: str = '',
    reason: str = '',
    operation_ids: Optional[List[str]] = None,
    label: Optional[str] = None,
    edit_plan=None, render_asset_id=None, qa_report=None, editorial_report=None, parent_render_revision_id=None,
) -> Revision:
    """Record a persistent revision snapshot. Never destructively overwrites history."""
    with LOCK:
        project_id = identifier(project_id)
        index = _load_index(project_id)
        history = index.get('history', [])
        parent_id = index.get('active_revision_id')

        rev_num = len(history) + 1
        rev_id = uid()
        state_hash = _hash_state(project_state)

        # Check if the state is identical to the active revision to prevent useless duplicate snapshots
        if parent_id:
            parent_rev = get_revision(project_id, parent_id)
            if parent_rev and parent_rev.get('state_hash') == state_hash and not instruction and not label and not render_asset_id:
                return Revision(**parent_rev)

        rev = Revision(
            id=rev_id,
            project_id=project_id,
            parent_id=parent_id,
            revision_number=rev_num,
            created_at=time.time(),
            actor=actor,
            instruction=instruction,
            operation_ids=operation_ids or [],
            reason=reason,
            label=label,
            project_state=project_state,
            state_hash=state_hash,
            edit_plan=edit_plan, render_asset_id=render_asset_id, qa_report=qa_report,
            editorial_report=editorial_report, parent_render_revision_id=parent_render_revision_id,
        )

        rev_file = _revisions_dir(project_id) / f"{rev_id}.json"
        atomic(rev_file, rev.model_dump(mode='json'))

        history.append({
            'id': rev.id,
            'parent_id': rev.parent_id,
            'revision_number': rev.revision_number,
            'created_at': rev.created_at,
            'actor': rev.actor,
            'instruction': rev.instruction,
            'operation_ids': rev.operation_ids,
            'reason': rev.reason,
            'label': rev.label,
            'state_hash': rev.state_hash,
            'render_asset_id': render_asset_id,
            'parent_render_revision_id': parent_render_revision_id,
        })
        index['active_revision_id'] = rev.id
        index['history'] = history
        _save_index(project_id, index)
        return rev


def get_revisions(project_id: str) -> List[Dict[str, Any]]:
    """List all revision summaries in chronological order with active pointer."""
    with LOCK:
        project_id = identifier(project_id)
        index = _load_index(project_id)
        active_id = index.get('active_revision_id')
        items = []
        for h in index.get('history', []):
            items.append({**h, 'is_active': h['id'] == active_id})
        return items


def get_revision(project_id: str, revision_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full revision snapshot."""
    with LOCK:
        project_id = identifier(project_id)
        revision_id = identifier(revision_id)
        path = _revisions_dir(project_id) / f"{revision_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding='utf-8'))


def restore_revision(project_id: str, revision_id: str) -> Dict[str, Any]:
    """Restore a previous revision, updating the active pointer and returning project state."""
    with LOCK:
        project_id = identifier(project_id)
        revision_id = identifier(revision_id)
        rev = get_revision(project_id, revision_id)
        if not rev:
            raise FileNotFoundError(f"Revision '{revision_id}' not found")

        state = rev['project_state']
        # Record the restoration as a new revision event preserving full DAG history
        new_rev = record_revision(
            project_id=project_id,
            project_state=state,
            actor='user',
            instruction=f"Restore revision #{rev['revision_number']}",
            reason=f"Restored to revision {revision_id}",
            label=f"Restored #{rev['revision_number']}"
        )
        # Update current project file
        from video_storage import atomic, DATA
        state['id'] = project_id
        state['updated'] = time.time()
        atomic(DATA / 'projects' / (project_id + '.json'), state)
        return state


def undo(project_id: str) -> Optional[Dict[str, Any]]:
    """Navigate backwards to the parent revision."""
    with LOCK:
        project_id = identifier(project_id)
        index = _load_index(project_id)
        active_id = index.get('active_revision_id')
        if not active_id:
            return None
        active_rev = get_revision(project_id, active_id)
        if not active_rev or not active_rev.get('parent_id'):
            return None  # At earliest revision

        parent_id = active_rev['parent_id']
        parent_rev = get_revision(project_id, parent_id)
        if not parent_rev:
            return None

        index['active_revision_id'] = parent_id
        _save_index(project_id, index)

        state = parent_rev['project_state']
        state['id'] = project_id
        state['updated'] = time.time()
        atomic(DATA / 'projects' / (project_id + '.json'), state)
        return state


def redo(project_id: str) -> Optional[Dict[str, Any]]:
    """Navigate forward to the child revision if available in history."""
    with LOCK:
        project_id = identifier(project_id)
        index = _load_index(project_id)
        active_id = index.get('active_revision_id')
        history = index.get('history', [])

        if not active_id and history:
            child_id = history[0]['id']
        else:
            # Find the first child whose parent is active_id
            children = [h for h in history if h.get('parent_id') == active_id]
            if not children:
                return None  # At latest revision
            child_id = children[-1]['id']  # Most recent child

        child_rev = get_revision(project_id, child_id)
        if not child_rev:
            return None

        index['active_revision_id'] = child_id
        _save_index(project_id, index)

        state = child_rev['project_state']
        state['id'] = project_id
        state['updated'] = time.time()
        atomic(DATA / 'projects' / (project_id + '.json'), state)
        return state

