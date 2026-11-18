"""Phrase-based cue selection and constrained word-aligned timing, before rasterization."""
import math
import re

# Netflix timed-text limits: at least 5/6 s and at most 7 s per event, 20 characters per second for
# adult English, and a 2-frame gap between consecutive events (0.083 s at 24 fps).
PROFILES = {
    'en': dict(max_cps=20., min_duration=5 / 6, max_duration=7., max_lag=.75, max_lead=.18),
    'ar': dict(max_cps=17., min_duration=1., max_duration=7., max_lag=.85, max_lead=.18),
}
GAP = 2 / 24


def optimize(words, duration, language='en', max_cps=None, shot_boundaries=(), fits=None):
    """Every word is retained once, with its actual timings/confidence. Timing changes may
    borrow adjacent silence but cannot cover neighbouring speech or drift arbitrarily.
    Impossible density is exposed as review work, never solved by dropping words.
    """
    spec = dict(PROFILES['ar' if language.startswith('ar') else 'en'])
    if max_cps is not None:
        spec['max_cps'] = max_cps
    ordered = [dict(w, word=str(w.get('word', w.get('text', ''))).strip()) for w in words]
    ordered = [w for w in ordered if w['word'] and 0 <= w['start'] < w['end'] <= duration + .04]
    n = len(ordered)
    if not n:
        return [], dict(profile=spec, changes=[], unresolved=[], words_retained=0)
    if n > 1500:
        raise ValueError('Caption optimization supports at most 1500 words per edit')
    costs, previous = [math.inf] * (n + 1), [None] * (n + 1)
    costs[0] = 0.
    for end in range(1, n + 1):
        for start in range(max(0, end - 16), end):
            group = ordered[start:end]
            text = ' '.join(w['word'] for w in group)
            spoken = group[-1]['end'] - group[0]['start']
            if spoken > spec['max_duration'] or len(text) > 150:
                continue
            if any(b['start']-a['end']>.6 for a,b in zip(group,group[1:])):
                continue # a long pause is a new caption event, not free reading time inside one phrase
            if any(group[0]['start'] + .1 < cut < group[-1]['end'] - .1 for cut in shot_boundaries):
                continue
            available_end = min(duration, group[-1]['end'] + spec['max_lag'], ordered[end]['start'] - GAP if end < n else duration)
            available_start = max(0., group[0]['start'] - spec['max_lead'], ordered[start - 1]['end'] + GAP if start else 0.)
            available = max(.05, available_end - available_start)
            needed = max(spec['min_duration'], len(text) / spec['max_cps']+.015)
            excess = max(0., needed - available)
            boundary = 0. if re.search(r'[.!?؟]$', group[-1]['word']) else .35 if re.search(r'[,;:،]$', group[-1]['word']) else 1.3
            if end < n and ordered[end]['start'] - group[-1]['end'] > .3:
                boundary *= .2
            # Keep names/phrases together; orphan one-word cues are expensive.
            cost = costs[start] + 1.5 + boundary + excess ** 2 * 25 + (2.5 if len(group) == 1 else 0.)
            for position,part in enumerate(group[:-1]):
                bare=re.sub(r'[^\w]','',part['word']).casefold()
                if re.search(r'[.!?؟]$',part['word']) and bare not in {'mr','mrs','ms','dr','prof'} and part['end']-group[0]['start']>.7:
                    cost+=8 # keep a complete sentence separate; a fleeting "Yes." may join its following phrase
            if fits and not fits(text):
                cost += 40
            if cost < costs[end]:
                costs[end], previous[end] = cost, start
    if previous[n] is None:
        # A single pathological word still receives a cue and a review flag.
        groups = [(i, i + 1) for i in range(n)]
    else:
        groups, cursor = [], n
        while cursor:
            start = previous[cursor]
            groups.append((start, cursor)); cursor = start
        groups.reverse()
    cues, changes, unresolved = [], [], []
    for index, (a, b) in enumerate(groups):
        group = ordered[a:b]
        text = ' '.join(w['word'] for w in group)
        start, spoken_end = group[0]['start'], group[-1]['end']
        earliest = max(0., start - spec['max_lead'], cues[-1]['end'] + GAP if cues else 0.)
        latest = min(duration, spoken_end + spec['max_lag'], ordered[b]['start'] - GAP if b < n else duration)
        need = max(spec['min_duration'], len(text) / spec['max_cps']+.015)
        cue_start = max(earliest, min(start, latest - need))
        cue_end = min(latest, max(spoken_end, cue_start + need))
        # Conflicting timestamps must not generate negative cue durations.
        cue_start = min(cue_start, max(0., cue_end - .05))
        cue = dict(start=round(cue_start, 3), end=round(cue_end, 3), text=text,
                   words=[dict(w) for w in group], spoken_start=start, spoken_end=spoken_end)
        cue['cps'] = round(len(text) / max(.05, cue['end'] - cue['start']), 2)
        if abs(cue_start - start) > .01 or abs(cue_end - spoken_end) > .01:
            changes.append(dict(cue=index, reason='Borrowed adjacent silence to meet reading time', spoken=[start, spoken_end], display=[cue['start'], cue['end']]))
        if cue['cps'] > spec['max_cps'] + .1:
            unresolved.append(dict(cue=index, reason='Speech is too dense for the reading target within allowed synchronization limits', cps=cue['cps']))
        if fits and not fits(text):
            unresolved.append(dict(cue=index, reason='Text needs layout/font adjustment or manual phrase editing; no words were removed'))
        cues.append(cue)
    return cues, dict(profile=spec, changes=changes, unresolved=unresolved, words_retained=n,
                      method='Dynamic phrase grouping over word timestamps, bounded silence borrowing, no transcript rewriting')


def map_words(words, ranges):
    mapped, offset = [], 0.
    for start, end in ranges:
        for word in words:
            if word['start'] >= start - .02 and word['end'] <= end + .02:
                mapped.append(dict(word, start=max(offset, offset + word['start'] - start), end=offset + min(end, word['end']) - start))
        offset += end - start
    return mapped, offset
