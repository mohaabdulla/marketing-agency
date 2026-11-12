"""Deterministic SEO inspection, offline pages and consent-aware email exports."""
import csv
import hashlib
import io
import json
import re
import zipfile
from html import escape as e
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .database import repository, Conflict, timestamp, uid, packed
from .acquisition_schemas import Contact, strict_json


def prepare(db, repo, client, kind, data, old):
    if kind == 'retention':
        exists = db.execute("SELECT id FROM records WHERE client_id=? AND kind='retention' AND id!=?",
                            (client, old['id'] if old else '')).fetchone()
        if exists:
            raise Conflict('This client already has a retention policy; edit the saved policy')
    if kind != 'contacts':
        return
    existing = db.execute("SELECT id FROM records WHERE client_id=? AND kind='contacts' "
                          "AND json_extract(payload,'$.email')=? AND id!=?",
                          (client, data['email'], old['id'] if old else '')).fetchone()
    if existing:
        raise Conflict('This email already exists for this client, including archived contacts')
    if old and data['email'] != old['data']['email']:
        raise ValueError('Contact email is immutable to retain consent and suppression history. Create a separate contact for a different address.')
    fields = ('consent_status', 'consent_purpose', 'consent_evidence', 'source')
    changed = old is None or any(data[k] != old['data'][k] for k in fields)
    data['consent_recorded_at'] = timestamp() if changed else old['data']['consent_recorded_at']


def audit(data):
    """Inspect supplied HTML only. Does not infer live HTTP, robots.txt or speed metrics."""
    source = data['html']
    soup = BeautifulSoup(source, 'html.parser')
    if len(soup.find_all(True, limit=15001)) > 15000:
        raise ValueError('HTML exceeds the 15,000 element audit limit')
    base = data['page_url']
    def meta(name):
        tag = soup.find('meta', attrs={'name': re.compile('^' + re.escape(name) + '$', re.I)})
        return tag.get('content', '') if tag else ''
    headings = [dict(level=int(h.name[1]), text=h.get_text(' ', strip=True)[:500]) for h in soup.find_all(re.compile(r'^h[1-6]$'))]
    images = [dict(src=i.get('src', '')[:2000], alt=i.get('alt'), decorative=i.get('alt') == '') for i in soup.find_all('img')]
    canonical = soup.find('link', rel=lambda r: r and 'canonical' in r)
    links = [urljoin(base, a.get('href', '')) for a in soup.find_all('a', href=True)]
    links = sorted({x for x in links if urlsplit(x).scheme in {'http', 'https'}})
    jsonld = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            value = strict_json(script.string or script.get_text())
            jsonld.append(dict(valid_syntax=isinstance(value, (dict, list)), value=value))
        except (ValueError, RecursionError):
            jsonld.append(dict(valid_syntax=False, error='Invalid JSON syntax'))
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    description = meta('description')
    robots = meta('robots')
    findings = []
    for condition, message in [
        (not title, 'Missing title'), (not description, 'Missing meta description'),
        (sum(h['level'] == 1 for h in headings) != 1, 'Expected one main H1; review heading structure'),
        (any(i['alt'] is None for i in images), 'Images without alt attributes'),
        (not meta('viewport'), 'Missing viewport metadata'),
        (any(not x['valid_syntax'] for x in jsonld), 'Invalid JSON-LD syntax'),
        (not canonical, 'No canonical link declared'),
    ]:
        if condition:
            findings.append(message)
    return dict(title=title, description=description, canonical=canonical.get('href', '') if canonical else '',
                robots=robots, allows_indexing_in_supplied_meta='noindex' not in re.split(r'[\s,]+', robots.casefold()),
                observed_status=data['observed_status'], viewport=meta('viewport'), headings=headings, images=images,
                internal_links=[x for x in links if urlsplit(x).netloc == urlsplit(base).netloc],
                external_links=[x for x in links if urlsplit(x).netloc != urlsplit(base).netloc],
                hreflang=[dict(language=x.get('hreflang'), href=x.get('href')) for x in soup.find_all('link', hreflang=True)],
                sitemap_references=[x.get('href') for x in soup.find_all('link', rel=lambda r: r and 'sitemap' in r)],
                structured_data=jsonld, source_bytes=len(source.encode()), source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                findings=findings, method='Supplied HTML inspection; observed HTTP status is operator-entered. '
                'No live crawl, robots.txt check, rendered-page test, speed measurement or ranking score.')


def audit_comparison(items):
    rows = [dict(id=r['id'], name=r['name'], **audit(r['data'])) for r in items]
    duplicates = {}
    for key in ('title', 'description'):
        groups = {}
        for row in rows:
            value = row[key].strip().casefold()
            if value:
                groups.setdefault(value, []).append(row['id'])
        duplicates[key] = [ids for ids in groups.values() if len(ids) > 1]
    return dict(pages=rows, duplicates=duplicates)


def bundle(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


PAGE_CSS = """*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:18px/1.65 system-ui,sans-serif}
nav,main,footer{max-width:1080px;margin:auto;padding:24px}section{padding:40px 16px;border-bottom:1px solid #8884}
h1{font-size:clamp(2rem,6vw,4rem);line-height:1.1}h2{font-size:clamp(1.4rem,4vw,2rem)}p{white-space:pre-line;max-width:75ch}
a,button{color:var(--primary)}.cta,button{display:inline-block;border:2px solid var(--primary);padding:12px 24px;border-radius:8px}
input,textarea{display:block;width:100%;max-width:600px;padding:12px;font:inherit}label{display:block;margin:16px 0}
input[type=checkbox]{display:inline;width:auto}.honey{position:absolute;left:-10000px}small{font-size:.8rem}
@media(max-width:640px){main,nav,footer{padding:12px}section{padding:24px 8px}}
"""
PAGE_JS = """document.querySelectorAll('[data-event]').forEach(el=>el.addEventListener('click',()=>{
window.dispatchEvent(new CustomEvent('lexnis:analytics',{detail:{event:el.dataset.event}}));
}));document.querySelectorAll('form[data-test]').forEach(form=>form.addEventListener('submit',event=>{
event.preventDefault();form.querySelector('[role=status]').textContent='Local test complete. Nothing was submitted or emailed.';
}));"""


def page_html(data, preview=False):
    direction = 'rtl' if data['language'].startswith('ar') else 'ltr'
    blocks = []
    for i, block in enumerate(data['blocks']):
        content = (f"<h{'1' if block['kind'] == 'hero' else '2'}>{e(block['heading'])}</h{'1' if block['kind'] == 'hero' else '2'}>"
                   if block['heading'] else '') + f"<p>{e(block['text'])}</p>"
        if block['cta_url']:
            content += f'<a class="cta" href="{e(block["cta_url"], quote=True)}" data-event="cta-{i}">{e(block["cta_label"] or "Learn more")}</a>'
        if block['kind'] == 'form':
            endpoint = '' if preview else data['form_endpoint']
            action = f'action="{e(endpoint, quote=True)}" method="post"' if endpoint else 'data-test'
            # An exported form remains in test mode unless an endpoint and privacy copy are both supplied.
            if endpoint and not data['privacy_copy'].strip():
                raise ValueError('A connected form needs privacy copy')
            content += f'''<form {action}><label>Email<input type="email" name="email" required maxlength="254"></label>
<label class="honey" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
<label><input type="checkbox" name="consent" required value="yes"> {e(data['privacy_copy'] or 'I consent to this local form test.')}</label>
<button type="submit">Submit</button><p role="status">{'Endpoint configured; its operator handles delivery, validation and spam protection.' if endpoint else 'Local test mode: no data leaves this page.'}</p></form>'''
        blocks.append(f'<section data-block="{block["kind"]}">{content}</section>')
    canonical = f'<link rel="canonical" href="{e(data["canonical_url"], quote=True)}">' if data['canonical_url'] else ''
    # Escape < to prevent closing the JSON-LD script element through operator-entered JSON.
    structured = '<script type="application/ld+json">' + data['structured_data'].replace('<', '\\u003c') + '</script>' if data['structured_data'] else ''
    style = f':root{{--primary:{data["primary_color"]};--bg:{data["background_color"]};--text:{data["text_color"]}}}' + PAGE_CSS
    return f'''<!doctype html><html lang="{data['language']}" dir="{direction}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(data['title'])}</title>
<meta name="description" content="{e(data['description'], quote=True)}"><meta property="og:title" content="{e(data['title'], quote=True)}">
<meta property="og:description" content="{e(data['description'], quote=True)}">{canonical}{structured}
<style>{style}</style></head><body><main>{''.join(blocks)}</main><script>{PAGE_JS}</script></body></html>'''


def landing_bundle(item):
    data = item['data']
    files = {'index.html': page_html(data), 'style.css': PAGE_CSS, 'events.js': PAGE_JS,
             'metadata.json': json.dumps(dict(id=item['id'], version=item['version'], data=data), ensure_ascii=False, indent=2),
             'README.txt': 'Static offline page. Serve with python -m http.server 8000. Forms are local tests unless you configure an endpoint. '
             'No delivery infrastructure is included. Enforce consent, honeypot and rate limits on your endpoint. '
             'Analytics uses a local lexnis:analytics DOM event; add your own approved collector. Review all claims and rights before publishing.'}
    if data['canonical_url']:
        from xml.sax.saxutils import escape
        files['sitemap.xml'] = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>' + escape(data['canonical_url']) + '</loc></url></urlset>'
        parsed = urlsplit(data['canonical_url'])
        files['robots.txt'] = 'User-agent: *\nAllow: /\nSitemap: ' + parsed.scheme + '://' + parsed.netloc + '/sitemap.xml\n'
    return bundle(files)


def eligible(contact, segment):
    d = contact['data']
    reasons = []
    if contact['archived']:
        reasons.append('archived')
    if d['suppressed']:
        reasons.append('suppressed')
    if d['unsubscribed']:
        reasons.append('unsubscribed')
    if d['consent_status'] != 'granted' or not d['consent_recorded_at']:
        reasons.append('no recorded consent')
    if d['consent_purpose'].strip().casefold() != segment['purpose'].strip().casefold():
        reasons.append('consent purpose mismatch')
    if segment['language'] and segment['language'] != d['language']:
        reasons.append('language mismatch')
    tags = set(d['tags'])
    if not set(segment['required_tags']).issubset(tags) or set(segment['excluded_tags']) & tags:
        reasons.append('tag filter')
    return reasons


def segment_preview(client, segment, repo=repository):
    with repo.connection() as db:
        repo.client(db, client, active=True)
        rows = db.execute("SELECT * FROM records WHERE client_id=? AND kind='contacts' ORDER BY id LIMIT 10001", (client,)).fetchall()
        if len(rows) > 10000:
            raise ValueError('Segment preview is limited to 10,000 contacts')
        contacts = [repo.unpack_record(r) for r in rows]
    accepted = []
    excluded = {}
    for contact in contacts:
        reasons = eligible(contact, segment)
        if reasons:
            for reason in reasons:
                excluded[reason] = excluded.get(reason, 0) + 1
        else:
            accepted.append(dict(id=contact['id'], version=contact['version'], name=contact['name'], email=contact['data']['email']))
    return dict(total=len(contacts), eligible=len(accepted), excluded_by_reason=excluded, contacts=accepted,
                recorded_at=timestamp(), note='Eligibility at export time only. Recheck consent and suppression before any external send. No email is sent.')


def import_contacts(client, upload, repo=repository):
    raw = upload.file.read(1024 ** 2 + 1)
    if len(raw) > 1024 ** 2 or not (upload.filename or '').lower().endswith('.csv'):
        raise ValueError('Import a UTF-8 .csv file up to 1 MB')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        headers = reader.fieldnames or []
        if not {'email', 'name'} <= set(headers) or len(set(headers)) != len(headers) or set(headers) - {'email', 'name', 'language', 'source', 'tags'}:
            raise ValueError('CSV columns: email,name and optionally language,source,tags. Consent cannot be granted by CSV import.')
        contacts = []
        emails = set()
        for number, row in enumerate(reader, 2):
            if number > 1001 or None in row or any(v is None for v in row.values()):
                raise ValueError('CSV needs rectangular rows and at most 1,000 contacts')
            name = row['name'].strip()
            if not name or len(name) > 160:
                raise ValueError(f'Row {number}: name must contain 1–160 characters')
            data = Contact(email=row['email'], language=row.get('language') or 'en', source=row.get('source') or 'CSV import',
                           tags=[x.strip() for x in row.get('tags', '').split('|') if x.strip()]).model_dump(mode='json')
            if data['email'] in emails:
                raise ValueError('Duplicate email in CSV; nothing imported')
            emails.add(data['email'])
            contacts.append((name, data))
    except UnicodeDecodeError:
        raise ValueError('CSV must be UTF-8')
    if not contacts:
        raise ValueError('CSV contains no contacts')
    with repo.connection(write=True) as db:
        repo.client(db, client, active=True)
        existing = {json.loads(r['payload'])['email'] for r in db.execute("SELECT payload FROM records WHERE client_id=? AND kind='contacts'", (client,))}
        if emails & existing:
            raise Conflict('One or more emails already exist in this client; nothing imported')
        now = timestamp()
        for name, data in contacts:
            key = uid()
            data['consent_recorded_at'] = now
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (key, client, 'contacts', name, None, None, packed(data), 1, 0, now, now))
            repo.revision(db, repo.record(db, client, key, 'contacts'), 'contacts')
        repo.audit(db, client, client, 'contacts.csv-imported', 1, dict(count=len(contacts), consent_status='unknown'))
    return dict(imported=len(contacts), consent_status='unknown')


def render_email(data):
    direction = 'rtl' if data['language'].startswith('ar') else 'ltr'
    url = data['unsubscribe_url']
    unsubscribe = f'<a href="{e(url, quote=True)}">Unsubscribe</a>' if url else '[UNSUBSCRIBE_URL REQUIRED BEFORE SEND]'
    address = data['physical_address'] or '[PHYSICAL ADDRESS REQUIRED BEFORE SEND]'
    cta = f'<p><a href="{e(data["cta_url"], quote=True)}">{e(data["cta_label"] or "Learn more")}</a></p>' if data['cta_url'] else ''
    html = f'''<!doctype html><html lang="{data['language']}" dir="{direction}"><head><meta charset="utf-8"><title>{e(data['subject'])}</title></head>
<body style="margin:0;background:#f2f4f5"><div style="display:none;max-height:0;overflow:hidden">{e(data['preheader'])}</div>
<table role="presentation" width="100%" cellpadding="20" cellspacing="0"><tr><td align="center">
<table role="presentation" width="600" style="max-width:100%;background:#fff;font:16px/1.6 Arial,sans-serif" cellpadding="20"><tr><td>
<h1>{e(data['subject'])}</h1><p>{e(data['body']).replace(chr(10), '<br>')}</p>{cta}
<hr><p>{e(data['footer'])}</p><p>{e(address)}</p><p>{unsubscribe}</p></td></tr></table></td></tr></table></body></html>'''
    plain = '\n\n'.join([data['subject'], data['body'], data['cta_url'], data['footer'], address, url or '[UNSUBSCRIBE_URL REQUIRED BEFORE SEND]'])
    checks = []
    if not url:
        checks.append('Missing unsubscribe URL')
    if not data['physical_address']:
        checks.append('Missing physical address')
    if data['subject'].isupper():
        checks.append('Heuristic: all-uppercase subject; review tone')
    return dict(html=html, plain_text=plain, checks=checks, method='Template checks and tone heuristics only; no deliverability score or sending capability.')


def email_bundle(item, recipients=None):
    rendered = render_email(item['data'])
    files = {'email.html': rendered['html'], 'email.txt': rendered['plain_text'],
             'checks.json': json.dumps(dict(checks=rendered['checks'], method=rendered['method']), indent=2),
             'README.txt': 'TEST EXPORT. No message was sent. Configure delivery infrastructure, confirm sender identity, consent, '
             'unsubscribe handling and physical address, and test email-client rendering before any external send.'}
    if recipients is not None:
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['contact_id', 'version', 'name', 'email'])
        for c in recipients['contacts']:
            # Prevent spreadsheet formula execution for operator-controlled names and email local parts.
            writer.writerow([("'" + str(c[k])) if str(c[k]).startswith(('=', '+', '-', '@', '\t', '\r')) else c[k]
                             for k in ['id', 'version', 'name', 'email']])
        files['recipients.csv'] = buffer.getvalue()
        files['recipient-snapshot.json'] = json.dumps(recipients, ensure_ascii=False, indent=2)
    return bundle(files)
