"""Speech-aware, human-directed quick edit over managed assets and the existing timeline renderer.

No filename, identity or hard-coded source timestamp participates in edit decisions. Every
decision records its purpose, evidence and confidence. Low-confidence cuts are proposed, not
applied. Requests the editor cannot fulfil are reported as such, never dropped silently.
Technical delivery QA (video_qa) and editorial QA (video_editorial_qa) are separate gates.
"""
import hashlib
import re
from typing import Annotated, Literal
from pydantic import Field
from video_projects import Strict, Clip, Canvas, BackgroundTreatment, ColorPipeline, save
from video_storage import read, uid
from video_transcription import transcribe, status as speech_status
from video_assets import annotate, path_for
from video_editor import validate_sources
from video_brand_editing import polish, checked, effective_rules
from video_presets import preset, canvas_for
import video_platforms

FILLERS = {'um', 'umm', 'uh', 'uhh', 'erm'}
TERMINAL = ('.', '?', '!', '؟')
AUTO_CUT_CONFIDENCE = 0.6        # below this a cut is only proposed
REVIEW_CUT_CONFIDENCE = 0.8      # below this an applied cut is marked "review recommended"
NAME_REVIEW_CONFIDENCE = 0.6     # a likely name recognised below this must be confirmed by a person


def metric(values, key, fmt):
    value = values.get(key)
    return format(value, fmt) if value is not None else 'not measured'


class QuickEdit(Strict):
    graphic_motion: Literal['fade','slide-up','masked-reveal','soft-scale'] = 'fade'
    preview_frames: bool = False
    color_look: Literal['auto','organic','polished-organic','corporate-clean','warm-lifestyle','high-energy','cinematic-brand'] = 'auto'
    reference_asset_id: str | None = Field(None,pattern=r'^[a-f0-9]{32}$')
    reference_preferences: list[Literal['pacing','caption-hierarchy','energy','color-mood']] = Field(default_factory=list,max_length=4)
    performance_tier: Literal['basic-cpu','enhanced-cpu','gpu-professional'] = 'enhanced-cpu'
    dialogue_noise_reduction: bool = False
    dialogue_hum_hz: Literal[0,50,60] = 0
    dialogue_deess: bool = False
    caption_max_cps: float | None = Field(None,ge=8,le=30)
    cut_policy: Literal['safe','balanced','aggressive'] = 'balanced'
    semantic_planner: Literal['auto','off','local'] = 'auto'
    asset_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    instruction: str = Field('Add readable captions, tighten pauses and use subtle zooms.', max_length=6000)
    captions: bool = True
    tighten_pauses: bool = True
    subtle_zooms: bool = True
    trim_recording_tail: bool = True
    language: str = Field('auto', pattern=r'^(auto|en|ar)$')
    aspect: str = Field('source', pattern=r'^(source|9:16|16:9|1:1|4:5)$')
    delivery: str = Field('web-youtube', pattern=r'^(source-master|web-youtube|vertical-social|square-social|portrait-feed|broadcast-ebu)$')
    max_punch_in: float | None = Field(None, ge=1.0, le=1.12)
    style: str = Field('auto', pattern=r'^(auto|organic|polished-organic|high-energy|brand-forward)$')
    motion_intensity: str = Field('minimal', pattern=r'^(minimal|balanced|expressive)$')
    lighting: str = Field('auto', pattern=r'^(auto|off)$')
    background: str = Field('auto', pattern=r'^(auto|none|blur-dim|replace)$')
    background_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    platform_profile: str = Field('auto', pattern=r'^(auto|tiktok-ltr|tiktok-rtl|instagram-reels|instagram-stories|meta-reels-ads|youtube-shorts|youtube-standard|generic-vertical|generic-horizontal)$')
    canvas_mode: str = Field('native', pattern=r'^(native|platform)$')
    dialogue_polish: bool = False
    approved_cuts: list[Annotated[str, Field(pattern=r'^[a-f0-9]{10}$')]] = Field(default_factory=list, max_length=40)
    caption_corrections: dict[Annotated[str, Field(max_length=60)], Annotated[str, Field(max_length=60)]] = Field(default_factory=dict, max_length=40)
    story_roles: dict[Annotated[str, Field(pattern=r'^sentence-\d{1,3}$')], Literal['HOOK','SETUP','VALUE','PAYOFF','CTA']] = Field(default_factory=dict, max_length=60)
    captions_reviewed: bool = False
    dry_run: bool = False
    plan_variants: bool = False
    parent_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')


def words_from(transcript):
    words = []
    for segment in transcript.get('segments', []):
        for word in segment.get('words', []):
            if word.get('word', '').strip() and 0 <= word['start'] < word['end']:
                words.append(dict(word))
    return sorted(words, key=lambda x: x['start'])


def _silent_share(start, end, silences):
    """Share of [start,end) inside measured silence, or None when silence was not measured."""
    if silences is None:
        return None
    span = max(1e-6, end - start)
    return sum(max(0., min(end, s['end']) - max(start, s['start'])) for s in silences) / span


def cut_id(item):
    return hashlib.sha1(f"{item['kind']}:{item['start']:.2f}:{item['end']:.2f}".encode()).hexdigest()[:10]


def cut_candidates(duration, words, tighten=True, tail=True, silences=None, pause_threshold=.65):
    """Every removal the rules can justify, each with its evidence and confidence.

    Pauses inside a sentence are tightened; a pause after a finished sentence is a natural beat
    and is only shortened when it runs long, and then more air is left. When silence was measured
    and the gap is not actually quiet (laughter, a gesture, room sound), the pause is kept.
    """
    cuts = []

    def cut(start, end, reason, kind, confidence, evidence, transcript_confidence=None, corroboration=()):
        item = dict(start=max(0, start), end=min(duration, end), reason=reason, kind=kind, confidence=round(confidence, 2), evidence=evidence,
                    transcript_confidence=round(transcript_confidence, 2) if transcript_confidence is not None else None,
                    corroboration=list(corroboration), semantic_confidence=None, visual_confidence=None, overall_confidence=round(confidence, 2),
                    story_impact='Timing-only removal; spoken meaning is not assessed.' if kind == 'pause' else 'Removes spoken material; check context before publishing.',
                    requires_approval=confidence < AUTO_CUT_CONFIDENCE)
        if item['end'] > item['start']:
            cuts.append(dict(item, id=cut_id(item)))

    normalized = [re.sub(r'[^\w]', '', w['word']).casefold() for w in words]

    def certainty(*items):
        return min([w.get('probability', 1) for w in items] or [1])

    if words and tighten:
        if words[0]['start'] > .5:
            share = _silent_share(0, words[0]['start'] - .16, silences)
            if share is None or share >= .6:
                cut(0, words[0]['start'] - .16, 'Leading silence', 'pause', .95 if share is not None else .8,
                    f"First recognised word starts at {words[0]['start']:.2f}s" + (f'; {share:.0%} of the lead-in is measured silence' if share is not None else '; silence was not measured'),
                    corroboration=['measured silence'] if share is not None else [])
        for a, b in zip(words, words[1:]):
            gap = b['start'] - a['end']
            ended = a['word'].strip().endswith(TERMINAL)
            threshold, air = (max(1.0, pause_threshold + .35), .25) if ended else (pause_threshold, .16)
            if gap <= threshold:
                continue
            start, end = a['end'] + air, b['start'] - air
            share = _silent_share(start, end, silences)
            if share is not None and share < .6:
                continue      # audible content in the gap: not a dead pause
            base = .95 if share is not None else .75
            cut(start, end, 'Long speech pause', 'pause', base * (.7 + .3 * certainty(a, b)),
                f"{gap:.2f}s between \"{a['word'].strip()}\" and \"{b['word'].strip()}\""
                + (f' after a finished sentence ({2 * air:.1f}s of pause kept)' if ended else f' inside a sentence ({2 * air:.2f}s kept)')
                + (f'; {share:.0%} measured silence' if share is not None else '; silence was not measured'),
                certainty(a, b), ['measured silence'] if share is not None else [])
        for word, label in zip(words, normalized):
            if label in FILLERS and word['end'] - word['start'] < 1.1 and word.get('probability', 1) >= .6:
                cut(word['start'] - .02, word['end'] + .02, 'Recognized filler', 'filler', word.get('probability', 1),
                    f"Recognised \"{word['word'].strip()}\" with {word.get('probability', 1):.0%} confidence", word.get('probability', 1))
    if words and tail:
        for i in range(len(words) - 1):
            phrase = ' '.join(normalized[i:i + 3])
            terminal = (phrase.startswith(('okay stop', 'ok stop', 'stop recording', 'cut recording', 'okay thats it', 'ok thats it')) or phrase.startswith('thats a wrap'))
            # Only recording instructions near the end, never an arbitrary earlier mention.
            if terminal and words[i]['start'] > duration * .55 and len(words) - i <= 9:
                heard = certainty(*words[i:i + 3])
                # A removal that changes meaning rests on what was said: its confidence is the
                # recognition confidence. Position alone does not raise it.
                cut(words[i]['start'] - .04, duration, 'Trailing recording instruction', 'recording-direction', heard,
                    'Closing phrase "' + ' '.join(w['word'].strip() for w in words[i:i + 3]) + f'" in the last part of the recording, recognised with {heard:.0%} confidence',
                    heard, ['phrase is at the end of the recording'])
                break
        else:
            if duration - words[-1]['end'] > .45:
                share = _silent_share(words[-1]['end'] + .18, duration, silences)
                if share is None or share >= .6:
                    cut(words[-1]['end'] + .18, duration, 'Trailing silence', 'pause', .9 if share is None else .95,
                        f"Last recognised word ends at {words[-1]['end']:.2f}s of {duration:.2f}s", corroboration=['measured silence'] if share is not None else [])
    return cuts


def merge_cuts(cuts, duration):
    merged = []
    for item in sorted(cuts, key=lambda c: (c['start'], c['end'])):
        if merged and item['start'] <= merged[-1]['end']:
            last = merged[-1]
            last.update(end=max(item['end'], last['end']), reason=last['reason'] + '; ' + item['reason'], evidence=last['evidence'] + ' · ' + item['evidence'],
                        confidence=min(last['confidence'], item['confidence']))
        else:
            merged.append(dict(item))
    ranges, cursor = [], 0
    for item in merged:
        if item['start'] - cursor >= .15:
            ranges.append((cursor, item['start']))
        cursor = max(cursor, item['end'])
    if duration - cursor >= .15:
        ranges.append((cursor, duration))
    if sum(b - a for a, b in ranges) < .5:
        raise ValueError('Speech cuts would remove too much footage. Disable pause cleanup and retry.')
    return ranges, [dict(c, start=round(c['start'], 3), end=round(c['end'], 3), removed_seconds=round(c['end'] - c['start'], 3)) for c in merged]


def keep_ranges(duration, words, tighten=True, tail=True, silences=None):
    """All justified cuts applied (no approval policy). Returns (kept ranges, cuts)."""
    return merge_cuts(cut_candidates(duration, words, tighten, tail, silences), duration)


def plan_cuts(duration, words, tighten=True, tail=True, silences=None, pause_threshold=.65, approved=(),policy=None):
    """Apply the approval policy. Returns (kept ranges, applied cuts, proposed cuts awaiting approval)."""
    applied, proposed = [], []
    for item in cut_candidates(duration, words, tighten, tail, silences, pause_threshold):
        threshold=AUTO_CUT_CONFIDENCE
        if policy:
            threshold={'safe':.95,'balanced':.75,'aggressive':.65}[policy] if item['kind']=='pause' else {'safe':.97,'balanced':.86,'aggressive':.74}[policy]
        if item['confidence'] >= threshold or item['id'] in approved:
            applied.append(dict(item, approval='approved by you' if item['id'] in approved else
                                'review recommended' if item['confidence'] < REVIEW_CUT_CONFIDENCE else 'applied'))
        else:
            proposed.append(dict(item, start=round(item['start'], 3), end=round(item['end'], 3), removed_seconds=round(item['end'] - item['start'], 3),
                                 requires_approval=True))
    ranges, merged = merge_cuts(applied, duration)
    return ranges, merged, proposed


def sentences(words):
    """Sentence spans from recognised punctuation: [(start, end, text)]."""
    spans, current = [], []
    for word in words:
        current.append(word)
        if word['word'].strip().endswith(TERMINAL):
            spans.append((current[0]['start'], current[-1]['end'], ' '.join(w['word'].strip() for w in current)))
            current = []
    if current:
        spans.append((current[0]['start'], current[-1]['end'], ' '.join(w['word'].strip() for w in current)))
    return spans


def emphasis_moments(source_path, words, ranges, limit):
    """Sentences worth a punch-in, chosen from measured movement (gesture/expression), not a timer.

    Returns [(start, end, reason, evidence)]. Empty when motion cannot be measured or no sentence
    stands out: then no emphasis punch-in is added."""
    import video_measure
    spans = [s for s in sentences(words) if s[1] - s[0] >= 1.0 and any(a - .05 <= s[0] and s[1] <= b + .05 for a, b in ranges)]
    if len(spans) < 2 or limit < 1:
        return []
    profile = video_measure.visual_profile(source_path, [dict(start=s[0], end=s[1]) for s in spans], sample_fps=6.0)
    if not profile:
        return []
    scored = [(entry['motion_mean_abs_diff'], span) for entry, span in zip(profile, spans) if entry['motion_mean_abs_diff'] is not None]
    if len(scored) < 2:
        return []
    ordered = sorted(m for m, _ in scored)
    median = ordered[len(ordered) // 2]
    chosen = [(m, span) for m, span in sorted(scored, key=lambda x: -x[0]) if median > 0 and m >= 1.2 * median][:limit]
    return [(span[0], span[1], 'Emphasise the most animated sentence (gesture and expression)',
             f'Measured movement {m / median:.1f}× the clip median while saying "{span[2][:60]}"') for m, span in sorted(chosen, key=lambda x: x[1][0])]


def punch_in_plan(ranges, enabled=True, max_scale=1.06, face=None, emphasis=()):
    """Shots with a held framing each. Framing changes only for a stated purpose: to emphasise a
    measured moment, or across a cut so the jump reads as a deliberate change of size."""
    if face and face.get('headroom', 1) < .08:
        max_scale = min(max_scale, 1.03)        # little headroom: keep the head inside the frame
    active = enabled and max_scale > 1
    shots, level = [], 0
    for index, (start, end) in enumerate(ranges):
        reason, evidence = ('Opening framing', 'Source framing') if not index else ('Continuous take', 'No change')
        if index and active:
            level = 1 - level
            reason, evidence = 'Hide the jump at a cut with a change of framing size', 'A cut joins two takes of the same shot here'
        cursor = start
        for moment_start, moment_end, why, proof in (emphasis if active else ()):
            if moment_start < cursor + .4 or moment_end > end + .05 or moment_start >= end - .8:
                continue
            if moment_start - cursor >= .4:
                shots.append(dict(start=cursor, end=moment_start, scale=max_scale if level else 1., reason=reason, evidence=evidence))
            shots.append(dict(start=moment_start, end=min(end, moment_end), scale=1. if level else max_scale, reason=why, evidence=proof))
            cursor = min(end, moment_end)
            reason, evidence = 'Return to the base framing after the emphasised sentence', 'Emphasis ended'
        if end - cursor >= .15:
            shots.append(dict(start=cursor, end=end, scale=max_scale if level else 1., reason=reason, evidence=evidence))
        elif shots:
            shots[-1]['end'] = end
    return shots


def likely_names(words):
    """Capitalised words that do not start a sentence: probable names or organisations."""
    found, sentence_start = [], True
    for word in words:
        text = word['word'].strip()
        bare = re.sub(r"[^\w'-]", '', text)
        if bare and not sentence_start and bare[0].isupper() and bare.lower() not in {'i', "i'm", "i'll", "i've", "i'd"} and bare.isascii():
            found.append(dict(heard=bare, start=round(word['start'], 2), confidence=round(word.get('probability', 1), 2)))
        sentence_start = text.endswith(TERMINAL) and bare.casefold() not in {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr'}
    return found


def story_map(words, duration, motion=(), face=None, roles=None):
    """Editable source-time structure. Roles are positional suggestions, never inferred meaning."""
    result = []
    groups = sentences(words)
    for index, group in enumerate(groups):
        start, end, text = group
        sentence_words = [w for w in words if start <= w['start'] < end]
        role = 'HOOK' if index == 0 else 'PAYOFF' if index == len(groups) - 1 else 'SETUP' if index == 1 else 'VALUE'
        key = f'sentence-{index + 1}'
        result.append(dict(id=key, start=start, end=end, text=text, suggested_role=(roles or {}).get(key, role),
                           basis='USER SUPPLIED' if key in (roles or {}) else 'POSITIONAL SUGGESTION', semantic_importance=None, semantic_confidence=None,
                           transcript_confidence=round(sum(w.get('probability', 1) for w in sentence_words) / len(sentence_words), 3),
                           gesture_emphasis=any(a <= start < b or start <= a < end for a, b, *_ in motion), face=face,
                           review_required=True))
    return dict(segments=result, duration=duration, reordered=False,
                notice='Opening/setup/value/close labels are editable positional suggestions. Meaning, hook strength and sentence importance need a person or the optional semantic planner. No statements were reordered.')


def apply_corrections(words, corrections):
    """Replace recognised words with the operator's corrections. Returns (words, applied heard-words)."""
    lookup = {k.strip().casefold(): v.strip() for k, v in corrections.items() if k.strip() and v.strip() and len(v) <= 60}
    applied, result = [], []
    for word in words:
        text = word['word'].strip()
        bare = re.sub(r"[^\w'-]", '', text)
        if bare.casefold() in lookup:
            trailing = text[len(text.rstrip('.,!?؟;:')):]
            result.append(dict(word, word=lookup[bare.casefold()] + trailing, probability=1.0, corrected_from=bare))
            applied.append(bare)
        else:
            result.append(word)
    return result, applied


def caption_cues(words, ranges, language='en', max_cps=None):
    from video_caption_timing import map_words, optimize
    mapped, duration = map_words(words, ranges)
    return optimize(mapped, duration, language, max_cps)[0]


REQUESTS = [
    ('background', 'Improve the background', r'background|backdrop'),
    ('lighting', 'Improve the lighting', r'light|brighten|exposure|colou?r[- ]?(grade|correct)|darker|brighter'),
    ('text', 'Add words on screen', r'words? on (the )?screen|on[- ]screen (text|words)|\btext\b|\btitles?\b|captions?|subtitles?|typography|hierarchy'),
    ('story','Review the story and hook',r'\bhook\b|\bstory\b|redundan|repetit'),
    ('effects', 'Add effects', r'effects?|zoom|punch[- ]?in|transition|animation|motion'),
    ('pacing', 'Tighten the pacing', r'\bcuts?\b|trim|shorten|tighten|pauses?|faster|pace|pacing'),
    ('music', 'Add music or sound effects', r'music|soundtrack|sound effects?|\bsfx\b|whoosh'),
    ('audio', 'Improve the sound', r'audio|\bsound\b|voice|noise|louder|quieter|volume'),
    ('resolution', 'Increase resolution or sharpness', r'\b4k\b|upscale|\bhd\b|resolution|sharper|sharpen'),
    ('reframe', 'Reframe for the platform', r'vertical|9:16|square|1:1|reframe|crop'),
]


def requested(instruction):
    text = (instruction or '').lower()
    return [(key, label) for key, label, pattern in REQUESTS if re.search(pattern, text)]


def build(project, asset, request, transcript, silences=None, face=None, context=None):
    """Plan the edit on a copy of the project. `context` carries measured facts gathered by run():
    lighting correction report, matting status/mask metadata, emphasis moments."""
    context = context or {}
    words = words_from(transcript)
    words, corrected = apply_corrections(words, request.caption_corrections)
    inst = request.instruction.casefold()
    tighten = request.tighten_pauses and not any(s in inst for s in ('keep all pauses', 'no cuts', 'do not cut'))
    zoom = request.subtle_zooms and not any(s in inst for s in ('no zoom', 'do not zoom'))
    captions = request.captions and not any(s in inst for s in ('no captions', 'without captions'))

    style_text = request.instruction + ' ' + project.creative_context.style
    style_id, style_words = (request.style, []) if request.style != 'auto' else video_platforms.interpret_style(style_text)
    style = video_platforms.STYLES[style_id]
    punch_scale = request.max_punch_in or style['punch_in']
    reference=context.get('reference') or {}
    emphasis_limit=style['max_emphasis']
    if reference and 'energy' in request.reference_preferences:
        energy=reference.get('motion_energy') or 0.
        if request.max_punch_in is None:punch_scale=round(1.03+min(.06,energy*.08),3)
        emphasis_limit=1 if energy<.15 else min(4,style['max_emphasis']+1)

    pause_threshold=style['pause_threshold']
    if context.get('reference') and 'pacing' in request.reference_preferences:
        from video_reference import pacing_threshold
        pause_threshold=pacing_threshold(context['reference'],pause_threshold)
    ranges, cuts, proposed = plan_cuts(asset['duration'], words, tighten, request.trim_recording_tail, silences, pause_threshold, set(request.approved_cuts),request.cut_policy)
    semantic=context.get('semantic') or {}
    if not any(term in inst for term in ('no cuts','do not cut','keep all speech')):
        for candidate in semantic.get('candidates',[]):
            if any(min(c['end'],candidate['end'])-max(c['start'],candidate['start'])>.1 for c in cuts+proposed):
                continue # keep the existing measured proposal and its uncertainty; no duplicate deletion
            candidate=dict(candidate,removed_seconds=round(candidate['end']-candidate['start'],3))
            if candidate['requires_approval'] and candidate['id'] not in request.approved_cuts:
                proposed.append(candidate)
            else:
                cuts.append(dict(candidate,approval='approved by you' if candidate['id'] in request.approved_cuts else 'semantic proposal under selected cut policy'))
        ranges,cuts=merge_cuts(cuts,asset['duration'])
    emphasis = context.get('emphasis') or []
    emphasis = [m for m in emphasis if any(a - .05 <= m[0] and m[1] <= b + .05 for a, b in ranges)][:emphasis_limit]
    shots = punch_in_plan(ranges, zoom, punch_scale, face, emphasis)
    if len(shots) > 40:
        raise ValueError('Too many cuts for one edit. Disable pause cleanup or shorten the source.')

    spec = preset(request.delivery)
    aspect = None if request.aspect == 'source' else request.aspect
    w, h = canvas_for(asset['width'], asset['height'], aspect or spec['aspect'], spec['max_edge'])
    language = transcript.get('language') or (request.language if request.language != 'auto' else 'en')
    platform_text = request.instruction if re.search(r'\b(tiktok|instagram|reels?|stories|shorts|youtube)\b', inst) else project.creative_context.platform
    platform_id = request.platform_profile if request.platform_profile != 'auto' else video_platforms.choose(platform_text, w, h, language)
    platform = video_platforms.profile(platform_id)
    canvas_note = 'Native master: source resolution kept.'
    if request.canvas_mode == 'platform':
        target_w, target_h = platform['recommended']
        ratio = min(target_w / w, target_h / h, 1920 / max(w, h) if max(w, h) else 1)
        if ratio > 1.01:
            w, h = int(w * ratio / 2) * 2, int(h * ratio / 2) * 2
            canvas_note = (f'Platform canvas: scaled from {asset["width"]}×{asset["height"]} to {w}×{h}. '
                           'Scaling makes the file fit the platform; it does not restore detail that the source never had.')
    project.canvas = Canvas(width=w, height=h, fps=30, fps_mode='original' if 1 <= asset['fps'] <= 60 else 'fixed')
    project.export_quality = 'high'
    project.name = (project.name[:95] + ' · edited')
    project.delivery_preset = spec['id']
    project.normalize_audio = bool(asset.get('has_audio', False) and spec['loudness'])
    project.dialogue_polish = bool(request.dialogue_polish and asset.get('has_audio'))
    noise_requested=bool(re.search(r'denoise|(?:remove|reduce|clean).{0,20}noise',inst)) and 'no noise reduction' not in inst
    project.dialogue_noise_reduction=(request.dialogue_noise_reduction or noise_requested) and bool(asset.get('has_audio'))
    project.dialogue_hum_hz=request.dialogue_hum_hz if asset.get('has_audio') else 0
    project.dialogue_deess=request.dialogue_deess and bool(asset.get('has_audio'))
    project.motion_intensity = request.motion_intensity
    project.motion_preset=request.graphic_motion

    # Lighting: a measured, pixel-verified correction (video_grade), applied to every shot of the take.
    correction = context.get('lighting') or dict(status='NOT_MEASURED', reason='Lighting was not analysed.', grade={})
    wants_light = request.lighting == 'auto' and (any(k == 'lighting' for k, _ in requested(request.instruction)) or correction.get('status') == 'CORRECTED')
    grade = {k: v for k, v in (correction.get('grade') or {}).items()} if wants_light and correction.get('status') == 'CORRECTED' else {}

    # Background: only with a subject mask. Never silently skipped.
    wants_background = any(k == 'background' for k, _ in requested(request.instruction))
    matting = context.get('matting') or dict(available=False, reason='Subject matting was not checked.')
    from video_background import interpret
    background_intent=interpret(request.instruction,request.background,request.background_asset_id)
    mode=background_intent['mode']
    if mode == 'replace' and not request.background_asset_id:
        mode = 'blur-dim'
    project.background = None
    if mode != 'none' and matting.get('available'):
        project.background = BackgroundTreatment(mode=mode, replacement_asset_id=request.background_asset_id if mode == 'replace' else None,**background_intent['parameters'])
        project.background.mask_fps=6 if request.performance_tier=='basic-cpu' else 24 if (context.get('performance') or {}).get('selected')=='gpu-professional' else 12

    project.color_pipeline=None
    if context.get('regional_pipeline'):
        project.color_pipeline=ColorPipeline.model_validate(context['regional_pipeline'])
    elif face and matting.get('available') and correction.get('status')=='CORRECTED':
        from video_grade import plan_regional
        project.color_pipeline=plan_regional(correction,asset['id'],style_id if request.color_look=='auto' else request.color_look)
        if reference.get('color') and 'color-mood' in request.reference_preferences:
            project.color_pipeline.subject.temperature=round(max(-.04,min(.04,reference['color']['red_blue_balance']*.1)),4)
    if project.color_pipeline:
        project.color_pipeline.mask_fps=project.background.mask_fps if project.background else 6 if request.performance_tier=='basic-cpu' else 12
    clip_grade={} if project.color_pipeline and project.color_pipeline.regional else grade

    anchor_x, anchor_y = (.5, .5)
    if face:
        anchor_x = min(.7, max(.3, face['x'] + face['width'] / 2))
        anchor_y = min(.7, max(.3, face['y'] + face['height'] / 2))
    project.clips = []
    for i, shot in enumerate(shots):
        from video_tracking import keyframes
        tracked=keyframes(context.get('tracking') or {},shot['start'],shot['end'])
        continuous=i>0 and abs(shots[i-1]['end']-shot['start'])<.02 and shots[i-1]['scale']!=shot['scale']
        project.clips.append(Clip(asset_id=asset['id'], trim=round(shot['start'], 4), duration=round(shot['end'] - shot['start'], 4),
                                  zoom_start=shots[i-1]['scale'] if continuous else shot['scale'],zoom_ease=.25 if continuous else 0.,
                                  zoom=shot['scale'], zoom_x=anchor_x, zoom_y=anchor_y,reframe_keyframes=tracked,
                                  fade_in=.1 if i == 0 else 0, fade_out=.12 if i == len(shots) - 1 else 0, **clip_grade))
    # Rebuild overlays from reviewed setup. Old captions/extra primary images cannot leak into this edit.
    project.caption_tracks = []
    rules = effective_rules(project)
    if project.creative_context.cta.strip() and not rules.cta:
        rules = rules.model_copy(update={'cta': project.creative_context.cta.strip()})
    plan = polish(project, 'Apply reviewed brand styling.', rules)
    project = checked(project, plan)
    logo_note = ''
    for clip in project.clips:
        if clip.kind == 'overlay' and clip.asset_id == rules.logo_asset_id:
            clip.logo_backplate = True
            clip.scale = .30
            # Keep the logo out of the area the app interface covers (top bar, side buttons).
            lw = max(2, round(w * clip.scale / 2) * 2)
            left, top, right, _ = video_platforms.safe_area(platform, w, h)
            rtl = platform['left'] > platform['right']
            target_x = left if rtl else right - lw
            clip.x = min(1., max(0., target_x / max(1, w - lw)))
            clip.y = min(1., max(0., (top + h * .01) / max(1, h - lw * .3)))
            logo_note = f'Logo placed inside the {platform["label"]} safe area ({"left" if rtl else "right"} side, below the top bar).'
    from video_caption_timing import map_words, optimize
    mapped, mapped_duration = map_words(words,ranges)
    cues,caption_timing = optimize(mapped,mapped_duration,language,request.caption_max_cps) if captions else ([],{})
    from video_editor import primary_layout
    from video_captions import render_caption_image, CaptionStyle, brand_caption_style
    caption_brand, caption_warnings = brand_caption_style(rules, language)
    duration = primary_layout(project)[1]
    cues = [dict(cue, end=min(cue['end'], duration)) for cue in cues if cue['start'] < duration - .1]
    # Captions sit just above the platform's bottom interface area, measured with the tallest cue.
    safe_left, _, safe_right, safe_bottom = video_platforms.safe_area(platform, w, h)
    caption_y = video_platforms.caption_center(platform)
    # Text block stays inside the horizontal safe area too (side buttons), with room for its plate.
    placement = dict(max_width_pct=round(max(.4, min(.8, (safe_right - safe_left) / w - .07)), 4), x_center_pct=round((safe_left + safe_right) / 2 / w, 4))
    measured_style = CaptionStyle.model_validate(caption_brand).model_copy(update=placement)
    if cues:
        tallest = max((render_caption_image(c['text'], w, h, measured_style).info['caption_layout']['box'] for c in cues), key=lambda b: b[3] - b[1])
        caption_y = round(max(.5, (safe_bottom - (tallest[3] - tallest[1]) / 2 - 3) / h), 4)
    # Speaker name and role become one lower third on a plate, between the face and the captions.
    speaker = {c.text_role: c for c in project.clips if c.kind == 'title' and c.text_role in ('speaker_name', 'speaker_role')}
    lower_third_track = None
    if speaker:
        text = '\n'.join(speaker[role].text.strip() for role in ('speaker_name', 'speaker_role') if role in speaker)
        y = caption_y - .15
        if face:
            y = max(y, face['y'] + face['height'] + .09)
        shown = min(3.5, duration)
        lower_third_track = dict(id=uid(), kind='lower-third', language=language, source='manual', reviewed=True, style_id='lower-third',
                                 y_pct=min(.9, y), burn_in=True, motion=request.graphic_motion, brand_style=brand_caption_style(rules, language, 'lower-third')[0],
                                 segments=[dict(start=.3 if duration > 2 else 0, end=shown, text=text)], **placement)
        project.clips = [c for c in project.clips if c not in speaker.values()]

    names = likely_names([w_ for w_ in words if any(a - .02 <= w_['start'] and w_['end'] <= b + .02 for a, b in ranges)])
    unresolved = [n for n in names if n['confidence'] < NAME_REVIEW_CONFIDENCE]
    caption_state = 'none'
    if cues:
        caption_state = 'needs-review' if unresolved else 'reviewed' if request.captions_reviewed else 'draft-asr'
        project.caption_tracks = [dict(id=uid(), kind='captions', language=language, source='whisper', reviewed=caption_state == 'reviewed', state=caption_state,
                                       style_id='quick-social', brand_style=caption_brand, y_pct=caption_y, burn_in=True, segments=cues,
                                       max_cps=caption_timing['profile']['max_cps'], **placement)]
    if lower_third_track:
        project.caption_tracks.append(lower_third_track)

    warnings = plan.warnings + plan.unfulfilled_requests + caption_warnings
    if cues:
        warnings = [w_ for w_ in warnings if not w_.startswith('No transcript was supplied.')]
    if max(asset['width'], asset['height']) > 1920:
        warnings.append('This renderer is limited to a 1920-pixel canvas. The larger source was resized; no original 4K detail is claimed.')
    caption_diagnostic = ''
    if captions and not cues:
        state = speech_status()
        caption_diagnostic = ('The source has no audio track, so there is no speech to caption.' if not asset.get('has_audio')
                              else state['reason'] if not state['available'] else 'Speech recognition ran but found no words in this recording.')
        warnings.append('Captions were requested but not created: ' + caption_diagnostic + ' You can import a reviewed SRT in the Advanced editor.')
    for item in cuts:
        if item['confidence'] < REVIEW_CUT_CONFIDENCE:
            warnings.append(f"Review the cut at {item['start']:.2f}s ({item['reason'].lower()}, {item['confidence']:.0%} confidence).")
    mean_confidence = sum(w_.get('probability', 1) for w_ in words) / len(words) if words else None
    if words and mean_confidence < .7:
        warnings.append(f'Speech recognition confidence is low (average {mean_confidence:.0%})'
                        + (' with automatic language detection; choose the spoken language and run again.' if request.language == 'auto' else '; review every caption before publishing.'))
    project.editing_brief.instruction = request.instruction[:1000]
    validate_sources(project)
    edited = round(sum(c.duration for c in project.clips if c.kind == 'video'), 3)
    logo = next((c for c in project.clips if c.kind == 'overlay'), None)
    titles = [c for c in project.clips if c.kind == 'title']
    for title in titles:
        title.motion = request.graphic_motion
        title.fade_in = min(.25, title.duration / 4)
        title.fade_out = min(.18, title.duration / 4)
    framing_changes = [(i, shot) for i, shot in enumerate(shots) if i and shot['scale'] != shots[i - 1]['scale']]

    # ---- decisions: what, when, why, evidence, confidence, expected effect
    decisions = [dict(type='CUT', start=c['start'], end=c['end'], purpose=c['reason'], reason=c['reason'], evidence=c['evidence'], confidence=c['confidence'],
                      effect=f"Removes {c['removed_seconds']:.2f}s", requires_review=c['confidence'] < REVIEW_CUT_CONFIDENCE, source='rule') for c in cuts]
    position = 0.
    for index, shot in enumerate(shots):
        if index and shot['scale'] != shots[index - 1]['scale']:
            decisions.append(dict(type='PUNCH_IN' if shot['scale'] > 1 else 'PUNCH_OUT', start=round(position, 3), end=round(position + shot['end'] - shot['start'], 3),
                                  purpose=shot['reason'], reason=shot['reason'], evidence=shot['evidence'] + f" · held at {shot['scale']:.2f}×, anchored on the "
                                  + ('detected face' if face else 'frame centre'), confidence=.8 if 'Measured' in shot['evidence'] else .7,
                                  effect='Changes framing size; no continuous zoom', requires_review=False, source='rule',
                                  scale=shot['scale'], subject_anchor=[round(anchor_x, 3), round(anchor_y, 3)]))
        position += shot['end'] - shot['start']
    decisions.append(dict(type='TRANSITION', start=0, end=edited, purpose='Keep the edit clean', reason='Clean cuts between takes; one short fade in and out at the ends',
                          evidence='No dissolve was requested by the brief or the brand rules', confidence=1., effect='No crossfades added', requires_review=False, source='rule'))
    if grade:
        changes = correction.get('changes') or {}
        decisions.append(dict(type='LIGHTING', start=0, end=edited, purpose='Correct a backlit or dark subject', reason='; '.join(f['message'] for f in correction.get('findings', [])),
                              evidence=f"Checked on a rendered frame: face luminance {metric(changes, 'face_luma', '+.2f')}, skin hue shift {metric(changes, 'face_hue_shift', '.0f')}°, "
                                       f"clipped highlights {metric(changes, 'clipped_highlights', '+.1%')}", confidence=.85,
                              effect='Subject and background corrected separately' if project.color_pipeline else 'Conservative measured shot correction', requires_review=False, source='rule', parameters=grade))
    if project.background:
        mask = context.get('mask') or {}
        decisions.append(dict(type='BACKGROUND', start=0, end=edited, purpose='Separate the speaker from a distracting background',
                              reason='Background ' + ('replaced with the approved image' if project.background.mode == 'replace' else 'blurred and slightly dimmed') + ' behind a subject mask',
                              evidence=(f"Mask stability {mask['temporal_iou']:.2f} (1.0 = identical frame to frame), {mask['coverage_jumps']} abrupt change(s)" if mask.get('temporal_iou') is not None
                                        else 'The subject mask is generated when the edit is rendered'), confidence=.8 if mask.get('stable', True) else .5,
                              effect='Subject unchanged; background softened' if project.background.mode != 'replace' else 'Subject composited over the approved background',
                              requires_review=not mask.get('stable', True), source='rule'))
    if cues:
        decisions.append(dict(type='CAPTIONS', start=cues[0]['start'], end=cues[-1]['end'], purpose='Make the speech readable without sound',
                              reason='Burned-in captions from local speech recognition', evidence=f"{len(cues)} cues from {len(words)} recognised words"
                              + (f'; {len(corrected)} word(s) corrected by you' if corrected else ''), confidence=round(mean_confidence, 2),
                              effect=f'Captions placed above the {platform["label"]} bottom interface area', requires_review=caption_state != 'reviewed', source='rule'))
    if logo:
        decisions.append(dict(type='LOGO', start=logo.start, end=round(logo.start + logo.duration, 3), purpose='Brand the video', reason='Brand logo from the selected logo or guideline',
                              evidence=logo_note or 'Logo asset chosen in the brand step', confidence=1., effect='Adds the logo on a backplate', requires_review=False, source='rule'))
    if lower_third_track:
        segment = lower_third_track['segments'][0]
        decisions.append(dict(type='LOWER_THIRD', start=segment['start'], end=segment['end'], purpose='Introduce the speaker', reason='Lower third: "' + segment['text'].replace('\n', ' · ')[:70] + '"',
                              evidence='Name and position supplied in the brief; placed below the face and above the captions', confidence=1.,
                              effect='Readable name plate for the first seconds', requires_review=False, source='rule'))
    for title in titles:
        decisions.append(dict(type='TITLE', start=title.start, end=round(title.start + title.duration, 3), purpose='Identify the speaker or state the call to action',
                              reason=f'{title.text_role.replace("_", " ").title()}: "{title.text[:60]}"', evidence='Text supplied in the brief or the reviewed guideline',
                              confidence=1., effect='On-screen title', requires_review=False, source='rule'))
    decisions.append(dict(type='AUDIO', start=0, end=edited, purpose='Deliver at a consistent level without clipping', reason=spec['label'] + ' mastering'
                          + (' with dialogue high-pass and gentle compression' if project.dialogue_polish else ''),
                          evidence=(f"Normalise to {spec['loudness']['integrated']} LUFS, " if project.normalize_audio else 'Loudness left as recorded, ') + f"true peak ceiling {spec['true_peak_ceiling']} dBTP",
                          confidence=1., effect='Measured after export', requires_review=False, source='rule'))

    # ---- request fulfilment: every thing asked for is answered
    fulfilment = []
    def answer(key, label, status, detail):
        fulfilment.append(dict(request=key, label=label, status=status, detail=detail))
    asked = requested(request.instruction)
    for key, label in asked:
        if key == 'background':
            if project.background and project.background.mode == 'replace':
                answer(key, label, 'FULFILLED', 'The speaker was masked and composited over the approved background image.')
            elif project.background:
                answer(key, label, 'FULFILLED' if background_intent['intent'] in {'BLUR','DIM','DESATURATE'} else 'PARTIALLY_FULFILLED', 'The background behind the speaker has the selected masked treatment. '
                       'It is not replaced: choose "Replace with an approved image" and select an image to do that. Generating a new background is not available.')
            elif mode == 'none':
                answer(key, label, 'NOT_APPLIED', 'Background treatment is switched off in the settings.')
            else:
                answer(key, label, 'UNSUPPORTED', matting.get('reason', 'Subject matting is unavailable.'))
        elif key == 'lighting':
            status = correction.get('status')
            if grade:
                c = correction.get('changes') or {}
                answer(key, label, 'FULFILLED' if correction.get('subject_lift_effective', True) else 'PARTIALLY_FULFILLED', ('' if correction.get('subject_lift_effective', True) else 'Only a slight lift passed the skin checks; the face is still darker than intended. ') + f"Measured correction applied: face luminance {metric(c, 'face_luma', '+.2f')}, clipped highlights {metric(c, 'clipped_highlights', '+.1%')}, "
                       f"skin hue shift {metric(c, 'face_hue_shift', '.0f')}° (checked on a rendered frame).")
            elif request.lighting == 'off':
                answer(key, label, 'NOT_APPLIED', 'Lighting correction is switched off in the settings.')
            elif status == 'NO_CORRECTION_NEEDED':
                answer(key, label, 'NOT_NEEDED', correction.get('reason', 'Measured exposure is within normal ranges.'))
            elif status == 'REJECTED':
                answer(key, label, 'NOT_APPLIED', correction.get('reason', 'No correction passed the skin and highlight checks.'))
            else:
                answer(key, label, 'UNSUPPORTED', correction.get('reason', 'Lighting could not be measured on this machine.'))
        elif key == 'text':
            parts = ([f'{len(cues)} caption cues'] if cues else []) + (['a speaker lower third'] if lower_third_track else []) + ([f'{len(titles)} title(s)'] if titles else [])
            if cues or titles or lower_third_track:
                missing = captions and not cues
                answer(key, label, 'PARTIALLY_FULFILLED' if missing else 'FULFILLED', 'Added ' + ' and '.join(parts) + '.'
                       + (' Captions could not be created: ' + caption_diagnostic if missing else '')
                       + ('' if titles or lower_third_track else ' No title text was supplied in the brief (name, role or call to action), so only captions were added.'))
            else:
                answer(key, label, 'UNSUPPORTED', 'No on-screen text was added: ' + (caption_diagnostic or 'captions are off and no title text was supplied in the brief.'))
        elif key == 'effects':
            done = ([f'{len(framing_changes)} purpose-driven framing change(s)'] if framing_changes else []) + (['lighting correction'] if grade else []) \
                + (['background blur'] if project.background else []) + ['fade in and out at the ends']
            answer(key, label, 'FULFILLED' if framing_changes or grade or project.background else 'PARTIALLY_FULFILLED',
                   'Applied: ' + ', '.join(done) + '. Flashy transitions, filters and animated stickers are not added automatically.')
        elif key == 'pacing':
            if cuts or proposed:
                detail = f'{len(cuts)} cut(s) removed {sum(c["removed_seconds"] for c in cuts):.2f}s.' + (f' {len(proposed)} further cut(s) need your approval.' if proposed else '')
                answer(key, label, 'FULFILLED' if cuts else 'PARTIALLY_FULFILLED', detail)
            else:
                answer(key, label, 'NOT_NEEDED', 'No dead pause, filler or recording instruction met the evidence threshold.')
        elif key == 'music':
            answer(key, label, 'UNSUPPORTED', 'Music and sound effects are never added automatically. Add a licensed track in the Advanced editor; it will be ducked under speech.')
        elif key == 'audio':
            if not asset.get('has_audio'):
                answer(key,label,'UNSUPPORTED','The selected source has no audio track. Add an approved voice/music track in the Advanced editor.')
                continue
            treatments=(['high-pass, gentle EQ and compression'] if project.dialogue_polish else [])+(['conservative FFT noise reduction'] if project.dialogue_noise_reduction else [])+([f'{project.dialogue_hum_hz} Hz hum notch'] if project.dialogue_hum_hz else [])+(['gentle de-essing'] if project.dialogue_deess else [])
            missing=bool(re.search(r'de.?reverb|studio voice|neural speech',inst))
            answer(key, label, 'PARTIALLY_FULFILLED' if missing else 'FULFILLED', (f"Loudness normalised toward {spec['loudness']['integrated']} LUFS with a {spec['true_peak_ceiling']} dBTP ceiling" if project.normalize_audio
                                             else f"True peak limited to {spec['true_peak_ceiling']} dBTP") + ('; applied '+', '.join(treatments)+'.' if treatments else '. Dialogue cleanup is off.')+(' Neural enhancement/de-reverb is not installed.' if missing else ''))
        elif key == 'story':
            answer(key,label,'PARTIALLY_FULFILLED' if semantic.get('used') else 'AWAITING_REVIEW',
                   'Source sentences were classified by the local semantic planner; inspect roles, proposed removals and preservation of meaning.' if semantic.get('used') else 'The semantic planner is unavailable or off. Positional story suggestions are editable, but hook strength and sentence meaning require human review.')
        elif key == 'resolution':
            answer(key, label, 'PARTIALLY_FULFILLED' if request.canvas_mode == 'platform' else 'UNSUPPORTED', canvas_note + ' AI restoration/upscaling is not installed.')
        elif key == 'reframe':
            answer(key, label, 'FULFILLED', f'Canvas {w}×{h} for {platform["label"]}; aspect changes are centre crops, not subject-tracked reframing.')
    if project.guideline_id:
        answer('brand', 'Follow the brand guideline', 'FULFILLED', 'Reviewed guideline applied to titles, logo and call to action where it specifies them.')

    pending = []
    if proposed:
        pending.append(f'{len(proposed)} low-confidence cut(s) await your approval')
    if unresolved:
        pending.append('Caption review required: ' + ', '.join(f'"{n["heard"]}" ({n["confidence"]:.0%})' for n in unresolved))
    for decision in decisions:
        decision.update(reversible=True, brand_reference=dict(guideline_id=project.guideline_id, version=project.guideline_version),
                        platform_reference=dict(id=platform['id'], version=platform['version']))
    report = dict(
        engine='creative-director-and-measured-timeline', ai_text_planner_used=bool(semantic.get('used')),
        semantic_planner=semantic.get('reason') or 'Semantic AI planner unavailable. Deterministic editing remains available: decisions come from measured speech timing, silence, movement and lighting, not from a language model.',
        speech_model_used=bool(transcript), captions_requested=captions,
        source_duration=asset['duration'], edited_duration=edited, duration_removed=round(sum(c['removed_seconds'] for c in cuts), 3),
        cuts=cuts, proposed_cuts=proposed, decisions=decisions, request_fulfilment=fulfilment,
        story_map=semantic.get('story') if semantic.get('used') else story_map(words, asset['duration'], emphasis, face, request.story_roles),
        caption_count=len(cues), caption_draft=bool(cues) and caption_state != 'reviewed', caption_state=caption_state, caption_diagnostic=caption_diagnostic,
        caption_review=dict(required=bool(unresolved), names=names, unresolved=unresolved, corrected=corrected,
                            cues=[dict(start=c['start'], end=c['end'], text=c['text']) for c in cues]),
        zoom_segments=len(framing_changes), punch_in_scale=punch_scale if framing_changes else None, silence_measured=silences is not None,
        style_profile=dict(id=style_id, label=style['label'], summary=style['summary'], basis='INFERRED from the words ' + ', '.join(f'"{x}"' for x in style_words) if style_words
                           else 'USER_SUPPLIED' if request.style != 'auto' else 'PRODUCT DEFAULT (no style words found)',
                           parameters=dict(pause_threshold=pause_threshold, max_emphasis=emphasis_limit, punch_in=punch_scale)),
        platform_profile=dict(id=platform['id'], label=platform['label'], basis=platform['basis'], version=platform['version'], notice=platform['notice'],
                              obstruction=dict(top=platform['top'], bottom=platform['bottom'], left=platform['left'], right=platform['right'])),
        canvas=dict(mode=request.canvas_mode, note=canvas_note), lighting=correction, background=dict(mode=project.background.mode if project.background else 'none',
                                                                                                     matting=matting, mask=context.get('mask')),
        delivery_preset=dict(id=spec['id'], label=spec['label'], note=spec['note']),
        uncertain_words=[w_['word'] for w_ in words if w_.get('probability', 1) < .6 and any(a <= w_['start'] and w_['end'] <= b for a, b in ranges)],
        pending_approvals=pending, publish_readiness='DRAFT' if pending or (cues and caption_state != 'reviewed') else 'READY_FOR_REVIEW',
        face=face, original_dimensions=[asset['width'], asset['height']], output_dimensions=[project.canvas.width, project.canvas.height],
        warnings=list(dict.fromkeys(warnings)))
    from video_layout import solve
    report['caption_timing']=caption_timing
    report['color_pipeline']=project.color_pipeline.model_dump() if project.color_pipeline else dict(regional=False,notice='Shot/global correction only; regional subject correction requires a usable subject matte.')
    report['background']['interpreted_intent']=background_intent
    from video_audio import plan as audio_plan
    report['audio_plan']=audio_plan(project)
    report['reference_style']=dict(profile=context.get('reference'),requested_properties=request.reference_preferences,
        applied_properties=[p for p in request.reference_preferences if reference and p in {'pacing','energy'} or p=='color-mood' and reference.get('color') and project.color_pipeline],
        limitations='Reference caption hierarchy, semantic hook/CTA, and licensed media selection need human review; no reference media/copy is transferred.')
    report['performance']=context.get('performance') or dict(requested=request.performance_tier,selected='basic-cpu')
    report['tracking']=context.get('tracking') or dict(points=[],hands=None,notice='Continuous tracking was not measured.')
    scene=dict(context.get('scene') or {})
    if scene:
        scene['regions']=list(scene.get('regions',[]))+[dict(kind='face',box=p['box'],basis='MEASURED_TEMPORAL_FACE') for p in (context.get('tracking') or {}).get('points',[])]
    report['layout']=solve(project,platform,face,scene or None,rules)
    report['decisions'].append(dict(type='COMPOSITION',start=0,end=edited,purpose='Separate brand, speaker, dialogue and CTA roles',
        reason='Joint arrangement of measured graphic boxes',
        evidence=report['layout']['method'],confidence=.8,requires_review=any(e['requires_review'] for e in report['layout']['elements']),
        reversible=True,source='layout-solver',effect='Measured text boxes jointly placed around protected regions and other active graphics'))
    from video_director import document
    report['cut_policy']=request.cut_policy
    for outcome in report['request_fulfilment']:
        types={'text':{'CAPTIONS','LOWER_THIRD','TITLE','COMPOSITION'},'background':{'BACKGROUND'},'lighting':{'LIGHTING'},'audio':{'AUDIO'},'effects':{'PUNCH_IN','PUNCH_OUT','TRANSITION','BACKGROUND','LIGHTING'},'pacing':{'CUT'}}.get(outcome['request'],set())
        outcomes=[d for d in report['decisions'] if d['type'] in types]
        outcome.update(user_request=request.instruction,interpreted_intent=background_intent['intent'] if outcome['request']=='background' else outcome['label'],
                       operations=[d['type'] for d in outcomes],evidence=[d.get('evidence','') for d in outcomes],limitations=outcome['detail'] if outcome['status']!='FULFILLED' else '')
    report['edit_document']=document(project,report,asset['id'],semantic)
    return project, report


def run(original, request, job):
    from video_qa import master, sha256
    asset = read('assets', request.asset_id)
    if request.parent_asset_id:
        parent = read('assets', request.parent_asset_id)
        if parent.get('source_asset_id') != asset['id']:
            raise ValueError('The previous revision must belong to this source video.')
    if asset['kind'] != 'video':
        raise ValueError('Choose one uploaded video as the source. Logos belong in the logo section.')
    if request.background_asset_id and read('assets', request.background_asset_id)['kind'] not in {'image','video'}:
        raise ValueError('The replacement background must be an approved image or video asset.')
    source = path_for(asset['id'])
    before = sha256(source)
    transcript = {}
    if asset.get('has_audio') and speech_status()['available']:
        job.update(state='running', phase='Analyzing speech')
        transcript = transcribe(asset['id'], request.language, job)
    # Measured facts about the source: silence (to confirm pauses), face framing, loudness, colour tags.
    analysis = None
    silences = None
    face = None
    try:
        from video_analysis import analyze_asset
        job.update(state='running', phase='Analyzing shots and subject')
        analysis = analyze_asset(asset['id'], job=job)
        if asset.get('has_audio'):
            silences = [s.model_dump() for s in analysis.silence_segments]
        face = next((s.face for s in analysis.shots if s.face), None)
    except ValueError:
        pass      # analysis tools unavailable: decisions fall back to word timings and say so
    context = {}
    from video_provider_registry import tier
    context['performance']=tier(request.performance_tier)
    if request.reference_asset_id:
        from video_reference import analyze as analyze_reference
        job.update(state='running',phase='Analyzing reference style statistics')
        context['reference']=analyze_reference(request.reference_asset_id,job)
    from video_layout import analyze_frame
    import video_measure
    context['scene']=analyze_frame(video_measure.frame_at(source,min(2.5,asset['duration']*.3)),face)
    from video_tracking import track as track_subject
    job.update(state='running',phase='Tracking subject framing')
    context['tracking']=track_subject(asset['id'],job,sample_fps=1 if request.performance_tier=='basic-cpu' else 2)
    for point in context['tracking']['points']:
        context['scene']['regions'].append(dict(kind='face',box=point['box'],basis='MEASURED_TEMPORAL_FACE'))
    words = words_from(transcript)
    style_id = request.style if request.style != 'auto' else video_platforms.interpret_style(request.instruction + ' ' + original.creative_context.style)[0]
    style = video_platforms.STYLES[style_id]
    if request.subtle_zooms and words:
        try:
            job.update(state='running', phase='Analyzing movement for emphasis')
            limit = max(s['max_emphasis'] for s in video_platforms.STYLES.values()) if request.plan_variants or 'energy' in request.reference_preferences else style['max_emphasis']
            context['emphasis'] = emphasis_moments(source, words, [(0, asset['duration'])], limit)
        except Exception:
            context['emphasis'] = []
    if request.lighting == 'auto':
        import video_grade
        job.update(state='running', phase='Analyzing lighting')
        try:
            context['lighting'] = video_grade.scene_correction(source, min(asset['duration'] * .4, 3.0), face, style['grade_strength'])
        except ValueError as exc:
            context['lighting'] = dict(status='NOT_MEASURED', reason=str(exc), grade={})
    import video_segmentation
    context['matting'] = {k: v for k, v in video_segmentation.status().items() if k in ('available', 'model', 'reason', 'privacy')}
    from video_director import plan_story
    context['semantic']=plan_story(apply_corrections(words,request.caption_corrections)[0],asset['duration'],
        dict(original.creative_context.model_dump(),instruction=request.instruction),effective_rules(original).model_dump(),
        dict(silences=silences,face=face,emphasis=context.get('emphasis',[])),request.cut_policy,request.semantic_planner,job)
    job.update(state='running', phase='Preparing edit plan')
    project, report = build(original.model_copy(deep=True), asset, request, transcript, silences, face, context)
    if request.plan_variants:
        variants = []
        lighting_by_strength = {style['grade_strength']: context.get('lighting')}
        for key in video_platforms.STYLES:
            variant_request = request.model_copy(update={'style': key, 'dry_run': True, 'plan_variants': False})
            variant_context = dict(context)
            strength = video_platforms.STYLES[key]['grade_strength']
            if request.lighting == 'auto':
                if strength not in lighting_by_strength:
                    lighting_by_strength[strength] = video_grade.scene_correction(source, min(asset['duration'] * .4, 3.0), face, strength)
                variant_context['lighting'] = lighting_by_strength[strength]
            _, variant_report = build(original.model_copy(deep=True), asset, variant_request, transcript, silences, face, variant_context)
            variants.append(dict(style=key, report=variant_report))
        return dict(dry_run=True, variants=variants, edit_report=report, source_asset_id=asset['id'])
    if (project.background or project.color_pipeline and project.color_pipeline.regional) and not request.dry_run:
        job.update(state='running', phase='Generating subject masks')
        mask_rate=project.background.mask_fps if project.background else project.color_pipeline.mask_fps
        _, mask = video_segmentation.subject_mask(asset['id'], job, mask_rate)
        context['mask'] = mask
        mask_path,_=video_segmentation.cached_mask(asset['id'],mask_rate)
        mask_frame=video_measure.frame_at(mask_path,min(2.5,asset['duration']*.3))
        if mask_frame is not None:
            import cv2
            context['scene']=analyze_frame(video_measure.frame_at(source,min(2.5,asset['duration']*.3)),face,cv2.cvtColor(mask_frame,cv2.COLOR_BGR2GRAY))
            if project.color_pipeline and mask['subject_found']:
                job.update(state='running',phase='Verifying subject and background grades')
                at=min(asset['duration']*.4,3.)
                verified,regional_report=video_grade.verify_regional(source,at,face,cv2.cvtColor(video_measure.frame_at(mask_path,at),cv2.COLOR_BGR2GRAY),project.color_pipeline)
                context['regional_pipeline']=verified.model_dump() if verified else None
                context['lighting']=regional_report
        if not mask['subject_found']:
            context['matting'] = dict(context['matting'], available=False, reason='No clear subject was found in this video, so the background was left unchanged.')
        project, report = build(original.model_copy(deep=True), asset, request, transcript, silences, face, context)
    if analysis:
        report['source_analysis'] = dict(technical=analysis.technical.model_dump(), audio=analysis.audio_metrics.model_dump(),
                                         motion_scores=[s.motion_score for s in analysis.shots], face=face, black_intervals=analysis.black_intervals,
                                         frozen_intervals=analysis.frozen_intervals, not_measured=analysis.not_measured, warnings=analysis.warnings)
        report['warnings'] = list(dict.fromkeys(report['warnings'] + analysis.warnings))
    if asset.get('has_audio'):
        job.update(state='running', phase='Measuring dialogue signal')
        import video_measure
        try:
            report['audio_signal'] = video_measure.audio_quality(source, job)
        except ValueError as exc:
            report['audio_signal'] = dict(not_measured=str(exc))
    if request.dry_run:
        from video_preview import stills
        previews=stills(project,report,job) if request.preview_frames else []
        return dict(dry_run=True, edit_report=report, source_asset_id=asset['id'],preview_frames=previews)
    job.update(state='encoding', phase='Rendering the edited timeline', progress={'cuts': len(report['cuts']), 'captions': report['caption_count']})
    saved = save(project, actor='rule_engine', instruction=request.instruction, label='Quick edit · source project preserved')
    result = master(project, job, source_asset=asset, source_sha_before=before, cuts=report['cuts'], captions_requested=report['captions_requested'])
    job.update(state='encoding', phase='Running editorial QA')
    from video_editorial_qa import review
    editorial = review(result, project, asset, report, face, job)
    report['publish_readiness'] = editorial['publish_readiness']
    result = annotate(result, project_id=saved['id'], edit_report=report, editorial_report=editorial, source_asset_id=asset['id'])
    from video_revisions import record_revision
    revision = record_revision(saved['id'], saved, actor='rule_engine', instruction=request.instruction,
                               label='Rendered edit with QA', edit_plan=report, render_asset_id=result['id'],
                               qa_report=result.get('qa_report'), editorial_report=editorial,
                               parent_render_revision_id=parent.get('render_revision_id') if request.parent_asset_id else None)
    result = annotate(result, render_revision_id=revision.id, parent_asset_id=request.parent_asset_id,
                      review_state='DRAFT')
    return result
