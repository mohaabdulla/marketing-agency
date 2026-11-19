"""Finish reviewed producer takes with the existing exact-brand compositor and measured mastering."""
from pathlib import Path
from video.production import digest,file_hash,shot_digest,script_approved
from video.storage import read


def project_model(raw):
    from video.projects import Project
    return Project.model_validate({k:v for k,v in raw.items() if k in Project.model_fields})


def timeline_hash(raw):return digest(project_model(raw).model_dump())


def selected_candidates(record):
    from video.assets import path_for
    if not script_approved(record):raise ValueError('The current script is not approved.')
    selected=[]
    for shot in record['shots']:
        parent=None
        for stage in ('concept','continuity','final'):
            approval=shot['approvals'].get(stage)
            if not approval or approval['input_sha256']!=shot_digest(record,shot):raise ValueError('Every current shot needs final approval before finishing.')
            candidate=next((c for c in shot['candidates'] if c['id']==approval['candidate_id']),None)
            if not candidate or candidate['pass_name']!=stage or file_hash(path_for(candidate['asset_id']))!=candidate['file_sha256']:raise ValueError('An approved take changed or is missing.')
            if candidate.get('parent_candidate_id')!=parent:raise ValueError('An approved take belongs to an older parent review. Generate and review the current chain.')
            parent=candidate['id']
            for asset_id,expected in candidate.get('source_hashes',{}).items():
                if file_hash(path_for(asset_id))!=expected:raise ValueError('An approved reference file changed. Generate and review a new take.')
        selected.append(candidate)
    return selected


def brief_for(record):
    selected=selected_candidates(record);scenes=[];cursor=0
    for shot,candidate in zip(record['shots'],selected):
        inputs=shot['input'];scenes.append(dict(start=round(cursor,3),duration=inputs['duration'],overlay_text=inputs['overlay_text'],voiceover=inputs['voiceover'],
            visual_prompt=inputs['visual_prompt'],asset_id=candidate['asset_id'],motion=inputs['motion'],background_style=inputs['background_style']))
        cursor+=inputs['duration']
    if not 6<=cursor<=60:raise ValueError('The reviewed timeline must be between 6 and 60 seconds.')
    return dict(brief_id=record['id'],request={**record['request'],'duration':round(cursor,3)},brand=record['governance']['brand'],
        scenes=scenes,planning_source=record['script_source'])


def compliance(record,project=None):
    from video.assets import path_for
    from agency.campaign_quality import PLACEHOLDER
    governance=record['governance'];rules=governance['rules'];findings=[]
    def finding(code,state,message):findings.append(dict(code=code,state=state,message=message))
    text='\n'.join(s['input']['overlay_text']+' '+s['input']['voiceover'] for s in record['shots'])
    if PLACEHOLDER.search(text):finding('PLACEHOLDER','FAIL','Replace unfinished script placeholders.')
    for term in rules.get('prohibited_elements',[]):
        if term.strip() and term.casefold() in text.casefold():finding('BANNED_WORDING','FAIL','Prohibited script wording: '+term)
    for phrase in rules.get('required_disclosures',[]):
        if phrase.casefold() not in text.casefold():finding('DISCLOSURE','FAIL','Required disclosure is absent from the script: '+phrase)
    logo=governance['brand'].get('logo_asset_id')
    if logo and file_hash(path_for(logo))!=governance['logo_sha256']:finding('LOGO_ARTWORK','FAIL','The snapshotted logo file changed. Start a new production with the current logo.')
    finding('IDENTITY_LAYERS','PASS','Corporate text and logos are compositor-owned layers, separate from the generated plates.')
    if project:
        if digest(project.brand_rules)!=digest(rules):finding('GOVERNANCE','FAIL','Timeline brand rules differ from the frozen governance pack.')
        if logo and not any(c.kind=='overlay' and c.asset_id==logo for c in project.clips):finding('LOGO','FAIL','The frozen company logo is missing from the timeline.')
        palette={color.lower() for color in rules['primary_colors']+rules['secondary_colors']}|{'#ffffff','#000000','#07111c'}
        if rules.get('caption_color'):palette.add(rules['caption_color'].lower())
        font=governance['brand']['font_family']
        for clip in project.clips:
            if clip.kind!='title':continue
            color=(clip.graphic_style or {}).get('fill',clip.color)
            if color and color[:7].lower() not in palette:finding('TITLE_COLOR','FAIL','A title uses a colour outside the frozen palette.')
            actual_font=(clip.graphic_style or {}).get('font_name') or clip.font_family
            if actual_font and actual_font.casefold()!=font.casefold():finding('TYPOGRAPHY','FAIL','A title uses a font outside the frozen typography choice.')
            for term in rules.get('prohibited_elements',[]):
                if term and term.casefold() in clip.text.casefold():finding('BANNED_TITLE','FAIL','A timeline title contains prohibited wording: '+term)
        for track in project.caption_tracks:
            style=track.get('brand_style') or {}
            if style.get('fill') and style['fill'].lower() not in palette:finding('CAPTION_COLOR','FAIL','A caption uses a colour outside the frozen palette.')
            if style.get('font_name') and style['font_name'].casefold()!=font.casefold():finding('CAPTION_FONT','FAIL','A caption uses a font outside the frozen typography choice.')
            for cue in track.get('segments',[]):
                if PLACEHOLDER.search(cue.get('text','')):finding('CAPTION_PLACEHOLDER','FAIL','A caption contains unfinished placeholder text.')
                for term in rules.get('prohibited_elements',[]):
                    if term and term.casefold() in cue.get('text','').casefold():finding('BANNED_CAPTION','FAIL','A caption contains prohibited wording: '+term)
        from video.brand_editing import compliance as brand_compliance
        report=brand_compliance(project)
        # Text-only required caption checks in the legacy checker do not see separate caption tracks.
        for item in report['findings']:
            if item['state']=='FAIL' and not (item['code']=='REQUIRED_ELEMENT' and 'caption' in item['message'].lower() and project.caption_tracks):
                findings.append(item)
    return dict(passed=not any(f['state']=='FAIL' for f in findings),findings=findings,
        notice='Timeline rules and managed artwork checks. Appearance, continuity, spelling and footage rights still require named human review.')


def assemble(record,options,job,work):
    from video.sequence import build_sequence_project,footage_timing,needs_interpolation
    from video.director import RenderSequenceRequest
    from video.assets import ingest
    from video.projects import save
    brief=brief_for(record);audio_id=options.voiceover_asset_id;narration=None
    if options.narrator_voice and audio_id:raise ValueError('Choose either the local narrator or a recorded voiceover.')
    if options.narrator_voice:
        from video.voice import narrate
        track,narration=narrate(brief['scenes'],record['request']['language'],options.narrator_voice,brief['request']['duration'],work,job)
        audio_id=ingest(track,'producer-narration.wav',job)['id'];narration['asset_id']=audio_id
    request=RenderSequenceRequest(brief_id=record['id'],burn_subtitles=options.burn_subtitles,
        voiceover_asset_id=audio_id,music_asset_id=options.music_asset_id,music_volume=options.music_volume)
    report={};project=build_sequence_project(brief,request,job,work,narration,report)
    project.name=record['name'];project.brand_rules=record['governance']['rules'];project.brand_id=record['request']['brand_id']
    project.guideline_id=record['governance']['guideline_id'];project.guideline_version=record['governance']['guideline_version']
    project.canvas.fps=30;project.export_quality='high';project.dialogue_polish=bool(audio_id);project.normalize_audio=bool(audio_id or options.music_asset_id)
    for clip in project.clips:
        if clip.kind=='title':
            clip.color=record['governance']['rules']['caption_color']
            if clip.graphic_style:clip.graphic_style={**clip.graphic_style,'fill':clip.color}
    for track in project.caption_tracks:
        style=track.get('brand_style')
        if style and record['governance']['rules'].get('caption_color'):style['fill']=record['governance']['rules']['caption_color']
    primaries=[c for c in project.clips if c.kind=='video']
    overlaps=[0]+[min(s['input']['transition_seconds'],record['shots'][i-1]['input']['duration']/4,s['input']['duration']/4)
        if s['input']['transition']=='fade' else 0 for i,s in enumerate(record['shots']) if i>0]+[0]
    for i,(clip,shot) in enumerate(zip(primaries,record['shots'])):
        clip.duration=round(shot['input']['duration']+overlaps[i+1],3);clip.transition=overlaps[i];clip.transition_type='fade'
        meta=read('assets',clip.asset_id)
        if meta['kind']=='video':
            clip.trim,clip.speed=footage_timing(meta,clip.duration)
            clip.smooth_motion=needs_interpolation(meta,clip.speed,project.canvas.fps)
    placement=record['governance']['rules'].get('logo_placement')
    if placement:
        for clip in project.clips:
            if clip.kind=='overlay' and clip.asset_id==record['governance']['brand'].get('logo_asset_id'):
                clip.x=.12 if placement.endswith('left') else .88;clip.y=.14 if placement.startswith('top') else .72;clip.scale=.16
    checked=compliance(record,project)
    if not checked['passed']:raise ValueError('Resolve the frozen brand rules before rendering: '+'; '.join(f['message'] for f in checked['findings'] if f['state']=='FAIL')[:900])
    stored=save(project,actor='user',instruction='Assembled final-approved producer shots',label='Producer timeline')
    return stored,report,narration


def variant_project(master,aspect,master_id):
    from video.variants import create_platform_variant
    variant=create_platform_variant(master,master_id,aspect)
    w,h=variant.canvas.width,variant.canvas.height
    for clip,original in zip(variant.clips,master.clips):
        if clip.kind=='video':clip.fit='blur-fill';clip.scale=1
        if clip.kind=='overlay':clip.x=original.x;clip.y=original.y
        if clip.graphic_style:
            style=dict(clip.graphic_style);style.update(canvas_width=w,canvas_height=h,reference_width=w)
            # Reflow the same text; never crop a raster title from the wide master.
            style['font_size_px']=max(20,min(96,round(w*.045)));style['max_width_pct']=.76
            clip.graphic_style=style;clip.layout_box=[0,0,w,h]
    for track in variant.caption_tracks:
        style=track.get('brand_style')
        if style:style.update(reference_width=w,font_size_px=max(20,min(64,round(w*.045))),max_width_pct=.76,y_pct=.76 if aspect=='9:16' else .82)
    return variant


def render_production(record,options,job):
    import tempfile
    from video.storage import DATA
    from video.qa import master
    from video.assets import path_for
    from video.projects import save
    from video.ffmpeg import probe
    selected_candidates(record)
    with tempfile.TemporaryDirectory(dir=DATA/'work',prefix='producer-finish-') as folder:
        if record.get('timeline_project_id'):
            stored=read('projects',record['timeline_project_id']);report={};narration=None
        else:stored,report,narration=assemble(record,options,job,Path(folder))
        project=project_model(stored);state_hash=timeline_hash(stored);checked=compliance(record,project)
        if not checked['passed']:raise ValueError('The timeline fails frozen brand compliance. Check the production review panel.')
        audio=any(c.kind=='audio' for c in project.clips)
        output=master(project,job,audio=audio,captions_requested=bool(project.caption_tracks and options.burn_subtitles))
        if timeline_hash(read('projects',stored['id']))!=state_hash:raise ValueError('The timeline changed while rendering. Render the current edit again.')
        outputs={}
        for aspect in dict.fromkeys(options.variants):
            job.update(phase='Rendering platform variant '+aspect,progress=None)
            variant=variant_project(project,aspect,stored['id']);saved=save(variant,actor='user',instruction='Reframed producer variant',label='Producer '+aspect)
            if not compliance(record,variant)['passed']:raise ValueError('Platform variant fails the frozen brand rules. Review logo placement, text and typography.')
            result=master(variant,job,audio=audio,captions_requested=bool(variant.caption_tracks and options.burn_subtitles))
            outputs[aspect]=dict(asset_id=result['id'],url=result['url'],qa=result.get('qa_report'),project_id=saved['id'],timeline_sha256=timeline_hash(saved),
                file_sha256=file_hash(path_for(result['id'])))
        meta=probe(path_for(output['id']))
        return dict(asset_id=output['id'],url=output['url'],project_id=stored['id'],timeline_sha256=state_hash,file_sha256=file_hash(path_for(output['id'])),
            qa=output.get('qa_report'),compliance=checked,variants=outputs,rendered_at=__import__('time').time(),
            native_metadata={k:meta[k] for k in ('width','height','duration','fps','video_codec','has_audio')},caption_report=report.get('captions'),narration=narration)
