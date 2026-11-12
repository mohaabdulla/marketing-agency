"""Planning packages and lossless agency backups; all archive paths are application-owned."""
import csv
import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
import re
from pathlib import Path, PurePosixPath
from contextlib import closing
from .database import repository, timestamp, uid, packed, NotFound, SCHEMA_VERSION
from .services import service
from .schemas import RecordInput
from .compliance import scan


def brief_from_strategy(client_id,campaign_id,repo=repository,agency=service):
    campaign=agency.get(client_id,campaign_id,'campaigns')
    data=campaign['data']
    strategy=agency.get(client_id,data['strategy_id'],'strategies')['data'] if data['strategy_id'] else {}
    positioning_id=data['positioning_id'] or strategy.get('positioning_id')
    positioning=agency.get(client_id,positioning_id,'positionings')['data'] if positioning_id else {}
    audience_ids=data['audience_ids'] or strategy.get('audience_ids',[])
    audience_names=[agency.get(client_id,key,'audiences')['name'] for key in audience_ids]
    message_ids=data['message_ids'] or strategy.get('message_ids',[])
    messages=[agency.get(client_id,key,'messages')['data'] for key in message_ids]
    offer_id=data['offer_id'] or strategy.get('offer_id')
    offer=agency.get(client_id,offer_id,'offers')['data'] if offer_id else {}
    payload=dict(business_context=strategy.get('business_context',''),campaign_objective=data['objective'],
                 measurable_success=data['primary_kpi'],audience='; '.join(audience_names),
                 positioning=positioning.get('primary_benefit',''),
                 primary_message=messages[0]['proposition'] if messages else '',
                 supporting_messages=[m for group in messages for m in group['supporting_messages']],
                 reasons_to_believe=[positioning['reason_to_believe']] if positioning.get('reason_to_believe') else [],
                 offer=offer.get('description',''),cta=offer.get('cta','') or next((m['cta'] for m in messages if m['cta']),''),
                 channels=strategy.get('channels',[]),budget=f"{data['budget']} {data['currency']}",
                 localization=', '.join(data['languages']),timing=' – '.join(x for x in [data['start_date'],data['end_date']] if x))
    return agency.save(client_id,'briefs',RecordInput(name=campaign['name']+' · brief',project_id=campaign['project_id'],
                       campaign_id=campaign_id,data=payload))


def campaign_plan(client_id,campaign_id,draft_only=True,repo=repository,agency=service):
    campaign=agency.get(client_id,campaign_id,'campaigns')
    # Client-level plans are paginated elsewhere; campaign export is bounded to 1,000 records.
    result=agency.list(client_id,campaign_id=campaign_id,limit=1000)
    if result['total']>1000:
        raise ValueError('Campaign exceeds the 1,000 record planning-package limit')
    records=result['items']
    briefs=sorted((r for r in records if r['kind']=='briefs'),key=lambda r:r['updated_at'],reverse=True)
    text_parts=[];claim_ids=[]
    for brief in briefs[:1]:
        data=brief['data']
        for field in ('primary_message','supporting_messages','reasons_to_believe','offer'):
            value=data[field]
            text_parts.extend(value if isinstance(value,list) else [value])
        claim_ids.extend(data['claim_ids'])
    cta=briefs[0]['data']['cta'] if briefs else ''
    result=scan(client_id,'\n'.join(text_parts),claim_ids,campaign['data']['brand_id'],cta,repo=repo)
    if not briefs:
        result['flags'].append(dict(code='missing_brief',severity='review',message='Create a creative brief before production'))
        result['export_state']='review-required'
    if result['flags'] and not draft_only:
        from .database import Conflict
        raise Conflict('Planning package has review flags; export as a review draft or resolve the checks')
    key=uid()
    path=repo.home/'exports'/(key+'.zip')
    payload=dict(schema_version=1,exported_at=timestamp(),purpose='Review draft' if draft_only else 'Checked planning package',
                 publication_authorized=False,campaign=campaign,records=records,checks=result)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('campaign-plan.json',json.dumps(payload,ensure_ascii=False,indent=2))
        stream=io.StringIO(newline='')
        writer=csv.writer(stream)
        writer.writerow(['Deliverable','Platform','Format','Language','Due date','Owner','State'])
        def safe(value):
            value=str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
        for r in records:
            if r['kind']=='deliverables':
                d=r['data']
                writer.writerow([safe(x) for x in [r['name'],d['platform'],d['format'],d['language'],d['due_date'],d['owner'],d['state']]])
        bundle.writestr('deliverables.csv','\ufeff'+stream.getvalue())
    with repo.connection(write=True) as db:
        repo.audit(db,client_id,campaign_id,'campaign.plan-exported',campaign['version'],dict(draft_only=draft_only))
    return path


def backup_bundle(repo=repository):
    repo.initialize()
    if len(list((repo.home/'backups').glob('*.zip')))>=20:
        raise ValueError('Twenty agency backups are retained. Move older backups to managed archival storage before creating more.')
    backup=repo.backup()
    database=repo.home/'backups'/(backup['id']+'.sqlite3')
    target=database.with_suffix('.zip')
    manifest=dict(schema_version=SCHEMA_VERSION,created_at=timestamp(),files={'agency.sqlite3':dict(sha256=backup['sha256'],size=backup['size'])})
    with closing(sqlite3.connect(database)) as db:
        rows=db.execute('SELECT filename,sha256,size FROM documents').fetchall()
        # Every file version of every registered asset, including superseded versions kept in history.
        stored=sorted({r[0] for r in db.execute("SELECT json_extract(snapshot,'$.data.stored_name') FROM revisions WHERE resource_type='assets'") if r[0]})
    asset_files=[]
    for name in stored:
        if not re.fullmatch(r'[a-f0-9]{64}\.[a-z0-9]{2,5}',name):
            raise ValueError('Unexpected asset filename in backup metadata')
        source=repo.home/'assets'/name
        if not source.is_file():
            raise ValueError('A registered asset file is missing; backup stopped')
        asset_files.append((name,source,source.stat().st_size))
    if backup['size']+sum(r[2] for r in rows)+sum(a[2] for a in asset_files)>512*1024**2:
        raise ValueError('Backup exceeds 512 MB limit; use an operator-managed archival workflow')
    try:
        with zipfile.ZipFile(target,'w',zipfile.ZIP_STORED) as bundle:
            bundle.write(database,'agency.sqlite3')
            for filename,digest,size in rows:
                if not re.fullmatch(r'[a-f0-9]{32}\.(?:txt|csv)',filename):
                    raise ValueError('Unexpected research document filename in backup metadata')
                source=repo.home/'documents'/filename
                if source.parent!=repo.home/'documents' or not source.is_file():
                    raise ValueError('A referenced research document is missing; backup stopped')
                if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
                    raise ValueError('Research document checksum mismatch; backup stopped')
                name='documents/'+filename
                bundle.write(source,name)
                manifest['files'][name]=dict(sha256=digest,size=size)
            for filename,source,size in asset_files:
                digest=hashlib.sha256()
                with source.open('rb') as handle:
                    for chunk in iter(lambda:handle.read(1024**2),b''):
                        digest.update(chunk)
                if digest.hexdigest()!=filename.split('.')[0]:
                    raise ValueError('Registered asset checksum mismatch; backup stopped')
                bundle.write(source,'assets/'+filename)
                manifest['files']['assets/'+filename]=dict(sha256=digest.hexdigest(),size=size)
            bundle.writestr('manifest.json',packed(manifest))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return dict(id=backup['id'],size=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                schema_version=SCHEMA_VERSION,documents=len(rows),assets=len(asset_files))


def restore_bundle(archive,destination):
    """Operator-only offline restore into a NEW directory. Never overwrites a running database."""
    destination=Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore destination must be an empty new directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent,prefix='lexnis-restore-') as tmp:
        staging=Path(tmp)
        with zipfile.ZipFile(archive) as bundle:
            entries=bundle.infolist()
            if len(entries)>10005 or sum(i.file_size for i in entries)>512*1024**2:
                raise ValueError('Backup has excessive entries or expansion size')
            names=[i.filename for i in entries]
            if len(set(names))!=len(names):
                raise ValueError('Duplicate backup entries are not accepted')
            for entry in entries:
                path=PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename:
                    raise ValueError('Unsafe backup archive path')
                is_asset=len(path.parts)==2 and path.parts[0]=='assets' and bool(re.fullmatch(r'[a-f0-9]{64}\.[a-z0-9]{2,5}',path.parts[1]))
                if entry.filename not in {'manifest.json','agency.sqlite3'} and not is_asset and not (
                    len(path.parts)==2 and path.parts[0]=='documents' and
                    len(path.stem)==32 and all(c in '0123456789abcdef' for c in path.stem) and path.suffix in {'.txt','.csv'}):
                    raise ValueError('Unexpected backup entry')
                if entry.file_size>(256 if is_asset else 10)*1024**2 and entry.filename!='agency.sqlite3':
                    raise ValueError('Backup document exceeds size limit')
            manifest=json.loads(bundle.read('manifest.json'))
            if manifest['schema_version']!=SCHEMA_VERSION or set(manifest['files'])!=set(names)-{'manifest.json'}:
                raise ValueError('Backup manifest does not match its files')
            for name,metadata in manifest['files'].items():
                target=staging/name
                target.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256();size=0
                with bundle.open(name) as source,target.open('wb') as out:
                    while chunk:=source.read(1024**2):
                        size+=len(chunk)
                        if size>512*1024**2:
                            raise ValueError('Backup expansion limit exceeded')
                        digest.update(chunk);out.write(chunk)
                if size!=metadata['size'] or digest.hexdigest()!=metadata['sha256']:
                    raise ValueError('Backup checksum mismatch')
                if name.startswith('assets/') and digest.hexdigest()!=PurePosixPath(name).stem:
                    raise ValueError('Backup asset does not match its content address')
        repository.validate_backup(staging/'agency.sqlite3')
        with closing(sqlite3.connect(staging/'agency.sqlite3')) as db:
            for filename,digest,size in db.execute('SELECT filename,sha256,size FROM documents'):
                if not re.fullmatch(r'[a-f0-9]{32}\.(?:txt|csv)',filename):
                    raise ValueError('Unexpected research document filename in backup database')
                file=staging/'documents'/filename
                if not file.is_file() or file.stat().st_size!=size or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
                    raise ValueError('Backup research documents do not match database metadata')
            needed={r[0] for r in db.execute("SELECT json_extract(snapshot,'$.data.stored_name') FROM revisions WHERE resource_type='assets'") if r[0]}
            if any(not (staging/'assets'/name).is_file() for name in needed):
                raise ValueError('Backup is missing registered asset files')
        if destination.exists():
            destination.rmdir()  # Only the checked, empty destination is removed.
        shutil.copytree(staging,destination)
    return dict(restored=True,schema_version=SCHEMA_VERSION)
