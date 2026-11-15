"""Reusable speech-aware edits over managed assets and the existing timeline renderer.

No filename, identity or hard-coded source timestamp participates in edit decisions. Every cut
and punch-in is recorded with its reason, the evidence it rests on and a confidence, and the
exported file is measured before it is reported as finished (video_qa).
"""
import re
from pydantic import Field
from video_projects import Strict,Project,Clip,Canvas,save
from video_storage import read,uid
from video_transcription import transcribe,status as speech_status
from video_assets import annotate,path_for
from video_editor import validate_sources
from video_brand_editing import model,polish,checked,effective_rules
from video_presets import PRESETS,preset,canvas_for

FILLERS={'um','umm','uh','uhh','erm'}
TERMINAL=('.','?','!','؟')


class QuickEdit(Strict):
    asset_id: str=Field(pattern=r'^[a-f0-9]{32}$')
    instruction: str=Field('Add readable captions, tighten pauses and use subtle zooms.',max_length=1000)
    captions: bool=True
    tighten_pauses: bool=True
    subtle_zooms: bool=True
    trim_recording_tail: bool=True
    language: str=Field('auto',pattern=r'^(auto|en|ar)$')
    aspect: str=Field('source',pattern=r'^(source|9:16|16:9|1:1|4:5)$')
    delivery: str=Field('web-youtube',pattern=r'^(source-master|web-youtube|vertical-social|square-social|portrait-feed|broadcast-ebu)$')
    max_punch_in: float=Field(1.06,ge=1.0,le=1.12)


def words_from(transcript):
    words=[]
    for segment in transcript.get('segments',[]):
        for word in segment.get('words',[]):
            if word.get('word','').strip() and 0<=word['start']<word['end']:
                words.append(dict(word))
    return sorted(words,key=lambda x:x['start'])


def _silent_share(start,end,silences):
    """Share of [start,end) inside measured silence, or None when silence was not measured."""
    if silences is None:return None
    span=max(1e-6,end-start)
    return sum(max(0.,min(end,s['end'])-max(start,s['start'])) for s in silences)/span


def keep_ranges(duration,words,tighten=True,tail=True,silences=None):
    """Decide what to remove. Returns (kept ranges, cuts); each cut explains itself.

    Pauses inside a sentence are tightened; a pause after a finished sentence is a natural beat
    and is only shortened when it runs long, and then more air is left. When silence was measured
    and the gap is not actually quiet (laughter, a gesture, room sound), the pause is kept.
    """
    cuts=[]
    def cut(start,end,reason,kind,confidence,evidence):
        cuts.append(dict(start=start,end=end,reason=reason,kind=kind,confidence=round(confidence,2),evidence=evidence))
    normalized=[re.sub(r'[^\w]','',w['word']).casefold() for w in words]
    def certainty(*items):
        return min([w.get('probability',1) for w in items] or [1])
    if words and tighten:
        if words[0]['start']>.5:
            share=_silent_share(0,words[0]['start']-.16,silences)
            if share is None or share>=.6:
                cut(0,max(0,words[0]['start']-.16),'Leading silence','pause',.95 if share is not None else .8,
                    f"First recognised word starts at {words[0]['start']:.2f}s"+(f'; {share:.0%} of the lead-in is measured silence' if share is not None else '; silence was not measured'))
        for a,b in zip(words,words[1:]):
            gap=b['start']-a['end']
            ended=a['word'].strip().endswith(TERMINAL)
            threshold,air=(1.0,.25) if ended else (.65,.16)
            if gap<=threshold:continue
            start,end=a['end']+air,b['start']-air
            share=_silent_share(start,end,silences)
            if share is not None and share<.6:continue      # audible content in the gap: not a dead pause
            base=.95 if share is not None else .75
            cut(start,end,'Long speech pause','pause',base*(.7+.3*certainty(a,b)),
                f"{gap:.2f}s between \"{a['word'].strip()}\" and \"{b['word'].strip()}\""
                +(' after a finished sentence (0.5s of pause kept)' if ended else ' inside a sentence (0.32s kept)')
                +(f'; {share:.0%} measured silence' if share is not None else '; silence was not measured'))
        for word,label in zip(words,normalized):
            if label in FILLERS and word['end']-word['start']<1.1 and word.get('probability',1)>=.6:
                cut(max(0,word['start']-.02),min(duration,word['end']+.02),'Recognized filler','filler',word.get('probability',1),
                    f"Recognised \"{word['word'].strip()}\" with {word.get('probability',1):.0%} confidence")
    if words and tail:
        for i in range(len(words)-1):
            phrase=' '.join(normalized[i:i+3])
            terminal=(phrase.startswith(('okay stop','ok stop','stop recording','cut recording','okay thats it','ok thats it')) or phrase.startswith('thats a wrap'))
            # Only recording instructions near the end, never an arbitrary earlier mention.
            if terminal and words[i]['start']>duration*.55 and len(words)-i<=9:
                cut(max(0,words[i]['start']-.04),duration,'Trailing recording instruction','recording-direction',certainty(*words[i:i+3]),
                    'Closing phrase "'+' '.join(w['word'].strip() for w in words[i:i+3])+'" in the last part of the recording');break
        else:
            if duration-words[-1]['end']>.45:
                cut(words[-1]['end']+.18,duration,'Trailing silence','pause',.9,f"Last recognised word ends at {words[-1]['end']:.2f}s of {duration:.2f}s")
    merged=[]
    for item in sorted(cuts,key=lambda c:(c['start'],c['end'])):
        start,end=max(0,item['start']),min(duration,item['end'])
        if end<=start:continue
        if merged and start<=merged[-1]['end']:
            last=merged[-1]
            last.update(end=max(end,last['end']),reason=last['reason']+'; '+item['reason'],evidence=last['evidence']+' · '+item['evidence'],
                        confidence=min(last['confidence'],item['confidence']))
        else:merged.append(dict(item,start=start,end=end))
    ranges=[];cursor=0
    for item in merged:
        if item['start']-cursor>=.15:ranges.append((cursor,item['start']))
        cursor=max(cursor,item['end'])
    if duration-cursor>=.15:ranges.append((cursor,duration))
    if sum(b-a for a,b in ranges)<.5:raise ValueError('Speech cuts would remove too much footage. Disable pause cleanup and retry.')
    return ranges,[dict(c,start=round(c['start'],3),end=round(c['end'],3),removed_seconds=round(c['end']-c['start'],3)) for c in merged]


def punch_in_plan(ranges,words,enabled=True,max_scale=1.06,face=None):
    """Shots with a held framing each. The framing changes only where an editor would change it:
    across a cut (so the jump reads as a deliberate change of size) or at the start of a new
    sentence after the current framing has been held for a while. No continuous zooming."""
    if face and face.get('headroom',1)<.08:max_scale=min(max_scale,1.03)   # keep the head inside the frame
    sentence_starts=[b['start'] for a,b in zip(words,words[1:]) if a['word'].strip().endswith(TERMINAL)]
    shots=[];level=0;held=0.
    for index,(start,end) in enumerate(ranges):
        if index and enabled and max_scale>1:
            level=1-level;held=0.
            reason='Framing change across the cut so the edit reads as intentional'
        else:reason='Opening framing' if not index else 'Continuous take'
        cursor=start
        for moment in sentence_starts:
            if not (enabled and max_scale>1):break
            if cursor+2.5<=moment<=end-2.5 and held+(moment-cursor)>=4.:
                shots.append(dict(start=cursor,end=moment,scale=max_scale if level else 1.,reason=reason))
                held=0.;level=1-level;cursor=moment
                reason='New sentence after the previous framing was held for 4 seconds or more'
        shots.append(dict(start=cursor,end=end,scale=max_scale if level else 1.,reason=reason))
        held+=end-cursor
    return shots


def caption_cues(words,ranges):
    mapped=[];offset=0
    for start,end in ranges:
        for word in words:
            if word['start']>=start-.02 and word['end']<=end+.02:
                mapped.append(dict(text=word['word'].strip(),start=max(offset,offset+word['start']-start),end=offset+min(end,word['end'])-start,
                                   probability=word.get('probability',1)))
        offset+=end-start
    cues=[];group=[]
    def flush():
        if group:cues.append(dict(start=round(group[0]['start'],3),end=round(max(group[-1]['end'],group[0]['start']+.2),3),text=' '.join(x['text'] for x in group),
                                  words=[dict(word=x['text'],probability=round(x['probability'],3)) for x in group]))
    for word in mapped:
        if group and (len(group)>=5 or len(' '.join(x['text'] for x in group)) +len(word['text'])>32 or word['end']-group[0]['start']>2.1 or word['start']-group[-1]['end']>.5):flush();group=[]
        group.append(word)
        if word['text'].endswith(TERMINAL):flush();group=[]
    flush()
    # A one- or two-word cue that flashes by is unreadable: join it to a neighbour when the
    # combined line still fits and the two are spoken back to back.
    merged=[]
    for cue in cues:
        previous=merged[-1] if merged else None
        if previous and (cue['end']-cue['start']<.7 or previous['end']-previous['start']<.7) \
                and cue['start']-previous['end']<.35 and len(previous['text'])+1+len(cue['text'])<=42:
            previous.update(end=cue['end'],text=previous['text']+' '+cue['text'],words=previous['words']+cue['words'])
        else:merged.append(cue)
    cues=merged
    # Hold each cue long enough to read, without running into the next one.
    for index,cue in enumerate(cues):
        limit=cues[index+1]['start']-.02 if index+1<len(cues) else cue['end']+.6
        cue['end']=round(min(limit,max(cue['end'],cue['start']+.8)),3)
    return cues


def build(project,asset,request,transcript,silences=None,face=None):
    words=words_from(transcript)
    inst=request.instruction.casefold()
    tighten=request.tighten_pauses and not any(s in inst for s in ('keep all pauses','no cuts','do not cut'))
    zoom=request.subtle_zooms and not any(s in inst for s in ('no zoom','do not zoom'))
    captions=request.captions and not any(s in inst for s in ('no captions','without captions'))
    ranges,cuts=keep_ranges(asset['duration'],words,tighten,request.trim_recording_tail,silences)
    shots=punch_in_plan(ranges,words,zoom,request.max_punch_in,face)
    if len(shots)>40:raise ValueError('Too many cuts for one edit. Disable pause cleanup or shorten the source.')
    spec=preset(request.delivery)
    aspect=None if request.aspect=='source' else request.aspect
    w,h=canvas_for(asset['width'],asset['height'],aspect or spec['aspect'],spec['max_edge'])
    project.canvas=Canvas(width=w,height=h,fps=30,fps_mode='original' if 1<=asset['fps']<=60 else 'fixed')
    project.export_quality='high';project.name=(project.name[:95]+' · edited')
    project.delivery_preset=spec['id']
    project.normalize_audio=bool(asset.get('has_audio',False) and spec['loudness'])
    project.clips=[]
    for i,shot in enumerate(shots):
        project.clips.append(Clip(asset_id=asset['id'],trim=round(shot['start'],4),duration=round(shot['end']-shot['start'],4),
            zoom_start=shot['scale'],zoom=shot['scale'],fade_in=.1 if i==0 else 0,fade_out=.12 if i==len(shots)-1 else 0))
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
    caption_diagnostic=''
    if captions and not cues:
        state=speech_status()
        caption_diagnostic=('The source has no audio track, so there is no speech to caption.' if not asset.get('has_audio')
            else state['reason'] if not state['available'] else 'Speech recognition ran but found no words in this recording.')
        warnings.append('Captions were requested but not created: '+caption_diagnostic+' You can import a reviewed SRT in the Advanced editor.')
    if any(s in inst for s in ('background','4k','upscale')):warnings.append('Background replacement and restored 4K detail are not implemented by this editor. The original scene and native detail are preserved.')
    for item in cuts:
        if item['confidence']<.6:
            warnings.append(f"Review the cut at {item['start']:.2f}s ({item['reason'].lower()}): it rests on low-confidence speech recognition ({item['confidence']:.0%}).")
    mean_confidence=sum(w.get('probability',1) for w in words)/len(words) if words else None
    if words and mean_confidence<.7:
        warnings.append(f'Speech recognition confidence is low (average {mean_confidence:.0%})'
            +(' with automatic language detection; choose the spoken language and run again.' if request.language=='auto' else '; review every caption before publishing.'))
    if zoom and not words:warnings.append('No punch-ins were added: without word timings there is no sentence or cut to justify a framing change.')
    project.editing_brief.instruction=request.instruction
    validate_sources(project)
    edited=round(sum(c.duration for c in project.clips if c.kind=='video'),3)
    changes=[shot for index,shot in enumerate(shots) if index and shot['scale']!=shots[index-1]['scale']]
    logo=next((c for c in project.clips if c.kind=='overlay'),None)
    decisions=[dict(type='CUT',start=c['start'],end=c['end'],reason=c['reason'],evidence=c['evidence'],confidence=c['confidence'],
                    effect=f"Removes {c['removed_seconds']:.2f}s",source='rule') for c in cuts]
    position=0.
    for index,shot in enumerate(shots):
        if index and shot['scale']!=shots[index-1]['scale']:
            decisions.append(dict(type='PUNCH_IN' if shot['scale']>1 else 'PUNCH_OUT',start=round(position,3),end=round(position+shot['end']-shot['start'],3),
                                  reason=shot['reason'],evidence=f"Held at {shot['scale']:.2f}× (maximum {request.max_punch_in:.2f}×); no continuous zoom",
                                  confidence=.8,effect='Changes framing size at an edit point',source='rule'))
        position+=shot['end']-shot['start']
    decisions.append(dict(type='TRANSITION',start=0,end=edited,reason='Clean cuts between takes; one short fade in and out at the ends',
                          evidence='No dissolve was requested by the brief or the brand rules',confidence=1.,effect='No crossfades added',source='rule'))
    if cues:decisions.append(dict(type='CAPTIONS',start=cues[0]['start'],end=cues[-1]['end'],reason='Burned-in captions from local speech recognition',
                                  evidence=f"{len(cues)} cues from {len(words)} recognised words; unreviewed draft",confidence=round(sum(w.get('probability',1) for w in words)/max(1,len(words)),2),
                                  effect='Adds readable captions',source='rule'))
    if logo:decisions.append(dict(type='LOGO',start=logo.start,end=round(logo.start+logo.duration,3),reason='Brand logo from the selected logo or guideline',
                                  evidence='Logo asset chosen in the brand step',confidence=1.,effect='Adds the logo on a backplate',source='rule'))
    decisions.append(dict(type='AUDIO',start=0,end=edited,reason=spec['label']+' mastering',
                          evidence=(f"Normalise to {spec['loudness']['integrated']} LUFS, " if project.normalize_audio else 'Loudness left as recorded, ')+f"true peak ceiling {spec['true_peak_ceiling']} dBTP",
                          confidence=1.,effect='Measured after export',source='rule'))
    report=dict(engine='measured-speech-and-timeline-rules',ai_text_planner_used=False,speech_model_used=bool(transcript),captions_requested=captions,
        source_duration=asset['duration'],edited_duration=edited,duration_removed=round(sum(c['removed_seconds'] for c in cuts),3),
        cuts=cuts,decisions=decisions,caption_count=len(cues),caption_draft=bool(cues),caption_diagnostic=caption_diagnostic,
        zoom_segments=len(changes),punch_in_scale=request.max_punch_in if changes else None,silence_measured=silences is not None,
        delivery_preset=dict(id=spec['id'],label=spec['label'],note=spec['note']),
        uncertain_words=[w['word'] for w in words if w.get('probability',1)<.6 and any(a<=w['start'] and w['end']<=b for a,b in ranges)],
        original_dimensions=[asset['width'],asset['height']],output_dimensions=[project.canvas.width,project.canvas.height],warnings=list(dict.fromkeys(warnings)))
    return project,report


def run(original,request,job):
    from video_qa import master,sha256
    asset=read('assets',request.asset_id)
    if asset['kind']!='video':raise ValueError('Choose one uploaded video as the source. Logos belong in the logo section.')
    before=sha256(path_for(asset['id']))
    transcript={}
    if asset.get('has_audio') and speech_status()['available']:
        transcript=transcribe(asset['id'],request.language,job)
    # Measured facts about the source: silence (to confirm pauses), face framing, loudness, colour tags.
    analysis=None;silences=None;face=None
    try:
        from video_analysis import analyze_asset
        job.update(state='running',phase='Measuring the source video')
        analysis=analyze_asset(asset['id'],job=job)
        if asset.get('has_audio'):silences=[s.model_dump() for s in analysis.silence_segments]
        face=next((s.face for s in analysis.shots if s.face),None)
    except ValueError:
        pass      # analysis tools unavailable: decisions fall back to word timings and say so
    project,report=build(original.model_copy(deep=True),asset,request,transcript,silences,face)
    if analysis:
        report['source_analysis']=dict(technical=analysis.technical.model_dump(),audio=analysis.audio_metrics.model_dump(),
            motion_scores=[s.motion_score for s in analysis.shots],face=face,black_intervals=analysis.black_intervals,
            frozen_intervals=analysis.frozen_intervals,not_measured=analysis.not_measured,warnings=analysis.warnings)
        report['warnings']=list(dict.fromkeys(report['warnings']+analysis.warnings))
    job.update(state='encoding',phase='Rendering the edited timeline',progress={'cuts':len(report['cuts']),'captions':report['caption_count']})
    saved=save(project,actor='rule_engine',instruction=request.instruction,label='Quick edit · source project preserved')
    result=master(project,job,source_asset=asset,source_sha_before=before,cuts=report['cuts'],captions_requested=report['captions_requested'])
    result=annotate(result,project_id=saved['id'],edit_report=report,source_asset_id=asset['id'])
    return result
