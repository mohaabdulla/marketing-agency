"""Content production: concept matrices, copy checks, scripts to storyboards, and a real
Video Studio project from a storyboard. Deterministic; no model is called."""
import difflib
import html
import itertools
import json
import re
import zipfile
from .database import repository, uid, timestamp, Conflict
from .schemas import RecordInput
from .services import service
from .compliance import scan
from .production import channel_specs, script_estimate

MATRIX_AXES = ('hook_type', 'benefit', 'pain_point', 'awareness_stage', 'appeal', 'visual_territory', 'offer', 'cta', 'channel')
MATRIX_LIMIT = 24
PLACEHOLDER = re.compile(r'\[[^\]\n]{1,40}\]|\{\{[^}\n]{1,40}\}\}|lorem ipsum|\bTBD\b|\bTODO\b|\bXXX+\b|<[a-z_ ]{2,30}>', re.IGNORECASE)
URL = re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)
VALID_URL = re.compile(r'^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#]\S*)?$')


def concept_matrix(client_id, campaign_id, axes, brief_id=None, audience_id=None, agency=service):
    """Cross the operator's own options into proposed concepts (no invented rationale or copy)."""
    axes = {k: [v.strip() for v in values if v.strip()] for k, values in axes.items() if k in MATRIX_AXES}
    axes = {k: list(dict.fromkeys(v)) for k, v in axes.items() if v}
    if not axes:
        raise ValueError('Enter options for at least one axis, for example two hooks and two visuals')
    combos = list(itertools.product(*axes.values()))
    if len(combos) > MATRIX_LIMIT:
        raise ValueError(f'This matrix has {len(combos)} combinations; reduce it to {MATRIX_LIMIT} or fewer so each can be reviewed')
    campaign = agency.get(client_id, campaign_id, 'campaigns')
    created = []
    for index, combo in enumerate(combos, 1):
        values = dict(zip(axes, combo))
        data = dict(brief_id=brief_id, audience_id=audience_id, channels=[values.pop('channel')] if 'channel' in values else [], **values)
        label = ' · '.join(str(v) for v in combo)[:120]
        created.append(agency.save(client_id, 'concepts', RecordInput(
            name=f'{campaign["name"][:30]} · concept {index}: {label}'[:160], campaign_id=campaign_id, data=data)))
    return dict(created=created, combinations=len(combos), axes=list(axes))


def copy_checks(client_id, campaign_id, fmt, text, headline='', cta='', hashtags=(), language='en', claim_ids=(),
                exclude_id=None, agency=service):
    """Deterministic review flags for one copy variant. Flags, not scores; a person still decides."""
    specs = channel_specs()
    spec = specs['formats'].get(fmt)
    if not spec:
        raise ValueError('Unknown copy format')
    campaign = agency.get(client_id, campaign_id, 'campaigns')
    result = scan(client_id, '\n'.join(x for x in (headline, text) if x), list(claim_ids), campaign['data']['brand_id'],
                  cta if fmt != 'cta' else text, language)
    flags = result['flags']
    non_latin = bool(re.search(r'[^\x00-\x7f]', text))
    limit = spec.get('max_chars_non_latin', spec['max_chars']) if non_latin else spec['max_chars']
    if len(text) > limit:
        hard = spec['limit_type'] == 'hard'
        flags.append(dict(code='length', severity='block' if hard else 'review',
                          message=f'{spec["label"]}: {len(text)} characters, {"limit" if hard else "recommended maximum"} {limit}'))
    tags = [t for t in hashtags if t.strip()] or re.findall(r'(?<!\w)#\w+', text)
    if spec.get('max_hashtags') is not None and len(tags) > spec['max_hashtags']:
        flags.append(dict(code='hashtags', severity='block' if spec.get('hashtag_limit_type') == 'hard' else 'review',
                          message=f'{len(tags)} hashtags; {spec["label"]} allows or recommends {spec["max_hashtags"]}'))
    for match in PLACEHOLDER.finditer(headline + '\n' + text + '\n' + cta):
        flags.append(dict(code='placeholder', severity='block', message='Placeholder text left in copy: ' + match.group()[:60]))
    for link in URL.findall(text + ' ' + cta):
        if not VALID_URL.match(link.rstrip('.,;:!?)')):
            flags.append(dict(code='link_format', severity='review', message='Check this link: ' + link[:120]))
    siblings = agency.list(client_id, 'copy', campaign_id=campaign_id, limit=100)['items']
    normal = ' '.join(text.casefold().split())
    for other in siblings:
        if other['id'] == exclude_id or other['data']['language'] != language:
            continue
        ratio = difflib.SequenceMatcher(None, normal, ' '.join(other['data']['text'].casefold().split())).ratio()
        if ratio >= 0.9:
            flags.append(dict(code='duplicate', severity='review', record_id=other['id'],
                              message=f'Nearly identical to "{other["name"]}" ({ratio:.0%} similar)'))
        elif ratio >= 0.75:
            flags.append(dict(code='similar', severity='review', record_id=other['id'],
                              message=f'Similar to "{other["name"]}" ({ratio:.0%}); make sure the variants test something different'))
    return dict(flags=flags, characters=len(text), limit=limit, limit_type=spec['limit_type'], format=spec['label'],
                export_state='review-required' if flags else 'checks-passed', limits_notice=specs['notice'],
                scope='Deterministic checks only. Tone, accuracy and cultural fit need a human reviewer.')


def storyboard_from_script(client_id, script_id, agency=service):
    """One shot per scene, carrying the script's own words; prompts are left for the operator."""
    script = agency.get(client_id, script_id, 'scripts')
    if not script['data']['scenes']:
        raise ValueError('Add at least one scene to the script before creating a storyboard')
    estimate = {row['scene']: row for row in script_estimate(script['data'])['scenes']}
    board = agency.save(client_id, 'storyboards', RecordInput(
        name=(script['name'] + ' · storyboard')[:160], campaign_id=script['campaign_id'],
        data=dict(script_id=script_id, notes=f'Created from script v{script["version"]}.')))
    shots = []
    for index, scene in enumerate(script['data']['scenes'], 1):
        shots.append(agency.save(client_id, 'shots', RecordInput(
            name=f'Shot {index:02d}' + (': ' + scene['heading'] if scene['heading'] else ''),
            data=dict(storyboard_id=board['id'], sequence=index,
                      duration_seconds=min(300, max(0.5, estimate[index]['planned_seconds'] or 4)),
                      description=scene['visual'], voiceover=scene['narration'], dialogue=scene['dialogue'],
                      on_screen_text=scene['on_screen_text']))))
    return dict(storyboard=board, shots=shots)


def storyboard_shots(client_id, storyboard_id, agency=service, repo=repository):
    board = agency.get(client_id, storyboard_id, 'storyboards')
    with repo.connection() as db:
        rows = db.execute("SELECT r.* FROM records r JOIN links l ON l.source_id=r.id AND l.client_id=r.client_id "
                          "WHERE l.target_id=? AND l.relation='storyboard_id' AND r.client_id=? AND r.kind='shots' AND r.archived=0",
                          (storyboard_id, client_id)).fetchall()
    shots = sorted((repo.unpack_record(r) for r in rows), key=lambda s: (s['data']['sequence'], s['created_at']))
    return board, shots


def _slate(shot, size, path):
    """A plain animatic card for a shot that has no picture yet."""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    width, height = size
    image = Image.new('RGB', size, (16, 26, 44))
    draw = ImageDraw.Draw(image)
    try:
        from visual_engine import get_font
        big, small = get_font('Inter', max(28, width // 16), weight='bold'), get_font('Inter', max(18, width // 34))
    except Exception:
        big = small = ImageFont.load_default()
    draw.text((width * 0.07, height * 0.12), f'SHOT {shot["data"]["sequence"]:02d}', font=big, fill=(101, 228, 242))
    draw.text((width * 0.07, height * 0.12 + big.size * 1.6), 'Animatic slate · no image selected yet', font=small, fill=(157, 177, 206))
    body = shot['data']['description'] or shot['name']
    y = height * 0.4
    for line in textwrap.wrap(body, 34)[:7]:
        draw.text((width * 0.07, y), line, font=small, fill=(227, 236, 250))
        y += small.size * 1.5
    image.save(path, 'PNG')


def video_project_from_storyboard(client_id, storyboard_id, agency=service, repo=repository):
    """Create a Video Studio project: shots in order, their stills or clips, on-screen text as titles."""
    from .assets import stored_path
    import video_assets
    import video_editor
    import video_projects
    board, shots = storyboard_shots(client_id, storyboard_id, agency, repo)
    if not shots:
        raise ValueError('This storyboard has no shots yet')
    if len(shots) > 30:
        raise ValueError('Video Studio projects are limited to 60 clips; split this storyboard (30 shots at most)')
    canvas = {'portrait-9x16': (720, 1280), 'square-1x1': (1080, 1080), 'landscape-16x9': (1280, 720), 'feed-4x5': (1080, 1350)}[board['data']['aspect']]
    work = repo.home / 'work' / uid()
    work.mkdir(parents=True)
    clips, start, slates = [], 0.0, 0
    try:
        for shot in shots:
            data = shot['data']
            asset_id = data['video_asset_id'] or data['image_asset_id']
            duration = float(data['duration_seconds'])
            if asset_id:
                asset = agency.get(client_id, asset_id, 'assets')
                media = video_assets.ingest(stored_path(asset['data']['stored_name'], repo), asset['name'] + '.' + asset['data']['stored_name'].rsplit('.', 1)[1])
                if media['duration']:
                    duration = min(duration, media['duration'])
            else:
                slate = work / f'shot-{data["sequence"]:02d}.png'
                _slate(shot, canvas, slate)
                media = video_assets.ingest(slate, slate.name)
                slates += 1
            clips.append(video_projects.Clip(asset_id=media['id'], kind='video', start=start, duration=duration))
            if data['on_screen_text'].strip():
                clips.append(video_projects.Clip(kind='title', text=data['on_screen_text'][:500], start=start,
                                                 duration=min(duration, 300), y=0.82,
                                                 font='arabic' if re.search(r'[؀-ۿ]', data['on_screen_text']) else 'sans'))
            start += duration
        project = video_projects.Project(name=(board['name'] + ' · animatic')[:120],
                                         canvas=video_projects.Canvas(width=canvas[0], height=canvas[1]), clips=clips)
        video_editor.validate_sources(project)
        saved = video_projects.save(project)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    with repo.connection(write=True) as db:
        repo.audit(db, client_id, storyboard_id, 'storyboard.video-project-created', board['version'],
                   dict(video_project_id=saved['id'], shots=len(shots), slates=slates))
    return dict(video_project_id=saved['id'], name=saved['name'], shots=len(shots), slates=slates,
                duration_seconds=round(start, 2),
                note='Open it in Video Studio → Projects. Storyboard records and registered assets are unchanged; '
                     'shots without a picture use a plain animatic slate.')


def _clock(seconds, comma):
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}{"," if comma else "."}{millis:03d}'


def storyboard_captions(client_id, storyboard_id, fmt='srt', agency=service, repo=repository):
    """SRT or WebVTT from the shots' voiceover (else dialogue) text.

    Timing is planned, not measured: each shot's text is split into cues of at most two
    42-character lines and shares the shot's duration by word count. Re-time against the final
    audio before publishing; there is no speech recognition here."""
    import textwrap
    board, shots = storyboard_shots(client_id, storyboard_id, agency, repo)
    cues, start = [], 0.0
    for shot in shots:
        duration = float(shot['data']['duration_seconds'])
        text = ' '.join((shot['data']['voiceover'] or shot['data']['dialogue']).split())
        if text:
            lines = textwrap.wrap(text, 42)
            blocks = [lines[i:i + 2] for i in range(0, len(lines), 2)]
            words = [max(1, len(' '.join(b).split())) for b in blocks]
            cursor = start
            for block, count in zip(blocks, words):
                length = duration * count / sum(words)
                cues.append((cursor, cursor + length, '\n'.join(block)))
                cursor += length
        start += duration
    if not cues:
        raise ValueError('No voiceover or dialogue text in this storyboard to caption')
    if fmt == 'vtt':
        body = 'WEBVTT\n\n' + '\n\n'.join(f'{_clock(a, False)} --> {_clock(b, False)}\n{t}' for a, b, t in cues) + '\n'
    else:
        body = '\n\n'.join(f'{i}\n{_clock(a, True)} --> {_clock(b, True)}\n{t}' for i, (a, b, t) in enumerate(cues, 1)) + '\n'
    return body, len(cues), round(start, 3)


def storyboard_export(client_id, storyboard_id, agency=service, repo=repository):
    """Self-contained HTML shot list with the selected stills, zipped."""
    from .assets import stored_path
    board, shots = storyboard_shots(client_id, storyboard_id, agency, repo)
    path = repo.home / 'exports' / (uid() + '.zip')
    rows, total = [], 0.0
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for shot in shots:
            d = shot['data']
            total += d['duration_seconds']
            picture = ''
            if d['image_asset_id']:
                asset = agency.get(client_id, d['image_asset_id'], 'assets')
                name = f'images/shot-{d["sequence"]:02d}.{asset["data"]["stored_name"].rsplit(".", 1)[1]}'
                bundle.write(stored_path(asset['data']['stored_name'], repo), name)
                picture = f'<img src="{name}" alt="Shot {d["sequence"]} reference">'
            cells = ''.join(f'<p><b>{label}</b> {html.escape(str(d[key]))}</p>' for key, label in (
                ('description', 'Picture'), ('framing', 'Framing'), ('camera_angle', 'Angle'), ('camera_motion', 'Motion'),
                ('action', 'Action'), ('voiceover', 'Voiceover'), ('dialogue', 'Dialogue'), ('on_screen_text', 'On-screen text'),
                ('transition', 'Transition'), ('continuity', 'Continuity')) if d[key])
            rows.append(f'<section><h2>{html.escape(shot["name"])} · {d["duration_seconds"]:g}s</h2>{picture}<div dir="auto">{cells}</div></section>')
        page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{html.escape(board["name"])}</title><style>body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#16202e}}'
                'section{border:1px solid #cfd8e3;border-radius:10px;padding:16px;margin:16px 0;break-inside:avoid}img{max-width:260px;float:right;margin:0 0 10px 16px;border-radius:6px}'
                'h2{font-size:17px;margin:0 0 8px}p{margin:4px 0}@media print{body{margin:0}}</style>'
                f'<h1>{html.escape(board["name"])}</h1><p>{len(shots)} shots · {total:g} seconds planned · storyboard v{board["version"]} · exported {timestamp()[:10]}</p>'
                + ''.join(rows) + '</html>')
        bundle.writestr('storyboard.html', page)
        bundle.writestr('storyboard.json', json.dumps(dict(storyboard=board, shots=shots), ensure_ascii=False, indent=2))
    return path
