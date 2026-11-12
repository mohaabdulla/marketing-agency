"""Asset library, version-bound approvals and local publication packages.

Registered files are copied into a content-addressed store, so an approved version can never
change underneath its approval. Nothing here publishes to an external platform."""
import hashlib
import io
import json
import re
import shutil
import zipfile
import threading
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit, unquote
from .database import repository, uid, timestamp, NotFound, Conflict, ROOT
from .schemas import RecordInput, MODELS
from .production_schemas import APPROVABLE
from .services import service
from .compliance import scan

MAX_ASSET = 256 * 1024 ** 2
TYPES = {  # extension -> (mime, default asset type)
    '.jpg': ('image/jpeg', 'image'), '.jpeg': ('image/jpeg', 'image'), '.png': ('image/png', 'image'), '.webp': ('image/webp', 'image'),
    '.gif': ('image/gif', 'gif'), '.mp4': ('video/mp4', 'video'), '.webm': ('video/webm', 'video'), '.mov': ('video/quicktime', 'video'),
    '.mp3': ('audio/mpeg', 'audio'), '.wav': ('audio/wav', 'audio'), '.m4a': ('audio/mp4', 'audio'), '.ogg': ('audio/ogg', 'audio'),
    '.srt': ('application/x-subrip', 'subtitle'), '.vtt': ('text/vtt', 'subtitle'), '.pdf': ('application/pdf', 'document'),
}
MANAGED = [('/renders/', ROOT / 'output/renders'), ('/uploads/', ROOT / 'output/uploads'), ('/static/assets/', ROOT / 'static/assets')]
STORE_LOCK = threading.RLock()


def serialized_store(function):
    """Serialize files in the supported single-process local server."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with STORE_LOCK:
            return function(*args, **kwargs)
    return wrapped


def store(repo=repository):
    folder = repo.home / 'assets'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def stored_path(stored_name, repo=repository):
    if not re.fullmatch(r'[a-f0-9]{64}\.[a-z0-9]{2,5}', stored_name):
        raise NotFound('Asset file not found')
    path = store(repo) / stored_name
    if not path.is_file():
        raise NotFound('Asset file not found')
    return path


def resolve_source(media_url='', video_asset_id=''):
    """Only application-managed media: a generated/uploaded file URL or a Video Studio asset ID."""
    if video_asset_id:
        import video_assets
        from video_storage import identifier, read
        try:
            item = read('assets', identifier(video_asset_id))
            return video_assets.path_for(video_asset_id), item['name'], '/api/video/media/' + video_asset_id
        except (ValueError, FileNotFoundError, KeyError):
            raise NotFound('Video Studio asset not found')
    parsed = urlsplit(media_url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Use an application media URL such as /renders/name.jpg')
    value = unquote(parsed.path)
    for prefix, directory in MANAGED:
        if value.startswith(prefix):
            name = value[len(prefix):]
            if name and '/' not in name and '\\' not in name and '..' not in name:
                path = (directory / name).resolve()
                if path.parent == directory.resolve() and path.is_file():
                    return path, name, value
    raise NotFound('Source must be an existing generated, uploaded or Video Studio file')


def inspect(path, name):
    """Extension allowlist, signature check, size limit, checksum and basic media facts."""
    ext = Path(name).suffix.lower()
    if ext not in TYPES:
        raise ValueError('Unsupported asset type')
    size = path.stat().st_size
    if not 0 < size <= MAX_ASSET:
        raise ValueError('Asset is empty or exceeds the 256 MB limit')
    with path.open('rb') as handle:
        head = handle.read(32)
    facts = dict(width=None, height=None, duration_seconds=None)
    mime, asset_type = TYPES[ext]
    if ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        from PIL import Image
        try:
            with Image.open(path) as image:
                expected = {'JPEG': {'.jpg', '.jpeg'}, 'PNG': {'.png'}, 'WEBP': {'.webp'}, 'GIF': {'.gif'}}
                if ext not in expected.get(image.format, set()):
                    raise ValueError('Image signature does not match its extension')
                if image.size[0] * image.size[1] > 64_000_000:
                    raise ValueError('Image dimensions exceed limits')
                facts.update(width=image.size[0], height=image.size[1])
                if ext == '.gif' and getattr(image, 'n_frames', 1) > 1:
                    total = 0
                    for index in range(image.n_frames):
                        image.seek(index)
                        total += image.info.get('duration', 0)
                    facts['duration_seconds'] = round(total / 1000, 3)
        except ValueError:
            raise
        except Exception:
            # Not an image at all (for example markup saved with an image extension).
            raise ValueError('File is not a valid image')
    elif ext in {'.mp4', '.mov', '.m4a'} and b'ftyp' not in head:
        raise ValueError('Invalid MP4/MOV signature')
    elif ext == '.webm' and not head.startswith(b'\x1aE\xdf\xa3'):
        raise ValueError('Invalid WebM signature')
    elif ext == '.wav' and not (head.startswith(b'RIFF') and head[8:12] == b'WAVE'):
        raise ValueError('Invalid WAV signature')
    elif ext == '.ogg' and not head.startswith(b'OggS'):
        raise ValueError('Invalid OGG signature')
    elif ext == '.pdf' and not head.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF signature')
    elif ext in {'.srt', '.vtt'}:
        text = path.read_bytes()[:200000].decode('utf-8-sig', errors='strict')
        if ext == '.vtt' and not text.lstrip().startswith('WEBVTT'):
            raise ValueError('Invalid WebVTT file')
        if ext == '.srt' and not re.search(r'\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}', text):
            raise ValueError('Invalid SRT file')
    if ext in {'.mp4', '.mov', '.webm', '.mp3', '.wav', '.m4a', '.ogg'}:
        try:
            from video_ffmpeg import probe
            meta = probe(path)
            facts.update(width=meta.get('width') or None, height=meta.get('height') or None,
                         duration_seconds=round(meta['duration'], 3) if meta.get('duration') else None)
        except Exception:
            pass      # FFprobe is optional here; the file is still checksummed and stored.
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return dict(sha256=digest.hexdigest(), size=size, mime=mime, ext=ext, default_type=asset_type, **facts)


def _file_fields(media_url, video_asset_id, repo):
    path, name, url = resolve_source(media_url, video_asset_id)
    facts = inspect(path, name)
    stored_name = facts['sha256'] + facts['ext']
    target = store(repo) / stored_name
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.part')
        shutil.copyfile(path, temporary)
        temporary.replace(target)
    return dict(sha256=facts['sha256'], size=facts['size'], mime=facts['mime'], stored_name=stored_name, original_url=url[:250],
                width=facts['width'], height=facts['height'], duration_seconds=facts['duration_seconds']), facts['default_type'], name


@serialized_store
def register(client_id, name='', media_url='', video_asset_id='', project_id=None, campaign_id=None, metadata=None,
             agency=service, repo=repository):
    fields, default_type, filename = _file_fields(media_url, video_asset_id, repo)
    data = dict(metadata or {})
    data.setdefault('asset_type', default_type)
    data.update(fields)
    return agency.save(client_id, 'assets', RecordInput(name=(name or filename)[:160], project_id=project_id,
                                                        campaign_id=campaign_id, data=data))


@serialized_store
def new_version(client_id, asset_id, expected_version, media_url='', video_asset_id='', agency=service, repo=repository):
    """Same asset, new file: the previous file stays in the store and in the revision history."""
    asset = agency.get(client_id, asset_id, 'assets')
    fields, _, _ = _file_fields(media_url, video_asset_id, repo)
    if fields['sha256'] == asset['data']['sha256']:
        raise Conflict('This file is identical to the current version')
    body = RecordInput(name=asset['name'], project_id=asset['project_id'], campaign_id=asset['campaign_id'],
                       data=dict(asset['data'], **fields))
    return agency.save(client_id, 'assets', body, asset_id, expected_version, file_change=True)


def version_file(client_id, asset_id, version=None, repo=repository):
    """(path, download name, mime) of a specific saved version of an asset."""
    with repo.connection() as db:
        asset = repo.record(db, client_id, asset_id, 'assets', include_archived=True)
        data = asset['data']
        if version is not None and version != asset['version']:
            row = db.execute('SELECT snapshot FROM revisions WHERE resource_id=? AND client_id=? AND version=?',
                             (asset_id, client_id, version)).fetchone()
            if not row:
                raise NotFound('Asset version not found')
            data = json.loads(row['snapshot'])['data']
    ext = data['stored_name'].rsplit('.', 1)[1]
    safe = re.sub(r'[^\w.-]+', '-', asset['name']).strip('-.')[:80] or 'asset'
    return stored_path(data['stored_name'], repo), f'{safe}-v{version or asset["version"]}.{ext}', data['mime']


# ---------------------------------------------------------------- approvals
def request_approval(client_id, target_id, reviewer, due_date=None, note='', agency=service):
    target = agency.get(client_id, target_id)
    if target['kind'] not in APPROVABLE:
        raise ValueError('This record type cannot be sent for approval')
    if target['archived']:
        raise Conflict('Restore this record before requesting approval')
    data = dict(target_id=target_id, target_kind=target['kind'], target_name=target['name'][:250], target_version=target['version'],
                target_sha256=target['data'].get('sha256') if target['kind'] == 'assets' else None,
                reviewer=reviewer, due_date=due_date, request_note=note)
    return agency.save(client_id, 'approvals', RecordInput(
        name=f'{target["name"][:120]} · v{target["version"]}', project_id=None, campaign_id=target['campaign_id'], data=data))


def _update_approval(client_id, approval, data, action, agency, repo, details=None):
    body = RecordInput(name=approval['name'], project_id=None, campaign_id=approval['campaign_id'], data=data)
    saved = agency.save(client_id, 'approvals', body, approval['id'], approval['version'])
    with repo.connection(write=True) as db:
        repo.audit(db, client_id, approval['id'], action, saved['version'], details or {})
    return saved


def comment(client_id, approval_id, expected_version, author, text, timecode_seconds=None, agency=service, repo=repository):
    approval = agency.get(client_id, approval_id, 'approvals')
    if approval['version'] != expected_version:
        raise Conflict('Approval changed elsewhere; reload before commenting')
    entry = dict(author=author, at=timestamp(), text=text, timecode_seconds=timecode_seconds, decision='')
    return _update_approval(client_id, approval, dict(approval['data'], comments=approval['data']['comments'] + [entry]),
                            'approval.commented', agency, repo)


def decide(client_id, approval_id, expected_version, decision, reviewer, text='', agency=service, repo=repository):
    """Approve, reject or request changes on exactly the version that was sent for review."""
    approval = agency.get(client_id, approval_id, 'approvals')
    data = approval['data']
    if approval['version'] != expected_version:
        raise Conflict('Approval changed elsewhere; reload before deciding')
    if data['state'] not in {'review-requested', 'changes-requested'}:
        raise Conflict('This request is already ' + data['state'] + '; send the current version for a new review')
    target = agency.get(client_id, data['target_id'])
    if target['version'] != data['target_version'] or (data['target_sha256'] and target['data'].get('sha256') != data['target_sha256']):
        raise Conflict('The record changed after this request; it is superseded. Request approval of the current version')
    if decision != 'approved' and not text.strip():
        raise ValueError('Explain what should change or why it is rejected')
    entry = dict(author=reviewer, at=timestamp(), text=text, timecode_seconds=None, decision=decision)
    saved = _update_approval(client_id, approval, dict(data, state=decision, decided_at=entry['at'], comments=data['comments'] + [entry]),
                             'approval.' + decision, agency, repo,
                             dict(target_id=data['target_id'], target_version=data['target_version'], reviewer=reviewer))
    created = production_tasks(client_id, target, agency) if decision == 'approved' and target['kind'] == 'briefs' else []
    return dict(approval=saved, workflow=dict(rule='brief approved → production tasks', tasks_created=[t['name'] for t in created]))


def production_tasks(client_id, brief, agency=service):
    """Deterministic workflow rule: an approved brief opens one task per planned deliverable (once)."""
    campaign_id = brief['campaign_id']
    deliverables = agency.list(client_id, 'deliverables', campaign_id=campaign_id, limit=100)['items']
    existing = {t['name'] for t in agency.list(client_id, 'tasks', campaign_id=campaign_id, limit=100)['items']}
    created = []
    for item in deliverables:
        full = agency.get(client_id, item['id'], 'deliverables')
        name = ('Produce: ' + full['name'])[:160]
        if full['data']['state'] == 'cancelled' or name in existing:
            continue
        created.append(agency.save(client_id, 'tasks', RecordInput(name=name, campaign_id=campaign_id, data=dict(
            origin='workflow-rule', due_date=full['data']['due_date'], owner=full['data']['owner'],
            notes=f'Opened automatically when brief "{brief["name"]}" v{brief["version"]} was approved.'))))
    return created


def approval_state(db, repo, client_id, record):
    """Current approval of a record's present version: approved / pending / none."""
    rows = db.execute("SELECT r.payload FROM records r JOIN links l ON l.source_id=r.id AND l.client_id=r.client_id "
                      "WHERE l.target_id=? AND l.relation='target_id' AND r.client_id=? AND r.kind='approvals' AND r.archived=0",
                      (record['id'], client_id)).fetchall()
    states = [json.loads(r['payload']) for r in rows]
    current = [s for s in states if s['target_version'] == record['version']
               and (not s['target_sha256'] or s['target_sha256'] == record['data'].get('sha256'))]
    if any(s['state'] == 'approved' for s in current):
        return 'approved'
    if any(s['state'] in {'review-requested', 'changes-requested'} for s in current):
        return 'in-review'
    if any(s['state'] == 'rejected' for s in current):
        return 'rejected'
    return 'not-approved'


def review_queue(client_id, state=None, limit=50, offset=0, agency=service):
    result = agency.list(client_id, 'approvals', limit=limit, offset=offset)
    items = [agency.get(client_id, item['id'], 'approvals') for item in result['items']]
    if state:
        items = [i for i in items if i['data']['state'] == state]
    return dict(items=items, total=result['total'], limit=limit, offset=offset)


# ---------------------------------------------------------------- publication package
def _safe_csv_cell(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def publication_package(client_id, entry_id, draft=True, agency=service, repo=repository):
    """ZIP with final media, caption, alt text, hashtags, disclosure, metadata and a posting checklist.

    A final (non-draft) package requires every linked copy and asset to be approved at its
    current version and free of blocking check flags. Publishing itself stays a human action."""
    entry = agency.get(client_id, entry_id, 'calendar')
    data = entry['data']
    campaign = agency.get(client_id, entry['campaign_id'], 'campaigns')
    copy = agency.get(client_id, data['copy_id'], 'copy') if data['copy_id'] else None
    assets = [agency.get(client_id, key, 'assets') for key in data['asset_ids']]
    issues, approvals, rights = [], {}, {}
    with repo.connection() as db:
        for record in ([copy] if copy else []) + assets:
            approvals[record['id']] = approval_state(db, repo, client_id, record)
            if approvals[record['id']] != 'approved':
                issues.append(f'{record["kind"]} "{record["name"]}" v{record["version"]} is {approvals[record["id"]]}')
    for asset in assets:
        license_id = asset['data']['license_id']
        license_record = agency.get(client_id, license_id, 'licenses') if license_id else None
        rights[asset['id']] = (license_record['effective_status'] + ' · ' + license_record['data']['license_type']) if license_record else 'unknown'
        if not license_record or license_record['data']['license_type'] == 'unknown':
            issues.append(f'Usage rights are not recorded for asset "{asset["name"]}"')
        elif license_record['effective_status'] == 'expired':
            issues.append(f'The licence for asset "{asset["name"]}" has expired')
    checks = dict(flags=[], export_state='checks-passed')
    if copy:
        from .content import copy_checks
        c = copy['data']
        checks = copy_checks(client_id, entry['campaign_id'], c['format'], c['text'], c['headline'], c['cta'], c['hashtags'],
                             c['language'], c['claim_ids'], exclude_id=copy['id'], agency=agency)
        issues += ['Copy check: ' + f['message'] for f in checks['flags'] if f['severity'] == 'block']
    else:
        issues.append('No copy is linked to this calendar entry')
    if not assets:
        issues.append('No media asset is linked to this calendar entry')
    if issues and not draft:
        raise Conflict('Not ready for a final package: ' + '; '.join(issues))
    path = repo.home / 'exports' / (uid() + '.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as bundle:
        files = []
        for index, asset in enumerate(assets, 1):
            ext = asset['data']['stored_name'].rsplit('.', 1)[1]
            name = f'media/{index:02d}-{re.sub(r"[^\w-]+", "-", asset["name"]).strip("-")[:60] or "asset"}.{ext}'
            bundle.write(stored_path(asset['data']['stored_name'], repo), name)
            files.append(dict(file=name, asset_id=asset['id'], version=asset['version'], sha256=asset['data']['sha256'],
                              approval=approvals[asset['id']], rights=rights[asset['id']]))
        first_image = next((a for a in assets if a['data']['mime'].startswith('image/')), None)
        if first_image:
            from PIL import Image
            with Image.open(stored_path(first_image['data']['stored_name'], repo)) as image:
                image = image.convert('RGB')
                image.thumbnail((640, 640))
                buffer = io.BytesIO()
                image.save(buffer, 'JPEG', quality=88)
            bundle.writestr('thumbnail.jpg', buffer.getvalue())
        c = copy['data'] if copy else dict(text='', headline='', cta='', hashtags=[])
        bundle.writestr('caption.txt', '\n\n'.join(x for x in (c['text'], c['cta']) if x))
        bundle.writestr('title.txt', data['title'] or c['headline'])
        bundle.writestr('alt-text.txt', data['alt_text'])
        bundle.writestr('hashtags.txt', ' '.join(c['hashtags']))
        bundle.writestr('disclosure.txt', data['disclosure'])
        when = f'{data["scheduled_date"]} {data["scheduled_time"]} ({data["timezone"]})'
        checklist = [('DRAFT FOR REVIEW — NOT CLEARED FOR PUBLICATION\n' if draft and issues else '') +
                     f'Posting checklist · {entry["name"]}', f'Channel: {data["channel"]}   Account: {data["target_account"] or "(choose when posting)"}',
                     f'Planned time: {when}', '',
                     '[ ] Open issues below are resolved' if issues else '[x] Linked copy and assets are approved at these exact versions',
                     *('    - ' + issue for issue in issues),
                     '[ ] Media files match the checksums in metadata.json',
                     '[ ] Caption, title and hashtags pasted exactly as provided',
                     '[ ] Alt text added' if data['alt_text'] else '[ ] Alt text is EMPTY — write one before posting',
                     '[ ] Disclosure included: ' + data['disclosure'] if data['disclosure'] else '[ ] Confirm no disclosure (paid partnership, sponsorship) is required',
                     '[ ] Posted by a person with authority on the account; this package does not publish anything',
                     '[ ] After posting, record the post link in the calendar entry and mark it published']
        bundle.writestr('posting-checklist.txt', '\n'.join(checklist))
        bundle.writestr('metadata.json', json.dumps(dict(
            schema_version=1, exported_at=timestamp(), draft=bool(draft), cleared=not issues, open_issues=issues,
            publication_authorized=False, publishes_externally=False,
            client_id=client_id, campaign=dict(id=campaign['id'], name=campaign['name']),
            calendar_entry=dict(id=entry['id'], version=entry['version'], name=entry['name'], channel=data['channel'],
                                target_account=data['target_account'], scheduled=when),
            copy=dict(id=copy['id'], version=copy['version'], format=copy['data']['format'], language=copy['data']['language'],
                      approval=approvals[copy['id']]) if copy else None,
            media=files, copy_checks=checks['flags']), ensure_ascii=False, indent=2))
    with repo.connection(write=True) as db:
        repo.audit(db, client_id, entry_id, 'calendar.package-exported', entry['version'], dict(draft=bool(draft), cleared=not issues))
    if not draft and data['publish_status'] == 'planned':
        agency.save(client_id, 'calendar', RecordInput(name=entry['name'], campaign_id=entry['campaign_id'],
                                                       data=dict(data, publish_status='package-exported')), entry_id, entry['version'])
    return path, not issues
