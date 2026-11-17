"""Orchestration for CPU animation, audio extraction and isolated local diffusion."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal
from pydantic import Field, PrivateAttr
from video_projects import Strict, Project, Clip, Canvas, CreativeContext
from video_storage import DATA, ROOT, read, space
from video_assets import path_for, ingest, annotate
from video_ffmpeg import ffmpeg, probe, Cancelled, stop_process
from video_qa import master
from video_models import CACHE, PYTHON, MODELS, statuses
from gpu_resources import gpu_slot


def prepare_sequence(request):
    """Validate the reviewed storyboard and owned media before occupying a worker."""
    from video_director import generate_video_brief,StoryboardScene,validate_storyboard
    brief=read('briefs',request.brief_id) if request.brief_id else generate_video_brief(request.brief)
    scenes=request.scenes or [StoryboardScene.model_validate(scene) for scene in brief['scenes']]
    validate_storyboard(scenes,brief['request']['duration'])
    for scene in scenes:
        if scene.asset_id and read('assets',scene.asset_id)['kind']!='image':
            raise ValueError('Storyboard visuals must be still images')
        if scene.asset_id:path_for(scene.asset_id)
    for key in (request.music_asset_id,request.voiceover_asset_id):
        if key:
            if read('assets',key)['kind']!='audio':raise ValueError('Choose an audio asset for music or voiceover')
            path_for(key)
    if brief['brand'].get('logo_asset_id'):path_for(brief['brand']['logo_asset_id'])
    return {**brief,'scenes':[scene.model_dump() for scene in scenes]}


def sequence_backdrop(path,canvas,brand,index):
    """Local vector-like motion artwork; supplied scene images can replace this backdrop."""
    from PIL import Image,ImageDraw
    primary=tuple(bytes.fromhex(brand['primary_hex'].lstrip('#')))
    accent=tuple(bytes.fromhex(brand['secondary_hex'].lstrip('#')))
    w,h=canvas.width,canvas.height
    image=Image.new('RGB',(w,h));draw=ImageDraw.Draw(image)
    for y in range(h):
        alpha=.07+.18*y/h
        color=tuple(round((1-alpha)*a+alpha*b) for a,b in zip(primary,accent))
        draw.line((0,y,w,y),fill=color)
    for n in range(5):
        x=int(w*(.12+((n+index)%5)*.19));y=int(h*(.22+(n%3)*.12));radius=int(min(w,h)*(.06+n*.018))
        draw.rounded_rectangle((x-radius,y-radius,x+radius,y+radius),radius=radius//3,outline=accent,width=max(2,w//250))
    draw.line((int(w*.1),int(h*.72),int(w*.9),int(h*.72)),fill=accent,width=max(3,w//150))
    image.save(path)


def build_sequence_project(brief,request,job,work):
    from video_captions import CaptionStyle
    from video_editor import validate_sources
    settings=brief['request'];brand=brief['brand'];ratio=settings['platform_target'];edge=settings['resolution']
    dimensions={'9:16':(edge,round(edge*16/9/2)*2),'1:1':(edge,edge),'16:9':(round(edge*16/9/2)*2,edge)}
    canvas=Canvas(width=dimensions[ratio][0],height=dimensions[ratio][1],fps=30)
    w,h=canvas.width,canvas.height;scenes=brief['scenes'];clips=[]
    rgb=tuple(bytes.fromhex(brand['primary_hex'].lstrip('#')))
    text_color='#07111c' if sum(a*b for a,b in zip(rgb,(.299,.587,.114)))>160 else '#ffffff'
    overlap=min(.35,min(scene['duration'] for scene in scenes)/4) if settings['transition']=='fade' else 0
    for index,scene in enumerate(scenes):
        if job.cancelled():raise Cancelled()
        job.update(state='running',phase='Preparing storyboard visuals',progress={'completed_scenes':index,'total_scenes':len(scenes)})
        asset=scene.get('asset_id')
        if not asset:
            path=work/f'scene-{index}.png';sequence_backdrop(path,canvas,brand,index)
            asset=ingest(path,path.name,job)['id']
        move=MOTIONS[scene['motion']]
        zoom_delta={'calm':.025,'balanced':.06,'fast':.10}[settings['pacing']]
        move={**move,'zoom_start':1+zoom_delta if scene['motion']=='zoom-out' else 1,
              'zoom':1+zoom_delta if scene['motion']!='still' and scene['motion']!='zoom-out' else 1}
        clips.append(Clip(asset_id=asset,duration=scene['duration']+(overlap if index<len(scenes)-1 else 0),
                          transition=overlap if index else 0,zoom_ease=1,**move))
    def graphic(text,start,duration,y,size,fill,role):
        style=CaptionStyle(id=role,name=role,font_family='arabic' if settings['language']=='ar' else 'sans',
            font_name=brand['font_family'],font_size=size,font_size_px=size,reference_width=w,fill=fill,
            background=brand['primary_hex']+'ee',stroke=None,stroke_width=0,y_pct=y,
            max_chars_per_line=26 if ratio=='9:16' else 42,max_lines=3,padding=20)
        return Clip(kind='title',text=text,start=start,duration=duration,text_role=role,font_family=brand['font_family'],
                    scale=1,layout_box=[0,0,w,h],graphic_style={**style.model_dump(),'canvas_width':w,'canvas_height':h},
                    fade_in=.15,fade_out=.15)
    name=(brand.get('brand_name_ar') or brand['brand_name']) if settings['language']=='ar' else brand['brand_name']
    clips.append(graphic(name,0,settings['duration'],.16, max(22,round(w*.035)),brand['secondary_hex'],'lower_third'))
    for index,scene in enumerate(scenes):
        clips.append(graphic(scene['overlay_text'],scene['start'],scene['duration'],.56,
                            min(80,max(28,round(w*.055))),text_color,'cta' if index==len(scenes)-1 else 'headline'))
    if brand.get('logo_asset_id'):
        clips.append(Clip(kind='overlay',asset_id=brand['logo_asset_id'],duration=settings['duration'],scale=.16,x=.86,y=.05,logo_backplate=True))
    for asset_id,role,volume in [(request.music_asset_id,'music',.18 if request.voiceover_asset_id else .55),
                                 (request.voiceover_asset_id,'voiceover',1)]:
        if asset_id:
            meta=read('assets',asset_id)
            clips.append(Clip(kind='audio',asset_id=asset_id,audio_role=role,volume=volume,
                              duration=min(settings['duration'],meta['duration']),fade_in=.1,fade_out=.3))
    caption_style=CaptionStyle(id='brief-subtitles',name='Branded storyboard captions',font_name=brand['font_family'],
        font_family='arabic' if settings['language']=='ar' else 'sans',font_size=32,fill=text_color,
        stroke=brand['primary_hex'],background=brand['primary_hex']+'ee',y_pct=.79,max_lines=3,max_chars_per_line=36)
    project=Project(name=(brand['brand_name']+' — '+settings['campaign_type'])[:120],canvas=canvas,brand_id=brand['id'],
        clips=clips,normalize_audio=bool(request.voiceover_asset_id or request.music_asset_id),
        delivery_preset={'9:16':'vertical-social','1:1':'square-social','16:9':'web-youtube'}[ratio],
        brand_rules=dict(brand_name=brand['brand_name'],primary_colors=[brand['primary_hex']],secondary_colors=[brand['secondary_hex']],font_preferences=[brand['font_family']]),
        creative_context=CreativeContext(key_message=settings['core_message'][:1000],objective=settings['campaign_type'],
            language=settings['language'],platform=ratio,style=settings['tone']),
        caption_tracks=[dict(id='storyboard-captions',language=settings['language'],source='manual',burn_in=request.burn_subtitles,
            brand_style=caption_style.model_dump(),segments=[dict(start=s['start'],end=round(s['start']+s['duration'],3),text=s['voiceover']) for s in scenes])])
    validate_sources(project)
    return project


def render_sequence(brief,request,job):
    import zipfile
    from video_editor import render
    from video_projects import save
    from video_captions import CaptionSegment,to_srt
    from video_storage import atomic
    folder=DATA/'sequences';folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA/'work',prefix=job.id+'-sequence-') as directory:
        work=Path(directory)
        project=build_sequence_project(brief,request,job,work)
        result=render(project,job,audio=bool(request.music_asset_id or request.voiceover_asset_id))
        meta=probe(path_for(result['id']))
        if (meta['width'],meta['height'])!=(project.canvas.width,project.canvas.height) or abs(meta['fps']-30)>.01 or abs(meta['duration']-brief['request']['duration'])>.12:
            raise ValueError('Rendered sequence does not match the reviewed storyboard')
        if job.cancelled():raise Cancelled()
        project_id=save(project,actor='rule_engine',instruction='Rendered reviewed video storyboard')['id']
        job.update(phase='Packaging video delivery',progress={'percent':95})
        archive=work/'video-client-kit.zip'
        subtitles=to_srt([CaptionSegment(**cue) for cue in project.caption_tracks[0]['segments']])
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(path_for(result['id']),'video/campaign.mp4')
            bundle.writestr('copy/script.txt','\n\n'.join(s['voiceover'] for s in brief['scenes']))
            bundle.writestr('copy/subtitles.srt',subtitles)
            bundle.writestr('storyboard.json',json.dumps(brief,ensure_ascii=False,indent=2))
            bundle.writestr('project.json',project.model_dump_json(indent=2))
        if job.cancelled():raise Cancelled()
        destination=folder/(job.id+'.zip');os.replace(archive,destination)
        manifest=dict(sequence_id=job.id,brief_id=brief['brief_id'],asset_id=result['id'],project_id=project_id,
            video_url=result['url'],mp4_url='/api/video/download/'+result['id'],bundle_zip_url='/api/video/sequences/'+job.id+'/bundle',
            width=meta['width'],height=meta['height'],fps=meta['fps'],duration=meta['duration'],
            burn_subtitles=request.burn_subtitles,planning_source=brief['planning_source'],rendering_source='local-motion-graphics',
            has_voiceover=bool(request.voiceover_asset_id),has_music=bool(request.music_asset_id))
        atomic(folder/(job.id+'.json'),manifest)
        annotate(result,project_id=project_id,sequence_id=job.id,generation_type='storyboard-sequence')
        return manifest


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
    duration: float = Field(4, ge=1, le=60)
    aspect: Literal['16:9', '9:16', '1:1', '4:5'] = '16:9'
    resolution: Literal[720, 1080] = 720
    motion: Literal['zoom-in', 'zoom-out', 'pan', 'still', 'auto'] = 'zoom-in'
    # Brand promo from stills: further scenes, a logo and the user's own licensed music.
    asset_ids: list[Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]] = Field(default_factory=list, max_length=7)
    logo_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    music_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
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
    logo = getattr(request, 'logo_asset_id', None)
    if logo and not rules.logo_asset_id:
        rules = rules.model_copy(update={'logo_asset_id': logo})      # a chosen logo is used when the guideline has none
    plan = polish(project, 'Apply reviewed brand guidelines with subtle professional styling.', rules) if request._rules or request.cta or logo else None
    if plan: project = checked(project, plan)
    saved = save(project, actor='rule_engine', instruction=request.prompt or request.objective,
                 label='Generated clip with reviewed brand guidelines' if request.guideline_id else 'Generated clip')
    findings = compliance(project)
    warnings = plan.warnings + plan.unfulfilled_requests if plan else []
    # The editor's note about free-form instructions does not apply to a generated clip.
    warnings = [w for w in warnings if not w.startswith('Rule-based Auto Polish applies')]
    warnings += [f['message'] for f in findings['findings'] if f['state'] in {'FAIL','WARNING'}]
    return project, saved['id'], warnings


MOTIONS = {'zoom-in': dict(zoom_start=1, zoom=1.14), 'zoom-out': dict(zoom_start=1.14, zoom=1), 'pan': dict(zoom_start=1.08, zoom=1.08, pan=.8),
           'pan-back': dict(zoom_start=1.08, zoom=1.08, pan=-.8), 'still': dict(zoom_start=1, zoom=1)}
SCENE_CROSSFADE = .4


def promo_timeline(request, canvas):
    """One still per scene with varied, eased camera moves and short crossfades.
    A single image with a chosen motion keeps the original one-shot behaviour."""
    scenes = list(dict.fromkeys([request.asset_id, *request.asset_ids]))
    count = len(scenes)
    overlap = SCENE_CROSSFADE if count > 1 else 0
    each = (request.duration + overlap * (count - 1)) / count
    cycle = ['zoom-in', 'pan', 'zoom-out', 'pan-back']
    clips = []
    for index, asset_id in enumerate(scenes):
        move = cycle[index % len(cycle)] if request.motion == 'auto' or count > 1 else request.motion
        if count == 1 and request.motion in ('zoom-in', 'zoom-out'):
            settings = dict(zoom_start=1.18 if request.motion == 'zoom-out' else 1, zoom=1.18 if request.motion == 'zoom-in' else 1)
        else:
            settings = MOTIONS[move]
        clips.append(Clip(asset_id=asset_id, duration=round(each, 4), transition=overlap if index else 0, fit=still_fit(asset_id, canvas),
                          fade_in=.4 if index == 0 else 0, fade_out=.4 if index == count - 1 else 0, **settings))
    if request.music_asset_id:
        music = read('assets', request.music_asset_id)
        clips.append(Clip(kind='audio', asset_id=request.music_asset_id, duration=round(min(request.duration, music['duration']), 4),
                          audio_role='music', fade_in=.3, fade_out=min(1.2, request.duration / 4)))
    project = Project(name='Brand promo' if count > 1 else 'Image Animation', canvas=canvas, clips=clips)
    project.normalize_audio = bool(request.music_asset_id)
    if request.logo_asset_id:
        project.editing_brief.logo_asset_id = request.logo_asset_id
    return project


def still_fit(asset_id, canvas):
    """'blur-fill' when cropping to the canvas would discard more than about a third of the still."""
    meta = read('assets', asset_id)
    if not meta.get('width') or not meta.get('height'):
        return 'cover'
    image, frame = meta['width'] / meta['height'], canvas.width / canvas.height
    return 'blur-fill' if min(image / frame, frame / image) < .64 else 'cover'


def scene_preview(asset_id, canvas, fit):
    """The still as it sits on the canvas (BGR), so measurements are in canvas coordinates."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps, ImageFilter
    with Image.open(path_for(asset_id)) as source:
        source = ImageOps.exif_transpose(source).convert('RGB')
        size = (canvas.width, canvas.height)
        frame = ImageOps.fit(source, size)
        if fit == 'blur-fill':
            frame = frame.filter(ImageFilter.GaussianBlur(max(8, canvas.width / 60)))
            whole = ImageOps.contain(source, size)
            frame.paste(whole, ((size[0] - whole.width) // 2, (size[1] - whole.height) // 2))
    return cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)


def still_face(image):
    """Largest frontal face in a BGR frame as frame fractions, or None. Used only to keep text off it."""
    try:
        import cv2
    except ImportError:
        return None
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ratio = min(1, 640 / max(gray.shape))
    small = cv2.resize(gray, None, fx=ratio, fy=ratio)
    found = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml').detectMultiScale(small, 1.1, 6, minSize=(40, 40))
    if not len(found):
        return None
    x, y, w, h = max(found, key=lambda box: box[2] * box[3])
    height, width = small.shape
    return dict(x=x / width, y=y / height, width=w / width, height=h / height)


def compose_promo(project, request):
    """Headline, call to action and logo as one designed composition: timed to the story
    (headline first, call to action as the close) and placed by the shared layout solver on
    plates with a type hierarchy, away from a detected face and the platform's interface."""
    import cv2
    import video_platforms
    from video_brand_editing import effective_rules
    from video_editor import primary_layout
    from video_layout import solve, analyze_frame
    layout, total = primary_layout(project)
    if abs(total - request.duration) > .02:
        # Brand transition rules may have changed the crossfades: keep the length that was asked for.
        scenes_ = [c for c in project.clips if c.kind == 'video']
        for clip in scenes_:
            clip.duration = round(max(.5, clip.duration + (request.duration - total) / len(scenes_)), 4)
        layout, total = primary_layout(project)
        for clip in project.clips:
            if clip.kind == 'audio':
                clip.duration = round(min(clip.duration, total), 4)
    width, height = project.canvas.width, project.canvas.height
    language = 'ar' if request.language.startswith('ar') else 'en'
    titles = [c for c in project.clips if c.kind == 'title']
    cta = next((c for c in titles if c.text_role == 'cta'), None)
    close = min(total, 3., max(1.5, total * .4))
    if cta:
        cta.start, cta.duration = round(max(0, total - close), 3), round(close, 3)
        cta.motion, cta.fade_in, cta.fade_out = 'slide-up', .25, min(.3, close / 4)
    message = (request.key_message or '').strip()
    if message and not any(c.text_role == 'hook' for c in titles):
        opening_start = min(.4, total * .06)
        opening = min(3.5, total - (close if cta else 0) - opening_start - .1)
        if opening >= 1.2:
            project.clips.append(Clip(kind='title', text=message, text_role='hook', start=round(opening_start, 3), duration=round(opening, 3),
                                      motion='slide-up', fade_in=.25, fade_out=.25))
    for clip in project.clips:
        if clip.kind == 'overlay':
            clip.logo_backplate = True
            clip.scale = max(clip.scale, .22)          # readable on a phone; the solver caps it at 23% of the width
            clip.start, clip.duration = 0, round(total, 3)
    scenes = [c for c, _, _ in layout]
    previews = [scene_preview(c.asset_id, project.canvas, c.fit) for c in scenes]
    faces = [still_face(frame) for frame in previews]
    first = previews[0]
    extra = []
    for face in faces[1:]:
        if face:            # text shown over later scenes stays clear of their faces too
            extra.append(dict(kind='face', box=[face['x'], face['y'], face['x'] + face['width'], face['y'] + face['height']], basis='MEASURED_STILL_FACE'))
    scene = analyze_frame(first, faces[0], None, extra)
    platform_id = video_platforms.choose(request.platform, width, height, language)
    platform = video_platforms.profile(platform_id)
    rules = effective_rules(project)
    report = solve(project, platform, faces[0], scene, rules)
    return project, dict(scenes=len(scenes), duration=round(total, 3), platform=dict(id=platform['id'], label=platform['label'], basis=platform['basis']),
                         elements=[dict(role=e['role'], start=e['start'], end=e['end'], box=e['box'], font_size_px=e['font_size_px'], requires_review=e['requires_review'],
                                        evidence=e['evidence']) for e in report['elements']],
                         faces_measured=sum(1 for f in faces if f), music=bool(request.music_asset_id),
                         notice='Text is placed on measured boxes away from detected faces and the platform interface. Faces are detected with a frontal-face detector; check each scene.')


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
        if len(request.key_message.strip()) > 120:
            raise ValueError('Keep the opening key message within 120 characters; it must fit on screen without cutting your copy')
        cta = (request._rules or {}).get('cta') or request.cta.strip()
        if request.key_message.strip() and request.duration < (3 if cta else 1.8):
            raise ValueError('Lengthen the video to at least ' + ('3' if cta else '1.8') + ' seconds so the key message can be read' + (' before the call to action' if cta else ''))
        for key in request.asset_ids:
            if read('assets', key)['kind'] != 'image':
                raise ValueError('Every additional scene must be a still image from the media library')
        if request.logo_asset_id and read('assets', request.logo_asset_id)['kind'] != 'image':
            raise ValueError('The logo must be an image')
        if request.music_asset_id:
            music = read('assets', request.music_asset_id)
            if music.get('kind') != 'audio' or not music.get('has_audio'):
                raise ValueError('The music track must be an uploaded audio file you are licensed to use')
            if (music.get('duration') or 0) < request.duration - .05:
                raise ValueError('Choose a music track at least as long as the video, or shorten the video to avoid an abrupt silent ending')
        scenes = len(dict.fromkeys([request.asset_id, *request.asset_ids]))
        if scenes > 1 and request.duration < scenes * 1.5:
            raise ValueError(f'{scenes} scenes need at least {scenes * 1.5:.0f} seconds; lengthen the video or remove a scene')
        return
    if request.asset_ids or request.music_asset_id:
        raise ValueError('Additional scenes and music are available for Image Animation only')
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
        project = promo_timeline(request, canvas)
        project, project_id, warnings = branded_project(project, request)
        project, composition = compose_promo(project, request)
        from video_projects import save
        save(project, project_id, actor='rule_engine', instruction=request.prompt or request.objective, label='Generated promo composition')
        result = master(project, job, audio=bool(request.music_asset_id))   # mastered and measured like every other export
        names = {'HOOK': 'headline', 'CTA': 'call to action', 'LOGO': 'logo'}
        for element in composition['elements']:
            if element['requires_review']:
                over = 'a detected face' if element['evidence'].get('face_overlap', 0) > .01 else 'another graphic or the platform interface area'
                warnings.append(f"Check the {names.get(element['role'], element['role'].lower())}: no free position was found, so it overlaps {over}.")
        return annotate(result, generation_type='deterministic-image-animation', name='Image Animation.mp4',
                        project_id=project_id, guideline_id=request.guideline_id, guideline_version=request._version,
                        brand_warnings=warnings, creation_prompt=generation_prompt(request), composition=composition)
    job.update(state='preparing', phase='Waiting for the local GPU', progress=None)
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
        payload['low_memory'] = request.model == 'cogvideox-2b' and hw.get('ram_gb', 32) < 24
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
                            job.update(state='running', phase=progress.get('phase') or 'Denoising', progress=progress)
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
        result = master(project, job, audio=False)   # every AI output receives the same delivery measurements
        manifest=json.loads((CACHE/request.model/'installation.json').read_text(encoding='utf-8'))
        return annotate(result, generation_type=request.mode, native_width=config['width'], native_height=config['height'],
                        inference_profile='staged-int8-text-fp16-video' if payload['low_memory'] else 'fp16-video' if request.model=='cogvideox-2b' else 'bf16-video',
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
