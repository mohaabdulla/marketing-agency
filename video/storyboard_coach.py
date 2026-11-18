"""Explainable editorial planning. Estimates guide review; measured narrator timing wins.

Reading targets are house targets, informed by Ofcom's 160–180 WPM subtitle guidance:
https://www.ofcom.org.uk/siteassets/resources/documents/tv-radio-and-on-demand/broadcast-codes/other-codes/access-service-code-jan-2017.pdf
They are not measurements of a specific speaker or a guarantee of accessibility.
"""
import math
import re

STRUCTURES={
    'company_intro':['identity','services','audience','invitation'],
    'product_launch':['hook','product-benefit','invitation'],
    'hiring':['opportunity','role-and-team','invitation'],
    'explainer':['problem','demonstration','next-step'],
    'brand_announcement':['announcement','what-changes','invitation']}
SHOTS={
    'identity':'Wide establishing view of the actual workplace, then a human detail. Show who the company is.',
    'services':'Medium process shot followed by a close-up of the product or service in use. Show the work.',
    'audience':'Eye-level view of the customer context or a real team collaboration. Show who benefits.',
    'proof':'Show the real project or process supporting the approved claim; use only sourced outcomes.',
    'hook':'Close-up of the product in its actual use context. Open with one clear subject.',
    'product-benefit':'Medium demonstration shot of the named product solving the stated need.',
    'opportunity':'Wide workplace establishing shot with a welcoming team interaction.',
    'role-and-team':'Over-the-shoulder view of the stated role doing relevant work; avoid unrelated office stock.',
    'problem':'Contextual wide shot of the stated task or problem; avoid invented before-and-after claims.',
    'demonstration':'Close process detail showing the described steps or service in use.',
    'announcement':'A clear hero composition of the company or subject being announced.',
    'what-changes':'Medium detail shot illustrating the specific change described in the brief.',
    'invitation':'Simple brand end card with clear space for the approved call to action; no unrelated stock.',
    'next-step':'Simple closing composition showing the next action; keep the approved CTA readable.'}


def beats(campaign,count):
    if campaign=='company_intro' and count==5:return ['identity','services','audience','proof','invitation']
    base=STRUCTURES.get(campaign,STRUCTURES['product_launch'])
    if count==len(base):return list(base)
    if count<len(base):return [*base[:count-1],base[-1]]
    return [base[0],*([base[1]]*(count-2)),base[-1]]


def word_count(text):
    return len(re.findall(r"[^\W_]+(?:['’-][^\W_]+)*",text,re.UNICODE))


def reading_seconds(text,language='en',pacing='balanced'):
    # Conservative planning estimates, including a small breath/pause allowance.
    wpm={'calm':125,'balanced':145,'fast':165}.get(pacing,145)
    if language=='ar':wpm*=.9
    return round(.45+word_count(text)*60/wpm,3)


def balance_timing(scenes,total,language='en',pacing='balanced'):
    """Redistribute the chosen runtime without deleting words, changing assets or growing the film."""
    if not scenes or total<len(scenes):raise ValueError('Allow at least one second per scene')
    weights=[max(.1,reading_seconds(s['voiceover'],language,pacing)-1) for s in scenes]
    minimum=1000;remaining=round(total*1000)-len(scenes)*minimum
    raw=[remaining*w/sum(weights) for w in weights]
    spans=[minimum+math.floor(n) for n in raw]
    for i in sorted(range(len(spans)),key=lambda i:raw[i]-math.floor(raw[i]),reverse=True)[:round(total*1000)-sum(spans)]:spans[i]+=1
    cursor=0;result=[]
    for scene,span in zip(scenes,spans):
        result.append({**scene,'start':cursor/1000,'duration':span/1000});cursor+=span
    return result


def review_storyboard(scenes,settings,assets=None):
    """A deterministic, source-transparent review of the current edit, not a fabricated AI score."""
    assets=assets or {};issues=[];reports=[];seen=set();used=set();cursor=0
    def issue(code,message,scene=None,severity='warning'):
        issues.append(dict(code=code,message=message,scene=scene,severity=severity))
    roles=beats(settings.get('campaign_type'),len(scenes))
    for i,scene in enumerate(scenes):
        number=i+1;duration=scene['duration'];voice=scene['voiceover'];headline=scene['overlay_text']
        estimated=reading_seconds(voice,settings.get('language','en'),settings.get('pacing','balanced'))
        if abs(scene.get('start',cursor)-cursor)>.02:issue('timing',f'Scene {number}: the timeline has a gap or overlap.',number,'error')
        cursor+=duration
        if duration<1:issue('timing',f'Scene {number}: allow at least one second.',number,'error')
        budget=max(1,int(max(0,duration-.45)*({'calm':125,'balanced':145,'fast':165}.get(settings.get('pacing'),145))*(.9 if settings.get('language')=='ar' else 1)/60))
        if estimated>duration+.2:issue('narration-pace',f'Scene {number}: about {estimated:.1f}s of narration in {duration:g}s. Shorten the script, balance timing, or increase the runtime.',number)
        if len(headline)>72 or word_count(headline)>12:issue('headline-density',f'Scene {number}: the headline is dense. Keep one short idea and put detail in the narration.',number)
        if re.search(r'\[[^\]]+\]|\b(?:TODO|TBD|INSERT HERE)\b',voice+' '+headline,re.I):issue('placeholder',f'Scene {number}: replace unfinished placeholders before delivery.',number)
        fingerprint=' '.join(headline.casefold().split())
        if fingerprint in seen:issue('repetition',f'Scene {number}: this headline repeats an earlier scene.',number)
        seen.add(fingerprint)
        asset_id=scene.get('asset_id');media=assets.get(asset_id,{})
        if asset_id in used:issue('repeated-visual',f'Scene {number}: this visual is reused; check that the repetition supports the story.',number)
        if asset_id:used.add(asset_id)
        if media:
            if media.get('width') and min(media.get('width',0),media.get('height',0))<settings.get('resolution',720):issue('media-resolution',f'Scene {number}: the visual may look soft at the selected resolution.',number)
            if media.get('kind')=='video' and media.get('duration',0)<duration*.75:issue('media-duration',f'Scene {number}: choose a longer video clip or shorten the scene.',number,'error')
        reports.append(dict(scene=number,beat=roles[i],words=word_count(voice),suggested_word_budget=budget,
            estimated_narration_seconds=estimated,duration=duration,visual_source=media.get('kind') or ('selected media' if asset_id else 'branded motion graphics')))
    if abs(cursor-settings['duration'])>.02:issue('total-duration',f'Scenes total {cursor:g}s; the selected runtime is {settings["duration"]:g}s.',severity='error')
    return dict(status='needs-attention' if issues else 'ready-for-review',issues=issues,scenes=reports,
        duration=round(cursor,3),estimated_narration_seconds=round(sum(s['estimated_narration_seconds'] for s in reports),3),
        notice='Timing is a planning estimate. Preview the selected narrator for measured speech timing; review all claims and selected visuals before delivery.')
