"""Real isolated persistence, SEO/page exports and CRM consent tests; no providers."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-acquisition-')
os.environ['AGENCY_DATA_DIR'] = str(Path(TEMP.name) / 'agency')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agency.api import router
from agency.security import AgencyRequestLimits

app = FastAPI()
app.include_router(router)
app.add_middleware(AgencyRequestLimits)


class AcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)

    def setUp(self):
        self.client = self.http.post('/api/agency/clients', json={'name': 'Acquisition client'}).json()['id']
        self.prefix = '/api/agency/clients/' + self.client

    def record(self, kind, data, name='Test record', status=201):
        response = self.http.post(self.prefix + '/records/' + kind, json=dict(name=name, data=data))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def update(self, item, **changes):
        response = self.http.put(self.prefix + '/records/' + item['kind'] + '/' + item['id'], json=dict(
            name=item['name'], data=dict(item['data'], **changes), expected_version=item['version']))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def get(self, path, status=200):
        response = self.http.get(self.prefix + path)
        self.assertEqual(response.status_code, status, response.text)
        return response

    def contact(self, email, **changes):
        return self.record('contacts', dict(email=email, source='Signed client form', consent_status='granted',
                                          consent_purpose='Product updates', consent_evidence='Form receipt 123', **changes))

    def test_audit_observations_duplicates_and_untrusted_html(self):
        html = '<title>Solar</title><meta name="robots" content="noindex"><h1>Solar</h1><img src="x"><a href="/service">More</a><script type="application/ld+json">{bad}</script>'
        first = self.record('seo-audits', dict(page_url='https://example.com/a', html=html))
        self.record('seo-audits', dict(page_url='https://example.com/b', html=html))
        result = self.get('/seo/audits/' + first['id'] + '/inspect').json()
        self.assertEqual(result['title'], 'Solar')
        self.assertFalse(result['allows_indexing_in_supplied_meta'])
        self.assertIsNone(result['observed_status'])
        self.assertEqual(result['internal_links'], ['https://example.com/service'])
        self.assertFalse(result['structured_data'][0]['valid_syntax'])
        self.assertIn('Images without alt attributes', result['findings'])
        comparison = self.get('/seo/compare').json()
        self.assertEqual(len(comparison['duplicates']['title'][0]), 2)
        self.assertNotIn('score', result)

    def test_landing_is_offline_rtl_escaped_and_preview_forms_cannot_send(self):
        item = self.record('landing-pages', dict(title='مرحبا', language='ar', canonical_url='https://example.com/مرحبا',
                           blocks=[dict(kind='hero', heading='<script>alert(1)</script>'), dict(kind='form')],
                           structured_data=json.dumps({'@type': 'WebPage', 'name': '</script><script>alert(2)</script>'})))
        response = self.get('/landing-pages/' + item['id'] + '/preview')
        self.assertIn('form-action \'none\'', response.headers['content-security-policy'])
        self.assertIn('dir="rtl"', response.text)
        self.assertNotIn('<script>alert(1)</script>', response.text)
        self.assertNotIn('</script><script>alert(2)</script>', response.text)
        self.assertIn('Local test mode', response.text)
        with zipfile.ZipFile(io.BytesIO(self.get('/landing-pages/' + item['id'] + '/export').content)) as archive:
            self.assertIn('sitemap.xml', archive.namelist())
            page = archive.read('index.html').decode()
            self.assertNotIn('https://cdn', page)
            self.assertIn('lexnis:analytics', page)

    def test_active_content_urls_and_json_rejected(self):
        self.record('landing-pages', dict(title='Bad', blocks=[dict(cta_url='javascript:alert(1)')]), status=422)
        self.record('email-templates', dict(subject='Bad', body='x', cta_url='data:text/html,boom'), status=422)
        self.record('landing-pages', dict(title='Bad', structured_data='{broken'), status=422)
        self.record('landing-pages', dict(title='Bad', structured_data='{"price":NaN}'), status=422)
        self.record('landing-pages', dict(title='Bad', structured_data='{"price":1e999}'), status=422)
        self.record('landing-pages', dict(title='Bad', structured_data='[' * 2000 + '0' + ']' * 2000), status=422)
        self.record('contacts', dict(email='a@example.com', consent_status='granted'), status=422)

    def test_research_snapshot_handoff_and_brand_token_freezing(self):
        from agency.research import document
        snapshot = document(self.client, 'website-snapshot.txt', b'<title>Captured page</title><h1>Captured</h1>', 'text/plain')
        source = self.record('sources', dict(source_type='url', url='https://example.com', snapshot_id=snapshot))
        response = self.http.post(self.prefix + '/seo/audit-source', json=dict(source_id=source['id']))
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        self.assertEqual(item['data']['source_ids'], [source['id']])
        self.assertEqual(self.get('/seo/audits/' + item['id'] + '/inspect').json()['title'], 'Captured page')
        brand = self.record('brands', dict(primary_color='#123456'))
        page = self.record('landing-pages', dict(title='Branded', brand_id=brand['id']))
        self.assertEqual(page['data']['primary_color'], '#123456')
        self.update(brand, primary_color='#654321')
        exported = self.get('/landing-pages/' + page['id'] + '/export')
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertIn('--primary:#123456', archive.read('index.html').decode())

    def test_consent_scope_withdrawal_and_suppression_override_tags(self):
        accepted = self.contact('yes@example.com', tags=['customers'])
        self.contact('suppressed@example.com', tags=['customers'], suppressed=True)
        self.contact('unsubscribed@example.com', tags=['customers'], unsubscribed=True)
        self.record('contacts', dict(email='unknown@example.com', tags=['customers']))
        self.contact('different-tag@example.com')
        segment = self.record('segments', dict(purpose='Product updates', required_tags=['customers']))
        path = '/segments/' + segment['id'] + '/preview'
        result = self.get(path).json()
        self.assertEqual(result['eligible'], 1)
        self.assertEqual(result['contacts'][0]['id'], accepted['id'])
        self.assertEqual(result['excluded_by_reason']['suppressed'], 1)
        self.assertTrue(accepted['data']['consent_recorded_at'])
        updated = self.update(accepted, notes='Same consent', consent_recorded_at='1990-01-01T00:00:00Z')
        self.assertEqual(updated['data']['consent_recorded_at'], accepted['data']['consent_recorded_at'])
        self.update(updated, consent_status='withdrawn')
        self.assertEqual(self.get(path).json()['eligible'], 0)
        history = self.get('/history/' + accepted['id']).json()
        self.assertTrue(history)

    def test_duplicate_emails_are_client_scoped_and_archiving_cannot_bypass(self):
        first = self.contact('Person@Example.com')
        self.record('contacts', dict(email='person@example.com'), status=409)
        archived = self.http.post(self.prefix + '/record/' + first['id'] + '/archive',
                                  json=dict(expected_version=first['version'], archived=True))
        self.assertEqual(archived.status_code, 200, archived.text)
        self.record('contacts', dict(email='person@example.com'), status=409)
        other = self.http.post('/api/agency/clients', json={'name': 'Other'}).json()['id']
        response = self.http.post('/api/agency/clients/' + other + '/records/contacts', json=dict(name='Person', data={'email': 'person@example.com'}))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(first['data']['email'], 'person@example.com')
        foreign = self.http.get('/api/agency/clients/' + other + '/segments/' + first['id'] + '/preview')
        self.assertEqual(foreign.status_code, 404)

    def test_csv_is_atomic_and_cannot_grant_consent(self):
        def upload(text):
            return self.http.post(self.prefix + '/contacts/import', files={'file': ('contacts.csv', text.encode(), 'text/csv')})
        self.assertEqual(upload('name,email\nOne,one@example.com\nTwo,not-an-email').status_code, 422)
        count = self.get('/records?kind=contacts').json()['total']
        self.assertEqual(count, 0)
        response = upload('name,email,tags\nOne,one@example.com,customer|local\nTwo,two@example.com,local')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['imported'], 2)
        for item in self.get('/records?kind=contacts').json()['items']:
            self.assertEqual(item['data']['consent_status'], 'unknown')
        self.assertEqual(upload('name,email,consent_status\nThird,three@example.com,granted').status_code, 400)
        self.assertEqual(upload('name,email\nOne,one@example.com\nThree,three@example.com').status_code, 409)
        self.assertEqual(self.get('/records?kind=contacts').json()['total'], 2)

    def test_email_snapshot_rechecks_withdrawal_on_every_export(self):
        contact = self.contact('client@example.com')
        segment = self.record('segments', dict(purpose='Product updates'))
        template = self.record('email-templates', dict(subject='Hello', body='<script>unsafe</script>\nWelcome'))
        path = self.prefix + '/email-templates/' + template['id'] + '/export?segment_id=' + segment['id']
        response = self.http.post(path)
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertNotIn('<script>unsafe</script>', archive.read('email.html').decode())
            checks = json.loads(archive.read('checks.json'))['checks']
            self.assertIn('Missing unsubscribe URL', checks)
            self.assertEqual(json.loads(archive.read('recipient-snapshot.json'))['eligible'], 1)
        self.update(contact, unsubscribed=True)
        with zipfile.ZipFile(io.BytesIO(self.http.post(path).content)) as archive:
            self.assertEqual(json.loads(archive.read('recipient-snapshot.json'))['contacts'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
