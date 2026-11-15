"""Reusable speech-aware edits over managed assets and the existing timeline renderer.

No filename, identity or hard-coded source timestamp participates in edit decisions.
"""
import re
from pydantic import Field
from video_projects import Strict,Project,Clip,Canvas,save
from video_storage import read,uid
from video_transcription import transcribe,status as speech_status
from video_assets import annotate
from video_editor import render,validate_sources
from video_brand_editing import model,polish,checked,effective_rules


class QuickEdit(Strict):
    asset_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    instruction: str=Field('Add readable captions, tighten pauses and use subtle zooms.',max_length=1000)
    captions: bool=True
    tighten_pauses: bool=True
    subtle_zooms: bool=True
    trim_recording_tail: bool=True
    language: str=Field('auto',pattern=r'^(auto|en|ar)$')
    aspect: str=Field('source',pattern=r'^(source|9:16|16:9|1:1|4:5)$')


def words_from(transcript):
    words=[]
    for segment in transcript.get('segments',[]):
        for word in segment.get('words',[]):
            if word.get('word','').strip() and 0<=word['start']<word['end']:
                words.append(dict(word))
    return sorted(words,key=lambda x:x['start'])


def keep_ranges(duration,words,tighten=True,tail=True):
    """Keep breathing room around words; only remove measured gaps/fillers/end markers."""
    cuts=[]
    normalized=[re.sub(r'[^\w]','',w['word']).casefold() for w in words]
    if words and tighten:
        if words[0]['start']>.5:cuts.append((0,max(0,words[0]['start']-.16),'Leading silence'))
        for a,b in zip(words,words[1:]):
            if b['start']-a['end']>.65:cuts.append((a['end']+.16,b['start']-.16,'Long speech pause'))
        for word,label in zip(words,normalized):
            if label in {'um','umm','uh','uhh','erm'} and word['end']-word['start']<1.1:
                cuts.append((max(0,word['start']-.02),min(duration,word['end']+.02),'Recognized filler'))
    if words and tail:
        for i in range(len(words)-1):
            phrase=' '.join(normalized[i:i+3])
            terminal=(phrase.startswith(('okay stop','ok stop','stop recording','cut recording','okay thats it','ok thats it')) or phrase.startswith('thats a wrap'))
            # Only recording instructions near the end, never an arbitrary earlier mention.
            if terminal and words[i]['start']>duration*.55 and len(words)-i<=9:
                cuts.append((max(0,words[i]['start']-.04),duration,'Trailing recording instruction'));break
        else:
            if duration-words[-1]['end']>.45:cuts.append((words[-1]['end']+.18,duration,'Trailing silence'))
    merged=[]
    for start,end,reason in sorted(cuts):
        start,end=max(0,start),min(duration,end)
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]),merged[-1][2]+'; '+reason)
        else:merged.append((start,end,reason))
    ranges=[];cursor=0
    for start,end,_ in merged:
        if start-cursor>=.15:ranges.append((cursor,start))
        cursor=max(cursor,end)
    if duration-cursor>=.15:ranges.append((cursor,duration))
    if sum(b-a for a,b in ranges)<.5:raise ValueError('Speech cuts would remove too much footage. Disable pause cleanup and retry.')
    return ranges,[dict(start=round(a,3),end=round(b,3),reason=reason) for a,b,reason in merged]


def caption_cues(words,ranges):
    mapped=[];offset=0
    for start,end in ranges:
        for word in words:
            if word['start']>=start-.02 and word['end']<=end+.02:
                mapped.append(dict(text=word['word'].strip(),start=max(offset,offset+word['start']-start),end=offset+min(end,word['end'])-start))
        offset+=end-start
    cues=[];group=[]
    def flush():
        if group:cues.append(dict(start=round(group[0]['start'],3),end=round(max(group[-1]['end'],group[0]['start']+.2),3),text=' '.join(x['text'] for x in group)))
    for word in mapped:
        if group and (len(group)>=5 or len(' '.join(x['text'] for x in group)) +len(word['text'])>32 or word['end']-group[0]['start']>2.1 or word['start']-group[-1]['end']>.5):flush();group=[]
        group.append(word)
        if word['text'].endswith(('.', '?','!')):flush();group=[]
    flush()
    return cues


def build(project,asset,request,transcript):
    words=words_from(transcript)
    inst=request.instruction.casefold()
    tighten=request.tighten_pauses and not any(s in inst for s in ('keep all pauses','no cuts','do not cut'))
    zoom=request.subtle_zooms and not any(s in inst for s in ('no zoom','do not zoom'))
    captions=request.captions and not any(s in inst for s in ('no captions','without captions'))
    ranges,cuts=keep_ranges(asset['duration'],words,tighten,request.trim_recording_tail)
    # Align subtle punch-ins to measured word boundaries rather than cutting inside words.
    shots=[]
    for start,end in ranges:
        cursor=start
        while zoom and end-cursor>5.1 and len(shots)<25:
            options=[w['start'] for w in words if cursor+2.8<=w['start']<=min(end-.8,cursor+4.8)]
            boundary=min(options,key=lambda t:abs(t-(cursor+3.8))) if options else cursor+3.8
            shots.append((cursor,boundary));cursor=boundary
        shots.append((cursor,end))
    if len(shots)>40:raise ValueError('Too many cuts for one edit. Disable pause cleanup or shorten the source.')
    w,h=asset['width'],asset['height'];ratio=min(1,1920/max(w,h));w,h=round(w*ratio/2)*2,round(h*ratio/2)*2
    if request.aspect!='source':
        a,b=map(int,request.aspect.split(':'));edge=min(w,h);w,h=(edge*a/b,edge) if a>=b else (edge,edge*b/a);ratio=min(1,1920/max(w,h));w,h=round(w*ratio/2)*2,round(h*ratio/2)*2
    project.canvas=Canvas(width=max(128,w),height=max(128,h),fps=30,fps_mode='original' if 1<=asset['fps']<=60 else 'fixed')
    project.export_quality='high';project.name=(project.name[:95]+' · edited')
    project.normalize_audio=asset.get('has_audio',False)
    project.clips=[]
    for i,(start,end) in enumerate(shots):
        z=(1,1.035) if i%2==0 else (1.07,1.09)
        project.clips.append(Clip(asset_id=asset['id'],trim=round(start,4),duration=round(end-start,4),
            zoom_start=z[0] if zoom else 1,zoom=z[1] if zoom else 1,fade_in=.1 if i==0 else 0,fade_out=.12 if i==len(shots)-1 else 0))
    # Rebuild overlays from reviewed setup. Old captions/extra primary images cannot leak into this edit.
    project.caption_tracks=[]
    rules=effective_rules(project)
    plan=polish(project,request.instruction,rules)
    project=checked(project,plan)
    for clip in project.clips:
        if clip.kind=='overlay' and clip.asset_id==rules.logo_asset_id:
            clip.logo_backplate=True;clip.scale=.30
    cues=caption_cues(words,ranges) if captions else []
    from video_editor import primary_layout
    duration=primary_layout(project)[1]
    cues=[dict(cue,end=min(cue['end'],duration)) for cue in cues if cue['start']<duration-.1]
    if cues:project.caption_tracks=[dict(id=uid(),language=transcript.get('language','en'),source='whisper',reviewed=False,style_id='quick-social',burn_in=True,segments=cues)]
    warnings=plan.warnings+plan.unfulfilled_requests
    if cues:warnings=[w for w in warnings if not w.startswith('No transcript was supplied.')]
    if max(asset['width'],asset['height'])>1920:warnings.append('This renderer is limited to a 1920-pixel canvas. The larger source was resized; no original 4K detail is claimed.')
    if captions and not cues:warnings.append('No speech captions were created. Configure local speech recognition or import a reviewed SRT.')
    if any(s in inst for s in ('background','4k','upscale')):warnings.append('Background replacement and restored 4K detail are not implemented by this editor. The original scene and native detail are preserved.')
    project.editing_brief.instruction=request.instruction
    validate_sources(project)
    report=dict(engine='measured-speech-and-timeline-rules',ai_text_planner_used=False,speech_model_used=bool(transcript),captions_requested=captions,
        source_duration=asset['duration'],edited_duration=round(sum(c.duration for c in project.clips if c.kind=='video'),3),
        cuts=cuts,caption_count=len(cues),caption_draft=bool(cues),zoom_segments=len(shots) if zoom else 0,
        uncertain_words=[w['word'] for w in words if w.get('probability',1)<.6 and any(a<=w['start'] and w['end']<=b for a,b in ranges)],
        original_dimensions=[asset['width'],asset['height']],output_dimensions=[project.canvas.width,project.canvas.height],warnings=list(dict.fromkeys(warnings)))
    return project,report


def run(original,request,job):
    asset=read('assets',request.asset_id)
    if asset['kind']!='video':raise ValueError('Choose one uploaded video as the source. Logos belong in the logo section.')
    transcript={}
    if asset.get('has_audio') and speech_status()['available']:
        transcript=transcribe(asset['id'],request.language,job)
    project,report=build(original.model_copy(deep=True),asset,request,transcript)
    job.update(state='encoding',phase='Rendering the edited timeline',progress={'cuts':len(report['cuts']),'captions':report['caption_count']})
    saved=save(project,actor='rule_engine',instruction=request.instruction,label='Quick edit · source project preserved')
    result=render(project,job,audio=True)
    result=annotate(result,project_id=saved['id'],edit_report=report,source_asset_id=asset['id'])
    return result
