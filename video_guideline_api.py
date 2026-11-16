"""Brand-aware Video Editor controls using existing timeline, renderer and revisions."""
from fastapi import HTTPException, UploadFile, File
from pydantic import Field
from video_api import router, guard
from video_projects import Strict, save
from video_storage import read
import brand_guidelines as g
import video_brand_editing as edits


@router.post('/projects/{project_id}/captions/import')
async def import_captions(project_id: str,file: UploadFile=File(...)):
    from video_captions import parse_srt
    from video_projects import Clip
    from video_storage import DATA,uid
    import hashlib
    import re
    try:
        raw=await file.read(256*1024+1)
        if not (file.filename or '').lower().endswith('.srt') or len(raw)>256*1024:
            raise HTTPException(400,'Import a UTF-8 SRT subtitle file up to 256 KB')
        try:
            text=raw.decode('utf-8-sig')
            if any(ord(c)<32 and c not in '\r\n\t' for c in text):
                raise ValueError('Invalid control characters')
            blocks=[b for b in text.replace('\r\n','\n').strip().split('\n\n') if b.strip()]
            for block in blocks:
                lines=block.strip().splitlines()
                if len(lines)<3 or not re.fullmatch(r'\d{1,8}',lines[0]) or len(lines[1])>60 or len('\n'.join(lines[2:]))>500:
                    raise ValueError('Invalid SRT block')
            segments=parse_srt(text)
            if not segments or len(segments)!=text.count('-->'):
                raise ValueError('Malformed caption timing')
        except Exception:
            raise HTTPException(400,'Invalid UTF-8 SRT captions')
        project=edits.model(guard(read,'projects',project_id))
        total=__import__('video_editor').primary_layout(project)[1]
        remaining=[c for c in project.clips if c.caption_style_id!='imported-srt']
        if len(remaining)+len(segments)>60:
            raise HTTPException(400,'Caption import exceeds the 60-clip rendering budget; combine cues or shorten the edit')
        previous=0
        for cue in segments:
            if cue.start<previous or cue.end<=cue.start or cue.end>total+.01 or len(cue.text)>500:
                raise HTTPException(400,'Captions must be ordered, non-overlapping, within the timeline, and at most 500 characters each')
            previous=cue.end
            remaining.append(Clip(kind='title',text=cue.text,start=cue.start,duration=cue.end-cue.start,
                                  text_role='caption',caption_style_id='imported-srt',font='arabic' if re.search(r'[\u0600-\u06ff]',cue.text) else 'sans',
                                  font_size=40,color='#ffffff',x=.5,y=.72))
        original=DATA/'caption-originals'
        original.mkdir(exist_ok=True)
        key=uid()
        (original/(key+'.srt')).write_bytes(raw)
        project.clips=remaining
        project.caption_tracks=[dict(id=key,source='imported',sha256=hashlib.sha256(raw).hexdigest(),burn_in=True,
                                     segments=[s.model_dump() for s in segments])]
        return guard(save,project,project_id,'user','Imported reviewed SRT captions')
    finally:
        await file.close()


@router.get('/editor/capabilities')
def editor_status():
    from video_transcription import status
    return dict(ai=edits.ai_status(), speech=status(), quick_edit=True, deterministic=True, supported_operations=list(edits.SUPPORTED),
                fonts=list(__import__('video_fonts').FONTS))


class Association(Strict):
    guideline_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')


@router.post('/projects/{project_id}/guidelines')
def attach(project_id: str, body: Association):
    project = edits.model(guard(read,'projects',project_id))
    if body.guideline_id:
        doc = guard(g.get,body.guideline_id)
        if not doc['confirmed']:
            raise HTTPException(409,'Review and confirm the extracted rules before applying them')
        project.guideline_id, project.guideline_version, project.brand_rules = doc['id'], doc['version'], doc['rules']
    else:
        project.guideline_id = project.guideline_version = project.brand_rules = None
    return guard(save,project,project_id, 'user','Updated guideline association')


class PlanRequest(Strict):
    instruction: str = Field('Apply the reviewed brand guidelines with clean, subtle styling.', min_length=1,max_length=1000)
    engine: str = Field('rule_engine', pattern=r'^(rule_engine|local_ai)$')
    repair_only: bool = False


@router.post('/projects/{project_id}/brand-edit/preview')
def preview(project_id: str, body: PlanRequest):
    return guard(edits.preview,project_id,body.instruction,body.engine,body.repair_only)


class Apply(Strict):
    plan_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirm_conflicts: bool = False


@router.post('/projects/{project_id}/brand-edit/apply')
def apply(project_id: str, body: Apply):
    return guard(edits.apply,project_id,body.plan_id,body.confirm_conflicts)


@router.delete('/projects/{project_id}/brand-edit/plans/{plan_id}')
def reject(project_id: str, plan_id: str):
    return guard(edits.reject,project_id,plan_id)


@router.get('/projects/{project_id}/brand-compliance')
def compliance(project_id: str):
    return guard(edits.compliance,edits.model(guard(read,'projects',project_id)))
