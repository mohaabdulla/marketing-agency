"""Producer-owned governance, immutable takes and human gates over the existing local video engine."""
import copy
import hashlib
import json
import tempfile
import time
from pathlib import Path

from video.storage import DATA,LOCK,atomic,read,uid
from video.production_schemas import ShotInput


class ProductionConflict(ValueError):pass


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def get(key):
    with LOCK:
        record=read('productions',key)
        if record.get('busy_job'):
            from video.jobs import jobs,TERMINAL
            try:terminal=jobs.status(record['busy_job'])['state'] in TERMINAL
            except FileNotFoundError:terminal=True
            if terminal:
                record['busy_job']=None;_save(record,'job-recovered',dict(note='The queued worker is no longer active.'))
        return record


def listings():
    folder=DATA/'productions'
    return [dict(id=p.stem,name=value['name'],version=value['version'],updated=value['updated'],stage=value['stage'])
        for p in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]
        for value in [json.loads(p.read_text(encoding='utf-8'))]]


def _save(record,action,detail=None):
    record['version']+=1;record['updated']=time.time()
    record['events'].append(dict(action=action,detail=detail or {},version=record['version'],at=record['updated']))
    if len(record['events'])>500:raise ValueError('Production history is full. Create a new production to continue.')
    (DATA/'productions').mkdir(parents=True,exist_ok=True)
    atomic(DATA/'productions'/(record['id']+'.json'),record)
    return record


def _editable(record,version):
    if record['version']!=version:raise ProductionConflict('Production changed. Reload before applying this change.')
    if record.get('busy_job'):raise ProductionConflict('A production job is running. Wait for it or cancel it in the production queue.')


def _shot(record,key):
    shot=next((s for s in record['shots'] if s['id']==key),None)
    if not shot:raise FileNotFoundError('Shot not found')
    return shot


def _invalidate(record):
    record.update(render=None,release=None,stage='storyboard')


def shot_digest(record,shot):
    return digest(dict(governance=record['governance']['sha256'],input=shot['input'],revision=shot['input_revision'],continuity=record['continuity_notes']))


def script_digest(record):return digest([dict(id=s['id'],sha256=shot_digest(record,s)) for s in record['shots']])


def script_approved(record):return (record.get('script_approval') or {}).get('sha256')==script_digest(record)


def freeze_governance(request):
    from brand.kits import get_brand
    from brand.guidelines import Rules,get as guideline
    from video.assets import existing,path_for
    from video.fonts import choose
    kit=get_brand(request.brand_id)
    if not kit:raise FileNotFoundError('Brand kit not found')
    document=guideline(request.guideline_id) if request.guideline_id else None
    if document and not document['confirmed']:raise ValueError('Review and confirm the extracted guideline rules before creating a production.')
    rules=Rules.model_validate(document['rules']) if document else Rules()
    primary=rules.primary_colors or [kit['primary_hex']]
    secondary=rules.secondary_colors or [kit['accent_hex']]
    preferences=rules.font_preferences or (kit.get('font_preferences_ar') if request.language=='ar' else kit.get('font_preferences')) or ['Cairo' if request.language=='ar' else 'Arial']
    font,warnings=choose(preferences)
    if not font:raise ValueError('No supported font is installed. Add a registered font before creating the production.')
    logo=rules.logo_asset_id or (existing(kit['logo_path'])['id'] if kit.get('logo_path') else None)
    rgb=bytes.fromhex(primary[0][1:]);contrast='#07111c' if sum(a*b for a,b in zip(rgb,(.299,.587,.114)))>160 else '#ffffff'
    rules=rules.model_copy(update=dict(brand_name=rules.brand_name or kit['brand_name'],primary_colors=primary,secondary_colors=secondary,caption_color=rules.caption_color or contrast,
        font_preferences=[font],logo_asset_id=logo,language=request.language))
    brand=dict(id=kit['id'],brand_name=rules.brand_name,brand_name_ar=kit.get('brand_name_ar',''),primary_hex=primary[0],secondary_hex=secondary[0],
        font_family=font,font_preferences=preferences,logo_asset_id=logo,tagline=kit.get('tagline',''))
    value=dict(version=1,brand=brand,rules=rules.model_dump(),guideline_id=request.guideline_id,
        guideline_version=document['version'] if document else None,guideline_sha256=digest(document['rules']) if document else None,
        logo_sha256=file_hash(path_for(logo)) if logo else None,warnings=warnings,
        identity_policy='Generated plates contain no corporate text or logos. Identity-critical artwork is composited from this frozen pack.')
    value['sha256']=digest(value)
    return value


def create(body):
    from video.production_text import plan_script
    governance=freeze_governance(body.brief)
    scenes,source,warnings=plan_script(body,governance)
    shots=[]
    for i,scene in enumerate(scenes):
        inputs=ShotInput.model_validate({k:v for k,v in scene.items() if k in ShotInput.model_fields}).model_dump()
        shots.append(dict(id=uid(),sequence=i+1,input_revision=1,input=inputs,candidates=[],approvals={}))
    record=dict(id=uid(),version=0,name=body.name,created=time.time(),updated=time.time(),stage='brief',request=body.brief.model_dump(),
        script_source=source,script_warnings=warnings,continuity_notes=body.continuity_notes,governance=governance,
        shots=shots,script_approval=None,render=None,release=None,timeline_project_id=None,busy_job=None,events=[])
    with LOCK:return _save(record,'created',dict(script_source=source,governance_sha256=governance['sha256']))


def update_shot(key,shot_id,body):
    from video.assets import path_for
    with LOCK:
        record=get(key);_editable(record,body.expected_version);shot=_shot(record,shot_id)
        for field in ('reference_asset_id','source_asset_id'):
            if getattr(body.shot,field):path_for(getattr(body.shot,field))
        shot.update(input=body.shot.model_dump(),input_revision=shot['input_revision']+1,approvals={})
        record['script_approval']=None;record['timeline_project_id']=None;_invalidate(record)
        return _save(record,'shot-edited',dict(shot_id=shot_id,input_revision=shot['input_revision']))


def approve_script(key,body):
    with LOCK:
        record=get(key);_editable(record,body.expected_version)
        total=sum(s['input']['duration'] for s in record['shots'])
        if not 6<=total<=60:raise ValueError('The reviewed script must total between 6 and 60 seconds.')
        record['script_approval']=dict(sha256=script_digest(record),reviewer=body.reviewer,note=body.note,at=time.time())
        record['stage']='generation'
        return _save(record,'script-approved',record['script_approval'])


def route_shot(record,shot):
    from video.assets import path_for
    inputs=shot['input'];method=inputs['method']
    source=read('assets',inputs['source_asset_id']) if inputs['source_asset_id'] else None
    reference=read('assets',inputs['reference_asset_id']) if inputs['reference_asset_id'] else None
    if method=='auto':
        method='real-footage' if source and source['kind']=='video' else 'image-animation' if reference or (source and source['kind']=='image') else 'motion-graphics'
    if inputs['accuracy_critical'] and method not in {'real-footage','image-animation'}:
        raise ValueError('Accuracy-critical content needs real footage or an approved still. Select one from the media library.')
    if method=='real-footage' and (not source or source['kind']!='video'):raise ValueError('Select real video footage for this shot.')
    if method in {'image-animation','image-to-video'}:
        selected=reference or source
        if not selected or selected['kind']!='image':raise ValueError('Select a still reference image for this shot.')
        if method=='image-to-video' and selected['id']==record['governance']['brand'].get('logo_asset_id'):
            raise ValueError('Use a clean reference plate for image-to-video; the company logo is composited separately.')
    if method in {'text-to-video','image-to-video'}:
        from video.engine import Generate,check_generate
        from video.models import MODELS
        if inputs['model'] not in MODELS:raise ValueError('Choose a supported local video model.')
        config=MODELS[inputs['model']]
        if inputs['duration']>config['frames']/config['fps']+.05:raise ValueError('This shot exceeds the model native clip length. Split it into shorter shots or use real footage.')
        selected=reference or source
        request=Generate(mode=method,model=inputs['model'],prompt=inputs['visual_prompt'],asset_id=selected['id'] if selected else None)
        check_generate(request)
    for asset in (source,reference):
        if asset:path_for(asset['id'])
    return method,source,reference


def candidate_prompt(record,shot):
    inputs=shot['input']
    details='; '.join(f'{field}: {inputs[field]}' for field in ('subject','framing','camera_angle','camera_motion','action','location','wardrobe','props','screen_direction','continuity_notes') if inputs.get(field))
    return (inputs['visual_prompt']+'\n'+details+'\nContinuity: '+record['continuity_notes']+
        '\nGenerate only a clean visual plate. No lettering, corporate text, subtitles, logos, watermarks or readable product labels. These will be composited separately.')[:2000]


def _queue(record,kind,worker,apply):
    from video.jobs import jobs
    snapshot=copy.deepcopy(record)
    def execute(job):
        try:
            result=worker(snapshot,job)
            with LOCK:
                if job.cancelled():
                    from video.ffmpeg import Cancelled
                    raise Cancelled()
                current=get(record['id'])
                if current.get('busy_job')!=job.id:raise ProductionConflict('Production job was superseded.')
                apply(current,result)
                _save(current,'job-result',dict(job_id=job.id))
            return dict(production_id=record['id'])
        finally:
            with LOCK:
                current=get(record['id'])
                if current.get('busy_job')==job.id:
                    current['busy_job']=None;_save(current,'job-finished',dict(job_id=job.id))
    job=jobs.submit(kind,execute)
    record['busy_job']=job['id'];_save(record,'job-queued',dict(job_id=job['id'],kind=kind))
    return job


def _candidate(record,shot,pass_name,job):
    from video.assets import path_for,annotate
    from video.ffmpeg import probe
    inputs=shot['input'];method,source,reference=route_shot(record,shot);prompt=candidate_prompt(record,shot)
    native_revision=None;native_profile=None
    if method in {'text-to-video','image-to-video'}:
        from video.engine import Generate,generate
        from video.models import CACHE
        selected=reference or source
        request=Generate(mode=method,model=inputs['model'],prompt=prompt,negative_prompt='letters, typography, logos, subtitles, watermark',
            asset_id=selected['id'] if selected else None,seed=inputs['seed'],quality='draft' if pass_name=='concept' else 'standard',
            duration=inputs['duration'],aspect=record['request']['platform_target'],resolution=record['request']['resolution'])
        result=generate(request,job)
        installation=json.loads((CACHE/inputs['model']/'installation.json').read_text(encoding='utf-8'))
        native_revision=dict(repo=installation['repo'],revision=installation['revision'],license=installation['license'])
        from video.models import MODELS
        native_profile={key:MODELS[inputs['model']][key] for key in ('width','height','frames','fps')}
    else:
        from video.editor import render
        from video.assets import ingest
        from video.projects import Canvas,Project,Clip
        from video.sequence import sequence_backdrop
        ratio=record['request']['platform_target'];short=360 if pass_name=='concept' else record['request']['resolution']
        a,b=map(int,ratio.split(':'));width=short if a<=b else round(short*a/b/2)*2;height=short if a>=b else round(short*b/a/2)*2
        canvas=Canvas(width=width,height=height,fps=30)
        selected=(reference or source) if method=='image-animation' else source if method=='real-footage' else None
        with tempfile.TemporaryDirectory(dir=DATA/'work',prefix='plate-') as folder:
            if not selected:
                plate=Path(folder)/'clean-plate.png';sequence_backdrop(plate,canvas,record['governance']['brand'],shot['sequence'],inputs['background_style'])
                selected=ingest(plate,plate.name,job)
            if selected['kind']=='video' and selected['duration']<inputs['duration']-.05:raise ValueError('This footage is too short. Shorten the scene or select a longer clip.')
            movement=dict(zoom=1.08 if inputs['motion']=='zoom-in' else 1,zoom_start=1.08 if inputs['motion']=='zoom-out' else 1,pan=.15 if inputs['motion']=='pan' else 0)
            following=record['shots'][shot['sequence']] if shot['sequence']<len(record['shots']) else None
            handle=min(following['input']['transition_seconds'],inputs['duration']/4,following['input']['duration']/4) if following and following['input']['transition']=='fade' else 0
            # Generate transition handles now. Slowing a 30 fps plate later triggers
            # expensive optical-flow interpolation despite already having smooth motion.
            clip=Clip(asset_id=selected['id'],duration=inputs['duration']+(handle+.1 if selected['kind']=='image' else 0),volume=0,fit='blur-fill',**(movement if selected['kind']=='image' else {}))
            result=render(Project(name='Clean plate',canvas=canvas,clips=[clip]),job,audio=False)
    meta=probe(path_for(result['id']))
    if meta['video_codec']!='h264' or meta['duration']<inputs['duration']-.12:raise ValueError('Generated clip does not meet its shot duration or codec requirements.')
    annotate(result,production_id=record['id'],shot_id=shot['id'],candidate_pass=pass_name)
    previous={'continuity':'concept','final':'continuity'}.get(pass_name)
    sources={asset['id']:file_hash(path_for(asset['id'])) for asset in (source,reference) if asset}
    return dict(id=uid(),shot_id=shot['id'],pass_name=pass_name,asset_id=result['id'],url=result['url'],
        parent_candidate_id=shot['approvals'][previous]['candidate_id'] if previous else None,source_hashes=sources,
        input_sha256=shot_digest(record,shot),governance_sha256=record['governance']['sha256'],script_sha256=script_digest(record),
        file_sha256=file_hash(path_for(result['id'])),method=method,prompt=prompt,seed=inputs['seed'],model=inputs['model'] if native_revision else None,
        model_revision=native_revision,native_generation=native_profile,created=time.time(),metadata={key:meta.get(key) for key in ('width','height','duration','fps','video_codec','has_audio')},
        reference_asset_id=inputs['reference_asset_id'],source_asset_id=inputs['source_asset_id'],
        notice='Local diffusion' if native_revision else 'Deterministic local composition; no diffusion inference')


def generate_candidate(key,shot_id,body):
    with LOCK:
        record=get(key);_editable(record,body.expected_version);shot=_shot(record,shot_id)
        if not script_approved(record):raise ValueError('Approve the current script before generating shots.')
        if len(shot['candidates'])>=36:raise ValueError('This shot has reached its take limit. Create a new production for more takes.')
        previous={'continuity':'concept','final':'continuity'}.get(body.pass_name)
        if previous and previous not in shot['approvals']:raise ValueError(f'Approve the {previous} pass before generating this pass.')
        method,_,_=route_shot(record,shot)
        kind=method if method in {'text-to-video','image-to-video'} else 'production-shot'
        return _queue(record,kind,lambda snapshot,job:_candidate(snapshot,_shot(snapshot,shot_id),body.pass_name,job),
            lambda current,result:_shot(current,shot_id)['candidates'].append(result))


def approve_candidate(key,shot_id,body):
    from video.assets import path_for
    with LOCK:
        record=get(key);_editable(record,body.expected_version);shot=_shot(record,shot_id)
        if not script_approved(record):raise ValueError('Approve the current script first.')
        candidate=next((c for c in shot['candidates'] if c['id']==body.candidate_id),None)
        if not candidate:raise FileNotFoundError('Candidate not found in this shot')
        if candidate['pass_name']!=body.gate or candidate['input_sha256']!=shot_digest(record,shot):raise ValueError('The take is stale or belongs to another review pass.')
        if file_hash(path_for(candidate['asset_id']))!=candidate['file_sha256']:raise ValueError('Candidate file changed. Generate a new take.')
        previous={'continuity':'concept','final':'continuity'}.get(body.gate)
        if previous and previous not in shot['approvals']:raise ValueError(f'Approve {previous} first.')
        if previous and candidate.get('parent_candidate_id')!=shot['approvals'][previous]['candidate_id']:
            raise ValueError('This take belongs to a previous approved parent. Generate a new take from the current review gate.')
        if body.approved:
            if not body.intent_checked:raise ValueError('Review the shot against its script intent before approving.')
            if body.gate in {'continuity','final'} and not body.continuity_checked:raise ValueError('Review appearance, location, props and screen direction before approving.')
            if body.gate=='final' and not body.readability_checked:raise ValueError('Confirm critical text will be composited separately.')
            shot['approvals'][body.gate]=dict(candidate_id=candidate['id'],input_sha256=candidate['input_sha256'],reviewer=body.reviewer,note=body.note,at=time.time())
        else:shot['approvals'].pop(body.gate,None)
        for later in {'concept':['continuity','final'],'continuity':['final'],'final':[]}[body.gate]:shot['approvals'].pop(later,None)
        _invalidate(record);record['timeline_project_id']=None
        if all('final' in s['approvals'] for s in record['shots']):record['stage']='editing'
        return _save(record,'shot-review',dict(shot_id=shot_id,gate=body.gate,approved=body.approved,reviewer=body.reviewer,note=body.note))


def reset_timeline(key,body):
    with LOCK:
        record=get(key);_editable(record,body.expected_version)
        record['timeline_project_id']=None;_invalidate(record)
        return _save(record,'timeline-reset',dict(note='Existing editor projects and revisions remain available.'))


def check(key):
    from video.production_render import project_model,compliance,timeline_hash
    record=get(key);project=project_model(read('projects',record['timeline_project_id'])) if record.get('timeline_project_id') else None
    report=compliance(record,project)
    report.update(script_approved=script_approved(record),final_shots_approved=sum('final' in s['approvals'] for s in record['shots']),shots=len(record['shots']))
    report['render_matches_timeline']=bool(record.get('render') and project and timeline_hash(project.model_dump())==record['render']['timeline_sha256'])
    return report


def render_master(key,body):
    from video.production_render import render_production,selected_candidates
    with LOCK:
        record=get(key);_editable(record,body.expected_version);selected_candidates(record)
        audio_keys=('narrator_voice','music_asset_id','voiceover_asset_id','burn_subtitles','music_volume')
        audio_options={name:getattr(body,name) for name in audio_keys}
        if record.get('timeline_project_id') and record.get('audio_options')!=audio_options:
            raise ValueError('Audio settings changed. Rebuild the timeline from approved shots, or adjust its audio in Video Editor.')
        def apply(current,result):
            current.update(render=result,release=None,timeline_project_id=result['project_id'],stage='review',audio_options=audio_options)
        return _queue(record,'production-master',lambda snapshot,job:render_production(snapshot,body,job),apply)


def release_readiness(record):
    from video.production_render import selected_candidates,timeline_hash,project_model,compliance
    from video.assets import path_for
    selected_candidates(record)
    output=record.get('render')
    if not output:raise ValueError('Render and review the current timeline before release.')
    project=read('projects',output['project_id'])
    if timeline_hash(project)!=output['timeline_sha256']:raise ValueError('The timeline changed after rendering. Render and review the current revision.')
    if not compliance(record,project_model(project))['passed']:raise ValueError('Resolve frozen brand compliance failures before release.')
    for result in [output,*output.get('variants',{}).values()]:
        if file_hash(path_for(result['asset_id']))!=result['file_sha256']:raise ValueError('A rendered file changed. Render a new master.')
        if (result.get('qa') or {}).get('overall') not in {'PASS','WARNING'}:raise ValueError('A render failed or lacks technical QA. Resolve the failure and render again.')
        checks={item['id']:item['status'] for item in result['qa'].get('checks',[])}
        if any(checks.get(name)!='PASS' for name in ('readable','duration','dimensions','frame_rate','video_codec')):
            raise ValueError('A render lacks passing core technical measurements. Render a new master before release.')
        if result.get('project_id') and timeline_hash(read('projects',result['project_id']))!=result['timeline_sha256']:
            raise ValueError('A platform timeline changed after rendering. Render it again before release.')
        if result.get('project_id') and not compliance(record,project_model(read('projects',result['project_id'])))['passed']:
            raise ValueError('A platform variant fails frozen brand compliance. Correct its timeline and render again.')
    return True


def release(key,body):
    from video.production_delivery import build_delivery
    with LOCK:
        record=get(key);_editable(record,body.expected_version);release_readiness(record)
        if not all(getattr(body,field) for field in ('story_checked','continuity_checked','text_checked','audio_checked','rights_checked')):
            raise ValueError('Complete all final human-review checks before release.')
        review=dict(reviewer=body.reviewer,note=body.note,at=time.time(),timeline_sha256=record['render']['timeline_sha256'],
            checks={field:getattr(body,field) for field in ('story_checked','continuity_checked','text_checked','audio_checked','rights_checked')})
        def worker(snapshot,job):
            import os
            snapshot['release_review']=review
            folder=DATA/'production-deliveries';folder.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=DATA/'work',prefix='producer-delivery-') as work:
                job.update(phase='Preparing reviewed client delivery',progress=None)
                path=Path(work)/'client-video-production.zip';manifest=build_delivery(snapshot,path)
                release_readiness(snapshot)
                destination=folder/(job.id+'.zip');os.replace(path,destination)
            return dict(delivery_id=job.id,sha256=file_hash(destination),manifest=manifest,review=review)
        def apply(current,result):
            release_readiness(current)
            current.update(release=result,release_review=review,stage='released')
        return _queue(record,'production-delivery',worker,apply)


def delivery_file(key,kind='zip'):
    from video.assets import path_for
    record=get(key)
    if not record.get('release'):raise ProductionConflict('The client delivery is locked until final release review passes.')
    release_readiness(record)
    if kind=='zip':
        path=DATA/'production-deliveries'/(record['release']['delivery_id']+'.zip')
        if not path.is_file() or file_hash(path)!=record['release']['sha256']:raise ValueError('The delivery archive changed or is missing. Release a new client kit.')
        return path
    if kind=='master':return path_for(record['render']['asset_id'])
    variant=record['render'].get('variants',{}).get(kind.replace('x',':'))
    if not variant:raise FileNotFoundError('Released variant not found')
    return path_for(variant['asset_id'])
