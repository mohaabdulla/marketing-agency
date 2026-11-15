"""Orchestration for CPU animation, audio extraction and isolated local diffusion."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal
from pydantic import Field, PrivateAttr
from video_projects import Strict, Project, Clip, Canvas, CreativeContext
from video_storage import DATA, ROOT, read, space
from video_assets import path_for, ingest, annotate
from video_ffmpeg import ffmpeg, probe, Cancelled, stop_process
from video_editor import render
from video_models import CACHE, PYTHON, MODELS, statuses
from gpu_resources import gpu_slot


def spawn_worker(*args, **kwargs):
    return subprocess.Popen(*args, **kwargs)


class Generate(Strict):
    mode: Literal['text-to-video', 'image-to-video', 'image-animation'] = 'text-to-video'
    model: Literal['cogvideox-2b', 'wan21-i2v-480p', 'wan21-t2v-480p', 'wan22-ti2v-5b'] = 'cogvideox-2b'
    prompt: str = Field('', max_length=2000)
    negative_prompt: str = Field('', max_length=1000)
    camera: str = Field('', max_length=250)
    asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    seed: int = Field(42, ge=0, le=2**31-1)
    quality: Literal['draft', 'standard'] = 'standard'
    duration: float = Field(4, ge=1, le=15)
    aspect: Literal['16:9', '9:16', '1:1', '4:5'] = '16:9'
    resolution: Literal[720, 1080] = 720
    motion: Literal['zoom-in', 'zoom-out', 'pan', 'still'] = 'zoom-in'
    guideline_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    guideline_version: int | None = Field(None, ge=1)
    objective: str = Field('', max_length=1000)
    audience: str = Field('', max_length=500)
    key_message: str = Field('', max_length=1000)
    style: str = Field('', max_length=500)
    cta: str = Field('', max_length=500)
    platform: str = Field('', max_length=100)
    language: Literal['en','ar','ar-BH'] = 'en'
    _rules: dict | None = PrivateAttr(default=None)
    _version: int | None = PrivateAttr(default=None)


def prepare_brand(request):
    """Freeze reviewed, workspace-owned rules before enqueueing a generation job."""
    if not request.guideline_id:
        return
    from brand_guidelines import get, Rules
    doc = get(request.guideline_id)
    if not doc['confirmed']:
        raise ValueError('Review and confirm the guideline before generating')
    if request.guideline_version and request.guideline_version != doc['version']:
        raise ValueError('The guideline changed. Review the latest version before generating')
    rules = Rules.model_validate(doc['rules'])
    if rules.logo_asset_id:
        path_for(rules.logo_asset_id)
    request._rules, request._version = rules.model_dump(), doc['version']


def branded_project(project, request):
    """Use the same validated styling operations as the editor, retaining a revision."""
    from brand_guidelines import Rules
    from video_brand_editing import polish, checked, compliance
    from video_projects import save
    project.guideline_id = request.guideline_id
    project.guideline_version = request._version
    project.brand_rules = request._rules
    project.creative_context = CreativeContext(**{key:getattr(request,key) for key in CreativeContext.model_fields})
    rules = Rules.model_validate(request._rules) if request._rules else Rules(cta=request.cta,language='ar' if request.language.startswith('ar') else 'en')
    plan = polish(project, 'Apply reviewed brand guidelines with subtle professional styling.', rules) if request._rules or request.cta else None
    if plan: project = checked(project, plan)
    saved = save(project, actor='rule_engine', instruction=request.prompt or request.objective,
                 label='Generated clip with reviewed brand guidelines' if request.guideline_id else 'Generated clip')
    findings = compliance(project)
    warnings = plan.warnings + plan.unfulfilled_requests if plan else []
    warnings += [f['message'] for f in findings['findings'] if f['state'] in {'FAIL','WARNING'}]
    return project, saved['id'], warnings


def generation_prompt(request):
    lines = [request.prompt]
    for label,key in [('Objective','objective'),('Audience','audience'),('Key message','key_message'),('Style','style'),('CTA','cta'),('Platform','platform'),('Language','language')]:
        if getattr(request,key): lines.append(label+': '+getattr(request,key))
    if request._rules:
        # These instructions go to the real diffusion worker; unsupported semantics
        # remain explicit in compliance rather than being claimed as enforced.
        lines.append('Reviewed brand context: '+json.dumps(request._rules,ensure_ascii=False))
        lines.append('Preserve source identities. No invented claims or transcript text.')
    return '\n'.join(lines)


def canvas_for(aspect, resolution):
    a, b = map(int, aspect.split(':'))
    w, h = (resolution * a/b, resolution) if a >= b else (resolution, resolution * b/a)
    return Canvas(width=round(w/2)*2, height=round(h/2)*2)


def check_generate(request):
    if request.guideline_id and request._rules is None:
        prepare_brand(request)
    if request.mode != 'text-to-video':
        if not request.asset_id or read('assets', request.asset_id)['kind'] != 'image':
            raise ValueError('Select a still image from the media library')
    if request.mode == 'image-animation':
        return
    if not request.prompt.strip():
        raise ValueError('A scene prompt is required')
    model = next(m for m in statuses() if m['id'] == request.model)
    if request.mode not in model['modes']:
        raise ValueError('This model does not support the selected generation mode')
    if not model['available']:
        raise ValueError('; '.join(model['reasons']))


def generate(request, job):
    check_generate(request)
    canvas = canvas_for(request.aspect, request.resolution)
    if request.mode == 'image-animation':
        project = Project(name='Image Animation', canvas=canvas, clips=[Clip(asset_id=request.asset_id,
            zoom_start=1.18 if request.motion == 'zoom-out' else 1,
            duration=request.duration, zoom=1.18 if request.motion == 'zoom-in' else 1.08 if request.motion == 'pan' else 1,
            pan=.8 if request.motion == 'pan' else 0, fade_in=.4, fade_out=.4)])
        project, project_id, warnings = branded_project(project, request)
        result = render(project, job, audio=False)
        return annotate(result, generation_type='deterministic-image-animation', name='Image Animation.mp4',
                        project_id=project_id, guideline_id=request.guideline_id, guideline_version=request._version,
                        brand_warnings=warnings, creation_prompt=generation_prompt(request))
    with gpu_slot(job.cancelled), tempfile.TemporaryDirectory(dir=DATA / 'work', prefix=job.id + '-') as temp:
        # Recheck free VRAM after acquiring the cross-workspace GPU lock.
        from video_models import hardware
        config = MODELS[request.model]
        hw = hardware()
        if not hw['gpu'] or hw['gpu']['free_gb'] < config['vram_gb']:
            raise ValueError('Insufficient free VRAM. Close other GPU applications and retry.')
        space(512*1024**2)
        tmp = Path(temp)
        payload = dict(request.model_dump(), model_path=str(CACHE / request.model), output=str(tmp/'native.mp4'),
                       progress=str(tmp/'progress.json'), **{k:config[k] for k in ['width','height','frames','fps']})
        payload['prompt'] = generation_prompt(request)
        if request.asset_id:
            payload['image'] = str(path_for(request.asset_id))
        (tmp/'request.json').write_text(json.dumps(payload), encoding='utf-8')
        environment = {**os.environ, 'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1', 'PYTHONIOENCODING':'utf-8'}
        job.update(state='preparing', phase='Loading local model', progress=None)
        with (DATA/'jobs'/(job.id+'.worker.log')).open('w', encoding='utf-8') as log:
            process = spawn_worker([str(PYTHON), '-u', str(ROOT/'scripts/render_local_video.py'), str(tmp/'request.json')],
                cwd=ROOT, env=environment, stdout=log, stderr=log, shell=False,
                start_new_session=os.name!='nt',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            started, last = time.monotonic(), None
            try:
                while process.poll() is None:
                    if job.cancelled():
                        raise Cancelled()
                    if time.monotonic()-started > 1800:
                        raise ValueError('AI inference exceeded the 30 minute time limit')
                    try:
                        progress = json.loads((tmp/'progress.json').read_text())
                        if progress != last:
                            job.update(state='running', phase='Denoising', progress=progress)
                            last = progress
                    except (OSError, ValueError):
                        pass
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    stop_process(process)
                process.wait()
        if process.returncode or not (tmp/'native.mp4').is_file():
            details = (DATA/'jobs'/(job.id+'.worker.log')).read_text(encoding='utf-8')
            if 'out of memory' in details.lower():
                raise ValueError('GPU out of memory. Use Image Animation or a larger GPU.')
            raise ValueError('Local AI worker failed; see local job diagnostics')
        native = probe(tmp/'native.mp4')
        if (native['width'],native['height']) != (config['width'],config['height']) or abs(native['duration']-config['frames']/config['fps']) > .2:
            raise ValueError('AI worker output does not match the expected native dimensions or duration')
        # Keep native dimensions explicit; only the export is resized/padded.
        job.update(state='encoding', phase='Padding and resizing native AI output', progress=None)
        ffmpeg(['-i', str(tmp/'native.mp4'), '-vf',
            f'scale={canvas.width}:{canvas.height}:force_original_aspect_ratio=decrease,pad={canvas.width}:{canvas.height}:(ow-iw)/2:(oh-ih)/2',
            '-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(tmp/'generated.mp4')],job)
        result = ingest(tmp/'generated.mp4', 'AI-generated.mp4')
        project = Project(name='Generated AI clip',canvas=canvas,clips=[Clip(asset_id=result['id'],duration=result['duration'])])
        project, project_id, warnings = branded_project(project, request)
        if request.guideline_id or request.cta:
            result = render(project,job,audio=False)
        manifest=json.loads((CACHE/request.model/'installation.json').read_text(encoding='utf-8'))
        return annotate(result, generation_type=request.mode, native_width=config['width'], native_height=config['height'],
                        seed=request.seed, model=request.model, revision=manifest['revision'],project_id=project_id,
                        guideline_id=request.guideline_id,guideline_version=request._version,
                        brand_warnings=warnings,creation_prompt=generation_prompt(request))


def extract_audio(asset_id, job):
    if not read('assets', asset_id).get('has_audio'):
        raise ValueError('This asset has no audio stream')
    with tempfile.TemporaryDirectory(dir=DATA/'work') as tmp:
        out = Path(tmp)/'extracted.wav'
        job.update(state='encoding', phase='Extracting audio')
        ffmpeg(['-i',str(path_for(asset_id)),'-vn','-c:a','pcm_s16le',str(out)],job)
        return ingest(out, out.name)
