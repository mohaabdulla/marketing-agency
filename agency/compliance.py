"""Deterministic review flags, not a legal determination or a model's self-score."""
import re
from .database import repository
from .services import effective_claim


def scan(client_id, text, claim_ids=(), brand_id=None, cta='', language='en', repo=repository):
    flags, spans = [], []
    with repo.connection() as db:
        repo.client(db,client_id)
        claims = [repo.record(db,client_id,key,'claims') for key in claim_ids]
        for claim in claims:
            status = effective_claim(claim['data'])
            if status not in {'verified','client-approved'}:
                flags.append(dict(code='claim_not_current',severity='block',message='Selected claim is '+status,record_id=claim['id']))
            else:
                spans.extend((m.start(),m.end()) for m in re.finditer(re.escape(claim['data']['text']),text,re.IGNORECASE))
        # Flag prohibited/expired wording even if the caller omits that claim from selected IDs.
        for row in db.execute("SELECT id,payload FROM records WHERE client_id=? AND kind='claims' AND archived=0",(client_id,)):
            import json
            data = json.loads(row['payload'])
            status = effective_claim(data)
            if status in {'prohibited','expired'} and data['text'].casefold() in text.casefold():
                flags.append(dict(code='restricted_claim',severity='block',message='Text uses a '+status+' claim',record_id=row['id']))
        if brand_id:
            brand = repo.record(db,client_id,brand_id,'brands')['data']
            for phrase in brand['prohibited_language']+brand['forbidden_claims']:
                if phrase and re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',text,re.IGNORECASE):
                    flags.append(dict(code='prohibited_phrase',severity='block',message='Prohibited wording: '+phrase))
            for disclosure in brand['legal_disclosures']:
                if disclosure.casefold() not in text.casefold():
                    flags.append(dict(code='missing_disclosure',severity='review',message='Missing required client disclosure: '+disclosure))
        for row in db.execute("SELECT id,payload FROM records WHERE client_id=? AND kind='glossary' AND archived=0",(client_id,)):
            import json
            for phrase in json.loads(row['payload'])['prohibited_forms']:
                if phrase and re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',text,re.IGNORECASE):
                    flags.append(dict(code='glossary_violation',severity='review',message='Prohibited terminology: '+phrase,record_id=row['id']))
    for match in re.finditer(r'(?<!\w)[0-9\u0660-\u0669]+(?:[.,٫][0-9\u0660-\u0669]+)?\s*[%٪]?',text):
        if not any(a<=match.start() and match.end()<=b for a,b in spans):
            flags.append(dict(code='quantitative_claim_needs_evidence',severity='review',message='Review unsubstantiated number: '+match.group().strip()))
    if not cta.strip():
        flags.append(dict(code='missing_cta',severity='review',message='Add a clear call to action'))
    if language.startswith('ar') and text and not re.search(r'[\u0600-\u06ff]',text):
        flags.append(dict(code='language_mismatch',severity='review',message='Arabic locale selected but no Arabic text found'))
    return dict(flags=flags,export_state='review-required' if flags else 'checks-passed',
                scope='Deterministic checks only. Review facts, rights and applicable requirements separately.')
