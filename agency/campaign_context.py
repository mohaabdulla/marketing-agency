"""One consistent, campaign-scoped view, including only explicitly referenced shared records."""
from .services import service,decorated


def campaign_context(client_id,campaign_id,agency=service):
    repo=agency.repo
    with repo.connection() as db:
        db.execute('BEGIN')
        client=repo.client(db,client_id)
        campaign=repo.record(db,client_id,campaign_id,'campaigns')
        rows=db.execute('''WITH RECURSIVE scoped(id) AS (
            SELECT id FROM records WHERE client_id=? AND archived=0 AND (id=? OR campaign_id=?)
            UNION SELECT l.target_id FROM links l JOIN scoped s ON l.source_id=s.id WHERE l.client_id=?
        ) SELECT r.* FROM records r JOIN scoped s ON r.id=s.id
          WHERE r.client_id=? AND r.archived=0 ORDER BY r.updated_at DESC,r.id''',
            (client_id,campaign_id,campaign_id,client_id,client_id)).fetchall()
        records={}
        for row in rows:
            item=decorated(repo.unpack_record(row))
            if item['kind']!='campaigns':records.setdefault(item['kind'],[]).append(item)
    return client,campaign,records


def approved_targets(records):
    current={item['id']:item for items in records.values() for item in items}
    approved=set()
    for item in records.get('approvals',[]):
        data=item['data'];target=current.get(data.get('target_id'))
        if (data.get('state')=='approved' and target and data.get('target_version')==target['version']
                and (not data.get('target_sha256') or data['target_sha256']==target['data'].get('sha256'))):
            approved.add(target['id'])
    return approved


def strategy_summary(campaign,records):
    data=campaign['data']
    def linked(kind,key):return next((r['data'] for r in records.get(kind,[]) if r['id']==data.get(key)),{})
    brief=next(iter(records.get('briefs',[])),{}).get('data',{})
    strategy=linked('strategies','strategy_id');positioning=linked('positionings','positioning_id');offer=linked('offers','offer_id')
    messages=[r['data'] for r in records.get('messages',[]) if r['id'] in data.get('message_ids',[])]
    audiences=[r for r in records.get('audiences',[]) if r['id'] in data.get('audience_ids',[])]
    return dict(proposition=brief.get('primary_message') or strategy.get('strategic_idea') or next((m.get('proposition') for m in messages if m.get('proposition')),''),
        problem=positioning.get('problem') or strategy.get('current_state',''),offer=brief.get('offer') or offer.get('description',''),
        proof=brief.get('reasons_to_believe',[]),cta=brief.get('cta') or offer.get('cta') or next((m.get('cta') for m in messages if m.get('cta')),''),
        target_audience=brief.get('audience') or ', '.join(a['name'] for a in audiences),channels=brief.get('channels') or strategy.get('channels',[]))
