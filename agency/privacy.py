"""Client-specific data export and explicit erasure. Never run automatically."""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from .database import repository, Conflict, timestamp, uid, packed
from .assets import serialized_store

LIMIT = 128 * 1024 ** 2


def _asset_names(records, revisions):
    names = set()
    for record in records:
        if record['kind'] == 'assets':
            names.add(json.loads(record['payload'])['stored_name'])
    for revision in revisions:
        value = json.loads(revision['snapshot'])
        if value.get('kind') == 'assets' and value.get('data', {}).get('stored_name'):
            names.add(value['data']['stored_name'])
    return names


def review_token(db, client):
    audit = db.execute('SELECT coalesce(max(id),0) FROM audit WHERE client_id=?', (client,)).fetchone()[0]
    documents = db.execute('SELECT count(*) FROM documents WHERE client_id=?', (client,)).fetchone()[0]
    jobs = tuple(db.execute('SELECT count(*),max(updated_at) FROM jobs WHERE client_id=?', (client,)).fetchone())
    return hashlib.sha256(packed(dict(client=client, audit=audit, documents=documents, jobs=jobs)).encode()).hexdigest()


def preview(client, repo=repository):
    with repo.connection() as db:
        db.execute('BEGIN')
        owner = repo.client(db, client)
        counts = {table: db.execute('SELECT count(*) FROM ' + table + ' WHERE client_id=?', (client,)).fetchone()[0]
                  for table in ('records', 'revisions', 'documents', 'jobs', 'audit')}
        token = review_token(db, client)
    return dict(client_id=client, name=owner['name'], version=owner['version'], counts=counts,
                review_token=token,
                confirmation='DELETE CLIENT ' + client,
                retained='Previous backups, exported ZIPs, downloaded copies, and independent Image/Video Studio files are outside this erasure. '
                         'Review and remove those copies separately. This does not promise forensic disk erasure.',
                effect='Permanently removes this client from active agency SQLite storage, research originals and unshared registered asset files. '
                       'Cannot run while this client has active jobs. No automatic retention deletion.')


def retention_review(client, repo=repository):
    from datetime import datetime, timedelta, timezone
    with repo.connection() as db:
        repo.client(db, client)
        policy = db.execute("SELECT payload FROM records WHERE client_id=? AND kind='retention' AND archived=0", (client,)).fetchone()
        if not policy:
            raise ValueError('Save a retention policy before requesting a review')
        settings = json.loads(policy['payload'])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings['review_after_days'])).isoformat()
        total = db.execute('SELECT count(*) FROM records WHERE client_id=? AND kind!=? AND updated_at<?',
                           (client, 'retention', cutoff)).fetchone()[0]
        rows = [dict(r) for r in db.execute('SELECT id,kind,name,updated_at,archived FROM records WHERE client_id=? AND kind!=? AND updated_at<? ORDER BY updated_at LIMIT 500',
                                           (client, 'retention', cutoff))]
    return dict(settings=settings, cutoff=cutoff, total=total, items=rows,
                note='Review candidates only. Legal hold prevents routine erasure. Nothing is automatically deleted or treated as a legal retention determination.')


@serialized_store
def export_client(client, repo=repository):
    output = io.BytesIO()
    total = 0
    manifest = {}
    def add(archive, name, raw):
        nonlocal total
        total += len(raw)
        if total > LIMIT:
            raise ValueError('Client data exceeds the 128 MB export limit')
        archive.writestr(name, raw)
        manifest[name] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    with repo.connection() as db, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        db.execute('BEGIN')
        owner = repo.client(db, client)
        metadata_bytes = sum(db.execute('SELECT coalesce(sum(length(' + field + ')),0) FROM ' + table + ' WHERE client_id=?', (client,)).fetchone()[0]
                             for table, field in [('records', 'payload'), ('revisions', 'snapshot'), ('audit', 'details')])
        if metadata_bytes > LIMIT // 2:
            raise ValueError('Client metadata exceeds the export limit; use a full agency backup')
        rows = [dict(r) for r in db.execute('SELECT * FROM records WHERE client_id=? ORDER BY id', (client,))]
        revisions = [dict(r) for r in db.execute('SELECT * FROM revisions WHERE client_id=? ORDER BY resource_id,version', (client,))]
        documents = [dict(r) for r in db.execute('SELECT * FROM documents WHERE client_id=?', (client,))]
        payload = dict(client=owner, records=rows, revisions=revisions,
                       links=[dict(r) for r in db.execute('SELECT * FROM links WHERE client_id=?', (client,))],
                       documents=documents, audit=[dict(r) for r in db.execute('SELECT * FROM audit WHERE client_id=?', (client,))])
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        add(archive, 'client-data.json', raw)
        for document in documents:
            path = repo.home / 'documents' / document['filename']
            if path.parent.resolve() != (repo.home / 'documents').resolve() or not path.is_file():
                raise ValueError('A research original is missing')
            if path.stat().st_size + total > LIMIT:
                raise ValueError('Client data exceeds the export limit')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != document['sha256']:
                raise ValueError('A research original failed its checksum')
            add(archive, 'documents/' + document['filename'], raw)
        from .assets import stored_path
        for name in sorted(_asset_names(rows, revisions)):
            path = stored_path(name, repo)
            if path.stat().st_size + total > LIMIT:
                raise ValueError('Client data exceeds the export limit')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != name.split('.')[0]:
                raise ValueError('An asset failed its checksum')
            add(archive, 'assets/' + name, raw)
        archive.writestr('manifest.json', json.dumps(dict(created_at=timestamp(), files=manifest), indent=2))
        archive.writestr('README.txt', 'Client data portability export. Not a restore bundle. Contains personal data and immutable revision history. '
                          'Keep private. Use the agency backup tool for full restoration. Independent media stores and prior exports are separate.')
    with repo.connection(write=True) as db:
        repo.audit(db, client, client, 'privacy.client-exported', owner['version'], dict(files=len(manifest)))
    return output.getvalue()


@serialized_store
def erase(client, expected_version, confirmation, expected_review_token, repo=repository):
    # Only application-owned paths are removed after the database transaction commits.
    with repo.connection(write=True) as db:
        owner = repo.client(db, client)
        if owner['version'] != expected_version:
            raise Conflict('Client changed; review erasure again')
        if confirmation != 'DELETE CLIENT ' + client:
            raise ValueError('Type the exact confirmation shown in the erasure preview')
        if expected_review_token != review_token(db, client):
            raise Conflict('Client data changed after the erasure preview; review it again')
        hold = db.execute("SELECT 1 FROM records WHERE client_id=? AND kind='retention' AND archived=0 AND json_extract(payload,'$.legal_hold')=1", (client,)).fetchone()
        if hold:
            raise Conflict('This client has an active legal hold; resolve it before erasure')
        active = db.execute("SELECT 1 FROM jobs WHERE client_id=? AND state NOT IN ('completed','failed','cancelled')", (client,)).fetchone()
        if active:
            raise Conflict('Wait for or cancel this client’s active jobs before erasure')
        rows = [dict(r) for r in db.execute('SELECT * FROM records WHERE client_id=?', (client,))]
        revisions = [dict(r) for r in db.execute('SELECT * FROM revisions WHERE client_id=?', (client,))]
        names = _asset_names(rows, revisions)
        documents = [r['filename'] for r in db.execute('SELECT filename FROM documents WHERE client_id=?', (client,))]
        others = [dict(r) for r in db.execute('SELECT * FROM records WHERE client_id!=?', (client,))]
        other_versions = [dict(r) for r in db.execute('SELECT * FROM revisions WHERE client_id!=?', (client,))]
        unshared = names - _asset_names(others, other_versions)
        for table in ('links', 'job_links', 'jobs', 'revisions', 'documents', 'records', 'audit'):
            db.execute('DELETE FROM ' + table + ' WHERE client_id=?', (client,))
        db.execute('DELETE FROM clients WHERE id=?', (client,))
        repo.audit(db, None, uid(), 'privacy.client-erased', 1, dict(records=len(rows), revisions=len(revisions)))
    remaining = []
    for folder, names in [('documents', documents), ('assets', unshared)]:
        base = (repo.home / folder).resolve()
        for name in names:
            path = (base / name).resolve()
            if path.parent != base:
                remaining.append(folder + '/invalid-path')
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                remaining.append(folder + '/' + name)
    return dict(erased=True, removed_records=len(rows), files_requiring_manual_removal=remaining,
                retained='Prior backups, exports, downloads and independent Image/Video Studio files remain. Review those copies separately.')
