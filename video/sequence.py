"""Storyboard sequences: validate a reviewed storyboard, build its branded timeline (motion artwork,
headlines, logo, narration and subtitles), render it, check the result and package the client kit.

Delivery practice applied here (sources cited in the code comments):
- subtitles are short cues timed to the narrator's words, two lines at most and at a readable pace,
  never across a cut, placed above the platform's interface area (TikTok first for vertical video);
- the logo, brand name and headlines stay inside the same safe area, headlines clear of the subtitles;
- renders are mastered like every export (measured loudness to -14 LUFS under the true-peak ceiling,
  speech polish for narration, music set under the voice by measured loudness) and checked frame by frame;
- the client kit adds a cover image, WebVTT subtitles and short-form suggestions for the person to review.
"""
import json
import os
import tempfile
from pathlib import Path

from video.assets import annotate, ingest, path_for
from video.ffmpeg import Cancelled, probe
from video.motion import MOTIONS
from video.projects import Canvas, Clip, CreativeContext, Project
from video.storage import DATA, read


MIN_FOOTAGE_SPEED = .75   # slower than this, live footage reads as slow motion; ask for a longer clip instead


def frame_fit(meta, canvas):
    """'blur-fill' (whole picture on a blurred copy of itself) when filling the frame would crop away more
    than about a third of the picture or enlarge it more than 1.6x (soft, pixelated); otherwise 'cover'."""
    width, height = meta.get('width') or 0, meta.get('height') or 0
    if not width or not height:
        return 'cover'
    image, frame = width / height, canvas.width / canvas.height
    enlarge = max(canvas.width / width, canvas.height / height)
    return 'blur-fill' if min(image / frame, frame / image) < .64 or enlarge > 1.6 else 'cover'


def footage_timing(meta, needed):
    """Where a video clip starts and how fast it plays so it fills ``needed`` seconds: longer clips skip a
    little of their opening (often a fade); slightly short clips play in gentle slow motion."""
    available = float(meta.get('duration') or 0)
    if available >= needed:
        return round(min(1.0, (available - needed) / 2), 3), 1.0
    speed = available / needed
    if speed < MIN_FOOTAGE_SPEED:
        raise ValueError(f'the clip is {available:.1f} s long but the scene needs {needed:.1f} s; choose a longer clip or shorten the scene')
    return 0.0, round(speed - .005, 3)


def prepare_sequence(request):
    """Validate the reviewed storyboard and owned media before occupying a worker."""
    from video.director import generate_video_brief,StoryboardScene,VideoBriefRequest,compile_storyboard,validate_storyboard
    brief=read('briefs',request.brief_id) if request.brief_id else generate_video_brief(request.brief)
    context=brief.get('agency_context') or {}
    if context:
        from agency.api_production import validate_video_campaign_context
        validate_video_campaign_context(context['client_id'],context['campaign_id'])
    scenes=request.scenes or [StoryboardScene.model_validate(scene) for scene in brief['scenes']]
    validate_storyboard(scenes,brief['request']['duration'])
    for number,scene in enumerate(scenes,1):
        if not scene.asset_id:continue
        meta=read('assets',scene.asset_id)
        if meta['kind'] not in ('image','video'):
            raise ValueError('Storyboard visuals must be images or video clips')
        path_for(scene.asset_id)
        if meta['kind']=='video':
            try:footage_timing(meta,scene.duration+.35)   # room for a crossfade into the next scene
            except ValueError as error:raise ValueError(f'Scene {number}: {error}')
    for key in (request.music_asset_id,request.voiceover_asset_id):
        if key:
            if read('assets',key)['kind']!='audio':raise ValueError('Choose an audio asset for music or voiceover')
            path_for(key)
    if request.narrator_voice:
        if request.voiceover_asset_id:raise ValueError('Choose either a recorded voiceover or the AI narrator, not both')
        from video.voice import voice
        voice(request.narrator_voice,brief['request']['language'])
    if brief['brand'].get('logo_asset_id'):path_for(brief['brand']['logo_asset_id'])
    from video.storyboard_coach import review_storyboard
    scene_data=[scene.model_dump() for scene in scenes]
    assets={scene['asset_id']:read('assets',scene['asset_id']) for scene in scene_data if scene.get('asset_id')}
    return {**brief,'scenes':[scene.model_dump() for scene in scenes],
            'storyboard_review':review_storyboard(scene_data,brief['request'],assets),
            'timeline':compile_storyboard(VideoBriefRequest.model_validate(brief['request']),brief['brand'],scenes)}


def sequence_backdrop(path,canvas,brand,index,style='brand-gradient',line_y=.72):
    """Local vector-like motion artwork; supplied scene images can replace this backdrop.
    ``line_y`` places the accent rule (fraction of the height); None leaves it out."""
    from PIL import Image,ImageDraw
    primary=tuple(bytes.fromhex(brand['primary_hex'].lstrip('#')))
    accent=tuple(bytes.fromhex(brand['secondary_hex'].lstrip('#')))
    w,h=canvas.width,canvas.height
    image=Image.new('RGB',(w,h));draw=ImageDraw.Draw(image)
    for y in range(h):
        alpha=0 if style=='minimal' else .07+.18*y/h
        color=tuple(round((1-alpha)*a+alpha*b) for a,b in zip(primary,accent))
        draw.line((0,y,w,y),fill=color)
    for n in range(5 if style=='geometric' else 3 if style=='brand-gradient' else 0):
        x=int(w*(.12+((n+index)%5)*.19));y=int(h*(.22+(n%3)*.12));radius=int(min(w,h)*(.06+n*.018))
        if style=='brand-gradient':draw.arc((x-radius,y-radius,x+radius,y+radius),start=30,end=300,fill=accent,width=max(2,w//250))
        else:draw.rounded_rectangle((x-radius,y-radius,x+radius,y+radius),radius=radius//3,outline=accent,width=max(2,w//250))
    if line_y is not None:
        draw.line((int(w*.1),int(h*line_y),int(w*.9),int(h*line_y)),fill=accent,width=max(3,w//150))
    image.save(path)


# Subtitles follow timed-text practice (Netflix/BBC style guides): at most two lines, a readable pace
# (enforced by video.caption_timing) and about 42 characters per line in landscape, fewer on phones.
# Font sizes and line widths are fractions of the frame width.
CAPTION_LAYOUT = {'16:9': dict(font=.028, width=.62), '1:1': dict(font=.044, width=.80), '9:16': dict(font=.05, width=.76)}
# Vertical video is laid out for the most restrictive common interface (TikTok, then Reels and Shorts fit);
# square feed posts keep generic margins and landscape keeps room for the player controls.
PLATFORM_FOR_RATIO = {'9:16': 'tiktok', '1:1': 'generic-horizontal', '16:9': 'youtube-standard'}
LOGO_SCALE = .16


def platform_profile(ratio, language):
    from video import platforms
    name = PLATFORM_FOR_RATIO.get(ratio, 'generic-horizontal')
    if name == 'tiktok':
        name = 'tiktok-rtl' if language == 'ar' else 'tiktok-ltr'
    return platforms.profile(name)


def caption_words(scenes, narration=None):
    """Word timings for the subtitles: the narrator's own timings when the video is narrated, otherwise
    each scene's words spread across the scene (with a short margin at each cut)."""
    if narration and narration.get('words'):
        return [dict(word=w['word'], start=w['start'], end=w['end']) for w in narration['words']]
    words = []
    for scene in scenes:
        tokens = scene['voiceover'].split()
        begin, finish = scene['start'] + .15, scene['start'] + scene['duration'] - .15
        weights = [len(token) + 1 for token in tokens]
        cursor = begin
        for token, weight in zip(tokens, weights):
            span = (finish - begin) * weight / sum(weights)
            words.append(dict(word=token, start=round(cursor, 3), end=round(cursor + span, 3)))
            cursor += span
    return words


def caption_track(scenes, settings, brand, burn_in, narration, size, profile, text_color, report=None):
    """Short subtitle cues timed to the words, two lines at most, placed just above the platform's
    interface area and inside its side margins."""
    from video import platforms
    from video.caption_timing import optimize
    from video.captions import CaptionStyle
    from video.typography import compose
    w, h = size
    language = settings['language']
    layout = CAPTION_LAYOUT.get(settings['platform_target'], CAPTION_LAYOUT['16:9'])
    left, top, right, bottom = platforms.safe_area(profile, w, h)
    font = round(w * layout['font'])
    style = CaptionStyle(id='brief-subtitles', name='Branded storyboard captions', font_name=brand['font_family'],
                         font_family='arabic' if language == 'ar' else 'sans', font_size=max(18, min(96, font)),
                         font_size_px=max(12, min(160, font)), reference_width=w, fill=text_color, stroke=brand['primary_hex'],
                         stroke_width=2, background=brand['primary_hex'] + 'ee', y_pct=.8, max_lines=2, max_chars_per_line=42,
                         max_width_pct=round(max(.3, min(layout['width'], (right - left) / w - .06)), 4),
                         x_center_pct=round(min(.8, max(.2, (left + right) / 2 / w)), 4))
    measured = {}

    def fits(text):
        if text not in measured:
            info = compose(text, w, h, style)[0]
            measured[text] = not (info['exceeds_lines'] or info['oversized_word'] or info['font_reduced'])
        return measured[text]
    cues, timing = optimize(caption_words(scenes, narration), settings['duration'], language,
                            shot_boundaries=[scene['start'] for scene in scenes[1:]], fits=fits)
    # A cue may be shown slightly before its first word; it still never crosses a cut (timed-text practice
    # snaps subtitles to shot changes), so each cue is kept inside the scene its words belong to.
    for cue in cues:
        middle = (cue.get('spoken_start', cue['start']) + cue.get('spoken_end', cue['end'])) / 2
        scene = max((s for s in scenes if s['start'] <= middle + 1e-6), key=lambda s: s['start'], default=scenes[0])
        cue['start'] = round(max(cue['start'], scene['start']), 3)
        cue['end'] = round(min(cue['end'], scene['start'] + scene['duration']), 3)
    caption_top = None
    if cues:
        # Measured with the tallest cue so no subtitle reaches into the bottom interface area.
        boxes = [compose(cue['text'], w, h, style)[0]['box'] for cue in cues]
        tallest = max(box[3] - box[1] for box in boxes)
        style = style.model_copy(update={'y_pct': round(min(.92, max(.5, (bottom - tallest / 2 - 3) / h)), 4)})
        caption_top = style.y_pct * h - tallest / 2
    profile_cps = timing.get('profile', {}).get('max_cps', 20)
    if report is not None:
        report.update(cues=len(cues), timing='narrator word timings' if narration else 'scene text paced across each scene',
                      max_cps=profile_cps, unresolved=timing.get('unresolved', []), retimed=len(timing.get('changes', [])),
                      platform=dict(id=profile['id'], label=profile['label'], basis=profile['basis']))
    track = dict(id='storyboard-captions', kind='captions', language=language, source='manual', burn_in=burn_in,
                 brand_style=style.model_dump(), max_cps=profile_cps,
                 segments=[dict(start=cue['start'], end=cue['end'], text=cue['text']) for cue in cues])
    return track, caption_top if burn_in else None


def build_sequence_project(brief,request,job,work,narration=None,report=None):
    from video import platforms
    from video.captions import CaptionStyle
    from video.editor import validate_sources
    from video.director import VideoBriefRequest,StoryboardScene,compile_storyboard
    from video.typography import compose
    settings=brief['request'];brand=brief['brand'];ratio=settings['platform_target']
    compiled=compile_storyboard(VideoBriefRequest.model_validate(settings),brand,[StoryboardScene.model_validate(scene) for scene in brief['scenes']])
    canvas=Canvas(width=compiled['width'],height=compiled['height'],fps=compiled['fps'])
    w,h=canvas.width,canvas.height;scenes=brief['scenes'];clips=[]
    profile=platform_profile(ratio,settings['language'])
    left,top,right,bottom=platforms.safe_area(profile,w,h)
    rtl=profile['left']>profile['right']
    safe_center=round(min(.8,max(.2,(left+right)/2/w)),4)
    safe_width=round(max(.3,min(.8,(right-left)/w-.06)),4)
    rgb=tuple(bytes.fromhex(brand['primary_hex'].lstrip('#')))
    text_color='#07111c' if sum(a*b for a,b in zip(rgb,(.299,.587,.114)))>160 else '#ffffff'
    overlap=min(.35,min(scene['duration'] for scene in scenes)/4) if settings['transition']=='fade' else 0
    captions,caption_top=caption_track(scenes,settings,brand,request.burn_subtitles,narration,(w,h),profile,text_color,
                                       report.setdefault('captions',{}) if report is not None else None)
    def style_for(size,fill,role,y,center=safe_center,width=safe_width):
        return CaptionStyle(id=role,name=role,font_family='arabic' if settings['language']=='ar' else 'sans',
            font_name=brand['font_family'],font_size=size,font_size_px=size,reference_width=w,fill=fill,
            background=brand['primary_hex']+'ee',stroke=None,stroke_width=0,y_pct=y,
            max_chars_per_line=26 if ratio=='9:16' else 42,max_lines=3,padding=20,x_center_pct=center,max_width_pct=width)
    def graphic(text,start,duration,style,role,motion='none'):
        return Clip(kind='title',text=text,start=start,duration=duration,text_role=role,font_family=brand['font_family'],
                    scale=1,layout_box=[0,0,w,h],graphic_style={**style.model_dump(),'canvas_width':w,'canvas_height':h},
                    fade_in=.15,fade_out=.15,motion=motion)
    # Top bar: the logo in the upper corner and the brand name beside it, both inside the platform's safe area.
    logo_clip,logo_left,logo_right,logo_bottom=None,None,None,top
    if brand.get('logo_asset_id'):
        lw=max(2,round(w*LOGO_SCALE/2)*2)
        logo_meta=read('assets',brand['logo_asset_id'])
        lh=lw*logo_meta['height']/logo_meta['width'] if logo_meta.get('width') and logo_meta.get('height') else lw*.3
        target_x=left if rtl else right-lw
        logo_clip=Clip(kind='overlay',asset_id=brand['logo_asset_id'],duration=settings['duration'],scale=LOGO_SCALE,
                       x=round(min(1.,max(0.,target_x/max(1,w-lw))),4),y=round(min(1.,max(0.,(top+h*.01)/max(1,h-lh))),4),logo_backplate=True)
        logo_left,logo_right,logo_bottom=target_x,target_x+lw,top+h*.01+lh
    name=(brand.get('brand_name_ar') or brand['brand_name']) if settings['language']=='ar' else brand['brand_name']
    free=(left,logo_left-w*.03) if logo_left is not None and not rtl else (logo_right+w*.03,right) if logo_left is not None else (left,right)
    name_style=style_for(max(22,round(w*.035)),brand['secondary_hex'],'lower_third',.5,
                         center=round(min(.8,max(.2,(free[0]+free[1])/2/w)),4),width=round(max(.3,min(.95,(free[1]-free[0])/w)),4))
    name_box=compose(name,w,h,name_style)[0]['box']
    name_style=name_style.model_copy(update={'y_pct':round(max(.1,min(.4,(top+h*.01+(name_box[3]-name_box[1])/2)/h)),4)})
    bar_bottom=max(logo_bottom,name_style.y_pct*h+(name_box[3]-name_box[1])/2)
    # Headlines sit at 56% of the height unless that would reach the subtitles; never into the top bar.
    gap=h*.03
    headlines=[]
    for index,scene in enumerate(scenes):
        role='hook' if index==0 else 'cta' if index==len(scenes)-1 else 'headline'
        style=style_for(min(80,max(28,round(w*.055))),text_color,role,.56)
        box=compose(scene['overlay_text'],w,h,style)[0]['box'];half=(box[3]-box[1])/2
        centre=.56*h if caption_top is None else min(.56*h,caption_top-gap-half)
        centre=max(centre,bar_bottom+gap+half)
        headlines.append((role,style.model_copy(update={'y_pct':round(min(.92,max(.1,centre/h)),4)}),centre+half))
    for index,scene in enumerate(scenes):
        if job.cancelled():raise Cancelled()
        job.update(state='running',phase='Preparing storyboard visuals',progress={'completed_scenes':index,'total_scenes':len(scenes)})
        asset=scene.get('asset_id');meta=read('assets',asset) if asset else None
        length=scene['duration']+(overlap if index<len(scenes)-1 else 0)
        if meta and meta['kind']=='video':
            # Real footage carries its own motion: no added camera move, and its sound stays out of the mix.
            trim,speed=footage_timing(meta,length)
            clips.append(Clip(asset_id=asset,duration=length,transition=overlap if index else 0,trim=trim,speed=speed,
                              fit=frame_fit(meta,canvas),volume=0))
            continue
        if not asset:
            # The accent rule runs between the headline and the subtitles, or is left out when they are close.
            limit=caption_top if caption_top is not None else h*.9
            line=round((headlines[index][2]+limit)/2/h,4) if limit-headlines[index][2]>=gap else None
            path=work/f'scene-{index}.png';sequence_backdrop(path,canvas,brand,index,scene.get('background_style','brand-gradient'),line)
            asset=ingest(path,path.name,job)['id']
        move=MOTIONS[scene['motion']]
        zoom_delta={'calm':.025,'balanced':.06,'fast':.10}[settings['pacing']]
        move={**move,'zoom_start':1+zoom_delta if scene['motion']=='zoom-out' else 1,
              'zoom':1+zoom_delta if scene['motion']!='still' and scene['motion']!='zoom-out' else 1}
        clips.append(Clip(asset_id=asset,duration=length,transition=overlap if index else 0,zoom_ease=1,
                          fit=frame_fit(meta,canvas) if meta else 'cover',**move))
    clips.append(graphic(name,0,settings['duration'],name_style,'lower_third'))
    # Headlines enter with a short eased rise (motion intensity stays minimal; see video.motion).
    for scene,(role,style,_) in zip(scenes,headlines):
        clips.append(graphic(scene['overlay_text'],scene['start'],scene['duration'],style,role,motion='slide-up'))
    if logo_clip:clips.append(logo_clip)
    music_volume=request.music_volume if request.music_volume is not None else .18 if request.voiceover_asset_id else .55
    for asset_id,role,volume in [(request.music_asset_id,'music',music_volume),
                                 (request.voiceover_asset_id,'voiceover',request.voiceover_volume)]:
        if asset_id:
            meta=read('assets',asset_id)
            clips.append(Clip(kind='audio',asset_id=asset_id,audio_role=role,volume=volume,
                              duration=min(settings['duration'],meta['duration']),fade_in=.1,fade_out=.3))
    # Speech gets the gentle dialogue chain (high-pass, de-mud EQ, light compression): a narrator's peaks
    # otherwise stop the mix from reaching the -14 LUFS delivery target under the true-peak ceiling.
    project=Project(name=(brand['brand_name']+' — '+settings['campaign_type'])[:120],canvas=canvas,brand_id=brand['id'],
        clips=clips,normalize_audio=bool(request.voiceover_asset_id or request.music_asset_id),dialogue_polish=bool(request.voiceover_asset_id),
        delivery_preset={'9:16':'vertical-social','1:1':'square-social','16:9':'web-youtube'}[ratio],
        brand_rules=dict(brand_name=brand['brand_name'],primary_colors=[brand['primary_hex']],secondary_colors=[brand['secondary_hex']],font_preferences=[brand['font_family']]),
        creative_context=CreativeContext(key_message=settings['core_message'][:1000],objective=settings['campaign_type'],audience=settings.get('target_audience',''),
            language=settings['language'],platform=ratio,style=settings['tone']),
        caption_tracks=[captions])
    validate_sources(project)
    return project


MUSIC_BED_GAP = 18.0   # dB the music sits under the voice before ducking; mixing guides cite 18-24 dB under narration


def music_bed_level(request):
    """Music volume that places the music bed MUSIC_BED_GAP dB under the voice by measured loudness
    (ITU-R BS.1770), instead of one fixed volume for every track. Ducking still lowers it under speech."""
    import math
    from video.measure import loudness
    voice = loudness(path_for(request.voiceover_asset_id)).get('integrated_lufs')
    music = loudness(path_for(request.music_asset_id)).get('integrated_lufs')
    if voice is None or music is None:
        return None, None
    voice += 20 * math.log10(max(request.voiceover_volume, .001))
    gain = voice - MUSIC_BED_GAP - music
    volume = round(min(1.0, max(.02, 10 ** (gain / 20))), 3)
    return volume, dict(voice_lufs=round(voice, 1), music_lufs=round(music, 1), music_gain_db=round(gain, 1),
                        target_gap_db=MUSIC_BED_GAP, music_volume=volume, ducking='sidechain compression under speech')


def cover_frame(video, brief, captions, work):
    """A cover image from the opening scene once its headline has settled, preferring a moment with no
    subtitle on screen. Landscape covers use the 1280x720 thumbnail size."""
    import cv2
    from video.measure import frame_at
    first = brief['scenes'][0]
    begin, finish = first['start'] + .6, first['start'] + first['duration'] - .2
    quiet = [moment / 10 for moment in range(int(begin * 10), int(finish * 10) + 1)
             if not any(c['start'] - .05 <= moment / 10 <= c['end'] + .05 for c in captions)]
    moment = quiet[len(quiet) // 2] if quiet else first['start'] + min(first['duration'] * .6, 2.2)
    frame = frame_at(video, moment)
    if frame is None:
        return None
    if brief['request']['platform_target'] == '16:9':
        frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    path = work / 'cover.jpg'
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return path


def storyboard_advice(scenes, settings, captions=None):
    """Suggestions from published short-form video guidance. Advice only: the person decides."""
    advice = []
    hook = len(scenes[0]['overlay_text'].split())
    if hook > 8:
        advice.append(f'The opening headline has {hook} words. Hooks of about 3-8 words are easier to take in during the first few seconds.')
    if settings['platform_target'] in ('9:16', '1:1'):
        long = [str(i + 1) for i, scene in enumerate(scenes) if scene['duration'] > 7]
        if long:
            advice.append(f'Scene {", ".join(long)} keeps one picture for more than 7 seconds; short social videos usually change the picture every 2-7 seconds.')
        if settings['duration'] > 30:
            advice.append('Guides for short social video mostly recommend 15-30 seconds; consider a shorter cut for this format.')
    for i, scene in enumerate(scenes):
        words = len(scene['overlay_text'].split())
        if scene['duration'] < .5 + words / 4:
            advice.append(f'Scene {i + 1}: the headline ({words} words) is on screen for {scene["duration"]:g} s, which is short for reading it.')
    if scenes[-1]['duration'] < 2:
        advice.append('Give the closing call to action at least 2 seconds on screen.')
    if captions and captions.get('unresolved'):
        advice.append(f'{len(captions["unresolved"])} subtitle(s) are faster than the reading target of {captions["max_cps"]:g} characters per second; '
                      'shorten that narration or give its scene more time.')
    return advice


def sequence_qa(path,meta,brief,expect_audio,job=None,delivery=None):
    """Automated checks on the finished file. Hard faults already raised; these are reviewer warnings.
    With the delivery report from video.qa.master its measurements are reused and its findings listed."""
    from video.measure import black_and_frozen,loudness
    warnings=[];checks=dict(width=meta['width'],height=meta['height'],fps=meta['fps'],duration=meta['duration'],
        storyboard_duration=brief['request']['duration'],has_audio=meta['has_audio'])
    reported={check['id']:check for check in (delivery or {}).get('checks',[])}
    spans=reported['black_frames']['measured'] if isinstance(reported.get('black_frames',{}).get('measured'),list) else black_and_frozen(path,job)['black']
    black=[span for span in spans if span['duration']>=.5]
    checks['black_segments']=black
    if black:warnings.append('Black frames for '+', '.join(f'{s["duration"]:.1f} s at {s["start"]:.1f} s' for s in black[:3])+'; check the visuals for those moments.')
    if expect_audio:
        level=(delivery or {}).get('loudness') or loudness(path,job);checks['loudness']=level
        peak=level.get('true_peak_dbtp')
        if level.get('integrated_lufs') is None:warnings.append('The sound track is silent; check the voiceover and music.')
        elif peak is not None and peak>-.5:warnings.append(f'Audio peaks reach {peak:.1f} dBTP and may distort on some players.')
    else:warnings.append('No voiceover or music: the video is silent.')
    if delivery:
        for check in delivery.get('checks',[]):
            if check['id']=='frozen_frames':
                # Every storyboard scene is a still image with a slow camera move, which the frozen-picture
                # detector reads as motionless. Listed for review, not raised as a fault.
                checks['still_scene_intervals']=check.get('measured') or []
            elif check['status'] in ('WARNING','FAIL') and check['id']!='black_frames':
                warnings.append(f"{check['label']}: {check.get('detail') or check.get('expected') or check['status'].lower()}")
        checks['delivery']=dict(overall=delivery.get('overall'),counts=delivery.get('counts'),preset=delivery.get('preset'))
    return dict(passed=not warnings,warnings=warnings,checks=checks,
        notice='Automated checks catch technical faults only; watch the full video before sending it to a client.')


def render_sequence(brief,request,job):
    import zipfile
    from video.qa import master
    from video.projects import save
    from video.captions import CaptionSegment,to_srt,to_vtt
    from video.storage import atomic
    folder=DATA/'sequences';folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA/'work',prefix=job.id+'-sequence-') as directory:
        work=Path(directory)
        narration=None
        if request.narrator_voice and not request.voiceover_asset_id:
            from video.voice import narrate
            track,narration=narrate(brief['scenes'],brief['request']['language'],request.narrator_voice,brief['request']['duration'],work,job)
            narration['asset_id']=ingest(track,'ai-narration.wav',job)['id']
            request=request.model_copy(update={'voiceover_asset_id':narration['asset_id']})
        mix=None
        if request.music_asset_id and request.voiceover_asset_id and request.music_volume is None:
            volume,mix=music_bed_level(request)
            if volume is not None:request=request.model_copy(update={'music_volume':volume})
        report={}
        project=build_sequence_project(brief,request,job,work,narration,report)
        expect_audio=bool(request.music_asset_id or request.voiceover_asset_id)
        # Mastered like every other export: measured loudness correction plus the delivery checks.
        result=master(project,job,audio=expect_audio,captions_requested=bool(request.burn_subtitles and project.caption_tracks[0]['segments']))
        meta=probe(path_for(result['id']))
        if (meta['width'],meta['height'])!=(project.canvas.width,project.canvas.height) or abs(meta['fps']-30)>.01 or abs(meta['duration']-brief['request']['duration'])>.12:
            raise ValueError('Rendered sequence does not match the reviewed storyboard')
        if expect_audio and not meta['has_audio']:
            raise ValueError('Rendered sequence is missing its sound track')
        job.update(phase='Checking the finished video',progress={'percent':92})
        qa=sequence_qa(path_for(result['id']),meta,brief,expect_audio,job,delivery=result.get('qa_report'))
        if job.cancelled():raise Cancelled()
        segments=project.caption_tracks[0]['segments']
        cover_path=cover_frame(path_for(result['id']),brief,segments,work)
        cover=ingest(cover_path,'cover.jpg',job) if cover_path else None
        advice=storyboard_advice(brief['scenes'],brief['request'],report.get('captions'))
        project_id=save(project,actor='rule_engine',instruction='Rendered reviewed video storyboard')['id']
        job.update(phase='Packaging video delivery',progress={'percent':95})
        archive=work/'video-client-kit.zip'
        cues=[CaptionSegment(**cue) for cue in segments]
        credits=(brief.get('research') or {}).get('credits') or []
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(path_for(result['id']),'video/campaign.mp4')
            if cover:bundle.write(path_for(cover['id']),'cover.jpg')
            bundle.writestr('copy/script.txt','\n\n'.join(s['voiceover'] for s in brief['scenes']))
            bundle.writestr('copy/subtitles.srt',to_srt(cues))
            bundle.writestr('copy/subtitles.vtt',to_vtt(cues))
            bundle.writestr('storyboard.json',json.dumps(brief,ensure_ascii=False,indent=2))
            bundle.writestr('storyboard-review.json',json.dumps(brief.get('storyboard_review',{}),ensure_ascii=False,indent=2))
            bundle.writestr('project.json',project.model_dump_json(indent=2))
            if brief.get('research'):
                # Claim substantiation for the client: every researched source and the facts drawn from it.
                bundle.writestr('research/sources.json',json.dumps(brief['research'],ensure_ascii=False,indent=2))
            if credits:
                # Stock libraries ask for the creator and library to be credited; website media needs the client's confirmation.
                bundle.writestr('credits.txt','Footage and photo credits\n\n'+'\n'.join(credit['text'] for credit in credits)+'\n')
            if narration:
                bundle.write(path_for(narration['asset_id']),'audio/narration.wav')
            bundle.writestr('quality-check.json',json.dumps(dict(qa,narration=narration,captions=report.get('captions'),music_mix=mix,
                                                                 advice=advice,delivery=result.get('qa_report')),ensure_ascii=False,indent=2))
        if job.cancelled():raise Cancelled()
        destination=folder/(job.id+'.zip');os.replace(archive,destination)
        manifest=dict(sequence_id=job.id,brief_id=brief['brief_id'],asset_id=result['id'],project_id=project_id,
            video_url=result['url'],mp4_url='/api/video/download/'+result['id'],bundle_zip_url='/api/video/sequences/'+job.id+'/bundle',
            cover_url=cover and cover['url'],cover_download_url=cover and '/api/video/download/'+cover['id'],
            width=meta['width'],height=meta['height'],fps=meta['fps'],duration=meta['duration'],
            burn_subtitles=request.burn_subtitles,planning_source=brief['planning_source'],rendering_source='local-motion-graphics',
            has_voiceover=bool(request.voiceover_asset_id),has_music=bool(request.music_asset_id),agency_context=brief.get('agency_context',{}),
            narration=narration and {k:narration[k] for k in ('voice','engine','licence','scenes','word_timing')},quality=qa,
            captions=report.get('captions'),music_mix=mix,advice=advice,credits=[credit['text'] for credit in credits])
        manifest['storyboard_review']=brief.get('storyboard_review',{})
        atomic(folder/(job.id+'.json'),manifest)
        annotate(result,project_id=project_id,sequence_id=job.id,generation_type='storyboard-sequence')
        return manifest
