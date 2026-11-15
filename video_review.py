"""Scoped review events for rendered assets; review never rewrites the source or render."""
import time
from typing import Literal
from pydantic import Field
from video_projects import Strict
from video_storage import DATA, LOCK, atomic, read, identifier, space

State = Literal['DRAFT', 'INTERNAL_REVIEW', 'CLIENT_REVIEW', 'APPROVED', 'FINAL']


class ReviewRequest(Strict):
    state: State
    note: str = Field('', max_length=1000)


def review_record(asset_id):
    asset = read('assets', asset_id)
    if not asset.get('render_revision_id'):
        raise ValueError('Review is available for rendered edits with a saved revision.')
    path = DATA / 'reviews' / (identifier(asset_id) + '.json')
    if path.is_file():
        return read('reviews', asset_id)
    caption = (asset.get('edit_report') or {}).get('caption_state', 'none').upper().replace('-', '_')
    return dict(asset_id=asset_id, state='DRAFT', caption_state=caption, events=[])


def set_review(asset_id, body):
    with LOCK:
        asset = read('assets', asset_id)
        record = review_record(asset_id)
        order = ['DRAFT', 'INTERNAL_REVIEW', 'CLIENT_REVIEW', 'APPROVED', 'FINAL']
        current = record['state']
        if body.state == current:
            return record
        if body.state != 'DRAFT' and order.index(body.state) != order.index(current) + 1:
            raise ValueError('Move through internal review, client review, approval and final in order, or return to draft.')
        if body.state in ('APPROVED', 'FINAL'):
            editorial = asset.get('editorial_report') or {}
            if editorial.get('publish_readiness') != 'READY' or (asset.get('qa_report') or {}).get('overall') == 'FAIL':
                raise ValueError('Resolve caption review, pending cuts and failed QA before approval. Draft download remains available.')
        if len(record['events']) >= 100:
            raise ValueError('Review event limit reached for this render; create a new revision.')
        space(16384)
        record['events'].append(dict(previous=current, state=body.state, note=body.note, timestamp=time.time()))
        record['state'] = body.state
        if (asset.get('edit_report') or {}).get('caption_count'):
            record['caption_state'] = 'LOCKED' if body.state == 'FINAL' else 'APPROVED' if body.state == 'APPROVED' else (asset['edit_report']['caption_state'].upper().replace('-', '_'))
        (DATA / 'reviews').mkdir(exist_ok=True)
        atomic(DATA / 'reviews' / (asset_id + '.json'), record)
        return record
