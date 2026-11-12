"""Agency business rules. Every reference is resolved within the selected client."""
import json
from datetime import date
from .database import repository, Repository, NotFound, Conflict, uid, timestamp, packed
from .schemas import MODELS, REFERENCES
from . import production


def effective_claim(data):
    today = date.today().isoformat()
    if data.get('valid_until') and data['valid_until'] < today:
        return 'expired'
    if data.get('valid_from') and data['valid_from'] > today:
        return 'not-yet-valid'
    return data['status']


def decorated(item):
    if item['kind'] == 'claims':
        return dict(item, effective_status=effective_claim(item['data']))
    return production.decorate(item)


class AgencyService:
    def __init__(self, repo=repository):
        self.repo = repo

    def get(self, client_id, key, kind=None):
        with self.repo.connection() as db:
            self.repo.client(db,client_id)
            item=self.repo.record(db,client_id,key,kind,include_archived=True)
            item['reference_versions']=[dict(id=r['target_id'],relation=r['relation'],version=r['target_version'])
                for r in db.execute('SELECT target_id,relation,target_version FROM links WHERE source_id=? AND client_id=? ORDER BY relation,target_id',(key,client_id))]
            return decorated(item)

    def list(self, client_id, kind=None, **kwargs):
        summary=kwargs.pop('summary',False)
        if kind and kind not in MODELS:
            raise ValueError('Unsupported record type')
        with self.repo.connection() as db:
            for field,target in [('project_id','projects'),('campaign_id','campaigns')]:
                if kwargs.get(field):
                    self.repo.record(db,client_id,kwargs[field],target)
        result = self.repo.records(client_id,kind,**kwargs)
        result['items'] = [decorated(x) for x in result['items']]
        if summary:
            for item in result['items']:
                item['data']={k:v for k,v in item['data'].items() if k in {'status','state','classification','publish_status','asset_type','sequence','scheduled_date','channel','format','language'}}
                item.pop('computed',None)
        return result

    def save(self, client_id, kind, body, key=None, expected_version=None, file_change=False):
        if kind not in MODELS:
            raise ValueError('Unsupported record type')
        data = MODELS[kind].model_validate(body.data).model_dump(mode='json')
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            raise ValueError('End date must follow start date')
        with self.repo.connection(write=True) as db:
            self.repo.client(db,client_id,active=True)
            old = self.repo.record(db,client_id,key,kind,include_archived=True) if key else None
            if old and old['archived']:
                raise Conflict('Restore this record before editing')
            if old and old['version'] != expected_version:
                raise Conflict('Record changed elsewhere; reload before saving')
            from .acquisition import prepare as acquisition_prepare
            acquisition_prepare(db,self.repo,client_id,kind,data,old)
            production.prepare(db,self.repo,client_id,kind,data,body)
            if kind == 'projects' and (body.project_id or body.campaign_id):
                raise ValueError('Projects cannot belong to another project or campaign')
            if kind == 'campaigns' and body.campaign_id:
                raise ValueError('A campaign cannot belong to another campaign')
            if kind in {'briefs','channels','deliverables'} and not body.campaign_id:
                raise ValueError('Choose a campaign for this record')
            references = []
            scopes = {}
            for field,target in [('project_id','projects'),('campaign_id','campaigns')]:
                value = getattr(body,field)
                if value:
                    record = self.repo.record(db,client_id,value,target)
                    scopes[field] = record
                    references.append((value,field,record['version']))
            if body.project_id and body.campaign_id and scopes['campaign_id']['project_id'] != body.project_id:
                raise ValueError('The selected campaign does not belong to this project')
            resolved = {}
            for field,target in REFERENCES.items():
                raw = data.get(field)
                ids = raw if isinstance(raw,list) else [raw] if raw else []
                for value in ids:
                    record = self.repo.record(db,client_id,value,target)
                    references.append((value,field,record['version']))
                    resolved[value] = record
            for field in ('document_id','snapshot_id'):
                if data.get(field):
                    if not db.execute('SELECT id FROM documents WHERE id=? AND client_id=?',(data[field],client_id)).fetchone():
                        raise NotFound('Document not found in this client')
            if data.get('generation'):
                generated=data['generation']
                self.repo.record(db,client_id,generated['source_brief_id'],'briefs',include_archived=True)
                if not db.execute('SELECT 1 FROM revisions WHERE resource_id=? AND client_id=? AND version=?',
                                  (generated['source_brief_id'],client_id,generated['source_brief_version'])).fetchone():
                    raise NotFound('Generation source revision not found in this client')
                references.append((generated['source_brief_id'],'generation.source_brief',generated['source_brief_version']))
            if kind == 'sources' and data['source_type'] in {'document','csv'} and not data['document_id']:
                raise ValueError('Import a document before selecting this source type')
            if kind == 'findings' and data['classification'] == 'fact':
                if any(resolved[x]['data']['evidence_state'] not in {'verified_source','client_supplied'} for x in data['source_ids']):
                    raise ValueError('Facts need reviewed sources; retain hypothesis status until then')
            if kind == 'evidence' and data['source_type']=='research-source' and not data['source_ids']:
                raise ValueError('Research evidence requires source links')
            if kind == 'claims' and data['status'] in {'verified','client-approved'}:
                states = [resolved[x]['data']['state'] for x in data['evidence_ids']]
                if 'unverified_hypothesis' in states:
                    raise ValueError('Unverified hypotheses cannot substantiate an approved claim')
                if data['status']=='verified' and 'verified_source' not in states:
                    raise ValueError('Verified claims require verified-source evidence')
                if old and old['data']['text'] != data['text'] and old['data']['status'] in {'verified','client-approved'}:
                    raise Conflict('Changed claim wording needs a draft revision before a new approval')
            if kind in {'brands','briefs'}:
                for claim_id in data.get('approved_claim_ids',data.get('claim_ids',[])):
                    if effective_claim(resolved[claim_id]['data']) not in {'verified','client-approved'}:
                        raise ValueError('Only current verified or client-approved claims may be selected')
            production.rules(db,self.repo,client_id,kind,data,body,old,resolved,references,file_change)
            key = key or uid()
            if any(target == key for target,_,_ in references):
                raise ValueError('Records cannot reference themselves')
            now = timestamp()
            version = old['version']+1 if old else 1
            project_id = body.project_id
            if body.campaign_id:
                project_id = scopes['campaign_id']['project_id']
            if old:
                db.execute('UPDATE records SET name=?,project_id=?,campaign_id=?,payload=?,version=?,updated_at=? WHERE id=? AND client_id=?',
                           (body.name,project_id,body.campaign_id,packed(data),version,now,key,client_id))
                db.execute('DELETE FROM links WHERE source_id=? AND client_id=?',(key,client_id))
            else:
                db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (key,client_id,kind,body.name,project_id,body.campaign_id,packed(data),version,0,now,now))
            for target,relation,target_version in set(references):
                db.execute('INSERT INTO links VALUES (?,?,?,?,?)',(key,target,client_id,relation,target_version))
            item = self.repo.record(db,client_id,key,kind)
            # Freeze the versions of all source records used by this revision.
            item['reference_versions'] = [dict(id=t,relation=r,version=v) for t,r,v in sorted(set(references))]
            self.repo.revision(db,item,kind)
            self.repo.audit(db,client_id,key,kind+('.updated' if old else '.created'),version)
            production.after_save(db,self.repo,client_id,item)
            return decorated(item)

    def archive(self, client_id, key, expected_version, archived=True):
        with self.repo.connection(write=True) as db:
            self.repo.client(db,client_id,active=True)
            old = self.repo.record(db,client_id,key,include_archived=True)
            if old['version'] != expected_version:
                raise Conflict('Record changed elsewhere; reload before archiving')
            if archived and db.execute('SELECT 1 FROM links l JOIN records r ON r.id=l.source_id WHERE l.target_id=? AND r.archived=0 LIMIT 1',(key,)).fetchone():
                raise Conflict('This record is referenced by active work; remove or archive those dependencies first')
            db.execute('UPDATE records SET archived=?,version=version+1,updated_at=? WHERE id=?',
                       (int(archived),timestamp(),key))
            item = self.repo.record(db,client_id,key,include_archived=True)
            self.repo.revision(db,item,item['kind'])
            self.repo.audit(db,client_id,key,'record.archived' if archived else 'record.restored',item['version'])
            return decorated(item)

    def dashboard(self, client_id=None):
        with self.repo.connection() as db:
            if client_id:
                self.repo.client(db,client_id)
            clause, params = (' AND client_id=?',[client_id]) if client_id else ('',[])
            counts = {r['kind']:r['n'] for r in db.execute('SELECT kind,count(*) n FROM records WHERE archived=0'+clause+' GROUP BY kind',params)}
            recent = [self.repo.unpack_record(r) for r in db.execute('SELECT * FROM records WHERE archived=0'+clause+' ORDER BY updated_at DESC LIMIT 8',params)]
            clients = db.execute("SELECT count(*) FROM clients WHERE status!='archived'").fetchone()[0]
            return dict(active_clients=clients,counts=counts,recent=recent,mode='Local core · single local operator')

    def calendar(self, client_id, campaign_id=None,limit=25,offset=0):
        with self.repo.connection() as db:
            self.repo.client(db,client_id)
            if campaign_id:
                self.repo.record(db,client_id,campaign_id,'campaigns')
            where="client_id=? AND kind='deliverables' AND archived=0 AND json_extract(payload,'$.due_date') IS NOT NULL"
            params=[client_id]
            if campaign_id:
                where+=' AND campaign_id=?'
                params.append(campaign_id)
            total=db.execute('SELECT count(*) FROM records WHERE '+where,params).fetchone()[0]
            rows=db.execute("SELECT * FROM records WHERE "+where+" ORDER BY json_extract(payload,'$.due_date'),id LIMIT ? OFFSET ?",(*params,limit,offset))
            return dict(items=[self.repo.unpack_record(row) for row in rows],total=total,limit=limit,offset=offset)


service = AgencyService()
