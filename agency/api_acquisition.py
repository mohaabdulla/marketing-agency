"""Protected local acquisition API. No automatic network, publishing or email delivery."""
import hashlib
from fastapi import File, UploadFile
from fastapi.responses import Response, HTMLResponse
from .api import router, guard
from .schemas import Id, Strict, RecordInput
from .services import service
from . import acquisition as a
from .database import repository


class AuditSource(Strict):
    source_id: Id


@router.post('/clients/{client_id}/seo/audit-source', status_code=201)
def audit_source(client_id: Id, body: AuditSource):
    def run():
        item = service.get(client_id, body.source_id, 'sources')
        if item['archived'] or not item['data']['snapshot_id'] or not item['data']['url']:
            raise ValueError('Capture this website source in Research before creating an HTML audit')
        with repository.connection() as db:
            row = db.execute('SELECT filename,sha256 FROM documents WHERE id=? AND client_id=?',
                             (item['data']['snapshot_id'], client_id)).fetchone()
        if not row:
            raise ValueError('Source snapshot is missing')
        base = (repository.home / 'documents').resolve()
        path = (base / row['filename']).resolve()
        if path.parent != base or not path.is_file() or path.stat().st_size > 300000:
            raise ValueError('Captured HTML must exist and fit the 300 KB audit budget')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Source snapshot failed its checksum')
        return service.save(client_id, 'seo-audits', RecordInput(name=item['name'][:145] + ' · HTML audit',
                            project_id=item['project_id'], campaign_id=item['campaign_id'],
                            data=dict(page_url=item['data']['url'], html=raw.decode('utf-8', errors='replace'),
                                      source_ids=[item['id']], source_note='Captured research snapshot, source v' + str(item['version']))))
    return guard(run)


@router.post('/clients/{client_id}/contacts/import')
def import_contacts(client_id: Id, file: UploadFile = File(...)):
    try:
        return guard(a.import_contacts, client_id, file)
    finally:
        file.file.close()


@router.get('/clients/{client_id}/seo/audits/{audit_id}/inspect')
def inspect(client_id: Id, audit_id: Id):
    return guard(lambda: a.audit(service.get(client_id, audit_id, 'seo-audits')['data']))


@router.get('/clients/{client_id}/seo/compare')
def compare(client_id: Id):
    def run():
        result = service.list(client_id, 'seo-audits', limit=100)
        if result['total'] > 100:
            raise ValueError('Compare at most 100 saved page audits')
        return a.audit_comparison(result['items'])
    return guard(run)


@router.get('/clients/{client_id}/landing-pages/{page_id}/preview')
def preview_page(client_id: Id, page_id: Id):
    content = guard(lambda: a.page_html(service.get(client_id, page_id, 'landing-pages')['data'], preview=True))
    return HTMLResponse(content, headers={'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'none'; base-uri 'none'"})


@router.get('/clients/{client_id}/landing-pages/{page_id}/export')
def export_page(client_id: Id, page_id: Id):
    content = guard(lambda: a.landing_bundle(service.get(client_id, page_id, 'landing-pages')))
    return Response(content, media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="landing-page.zip"'})


@router.get('/clients/{client_id}/segments/{segment_id}/preview')
def preview_segment(client_id: Id, segment_id: Id):
    return guard(lambda: a.segment_preview(client_id, service.get(client_id, segment_id, 'segments')['data']))


@router.get('/clients/{client_id}/email-templates/{template_id}/preview')
def preview_email(client_id: Id, template_id: Id):
    return guard(lambda: a.render_email(service.get(client_id, template_id, 'email-templates')['data']))


@router.post('/clients/{client_id}/email-templates/{template_id}/export')
def export_email(client_id: Id, template_id: Id, segment_id: Id | None = None):
    def run():
        item = service.get(client_id, template_id, 'email-templates')
        recipients = None
        if segment_id:
            segment = service.get(client_id, segment_id, 'segments')
            recipients = a.segment_preview(client_id, segment['data'])
            recipients.update(segment_id=segment['id'], segment_version=segment['version'],
                              template_id=item['id'], template_version=item['version'])
        content = a.email_bundle(item, recipients)
        with repository.connection(write=True) as db:
            repository.audit(db, client_id, item['id'], 'email.test-exported', item['version'],
                             dict(segment_id=segment_id, eligible=recipients['eligible'] if recipients else None,
                                  snapshot_sha256=hashlib.sha256(content).hexdigest()))
        return content
    return Response(guard(run), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="email-test-kit.zip"'})
