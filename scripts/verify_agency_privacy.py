"""Isolated destructive-workflow verification; never uses real client data."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-privacy-')
os.environ['AGENCY_DATA_DIR'] = str(Path(TEMP.name) / 'agency')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from agency.api import router
from agency.database import repository, uid
from agency.security import AgencyRequestLimits

app = FastAPI()
app.include_router(router)
app.add_middleware(AgencyRequestLimits)


class PrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)
        cls.picture = ROOT / 'output/renders' / ('privacy-' + uid() + '.png')
        cls.picture.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (20, 20), '#123456').save(cls.picture)

    @classmethod
    def tearDownClass(cls):
        cls.picture.unlink(missing_ok=True)

    def setUp(self):
        self.a = self.http.post('/api/agency/clients', json={'name': 'Erase test'}).json()
        self.b = self.http.post('/api/agency/clients', json={'name': 'Keep test'}).json()
        self.prefix = '/api/agency/clients/' + self.a['id']
        self.other = '/api/agency/clients/' + self.b['id']

    def record(self, kind, data=None, prefix=None):
        response = self.http.post((prefix or self.prefix) + '/records/' + kind, json=dict(name='Private test', data=data or {}))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def asset(self, prefix):
        response = self.http.post(prefix + '/assets/register', json=dict(media_url='/renders/' + self.picture.name))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def erase(self, status=200, **changes):
        preview = self.http.get(self.prefix + '/privacy/erasure-preview').json()
        body = dict(expected_version=self.a['version'], confirmation='DELETE CLIENT ' + self.a['id'], review_token=preview['review_token'])
        response = self.http.post(self.prefix + '/privacy/erase', json=dict(body, **changes))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_export_includes_only_selected_client_history_and_actual_files(self):
        self.record('contacts', {'email': 'private@example.com'})
        self.record('contacts', {'email': 'other@example.com'}, self.other)
        asset = self.asset(self.prefix)
        self.asset(self.other)
        response = self.http.post(self.prefix + '/privacy/export')
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            data = archive.read('client-data.json')
            self.assertIn(b'private@example.com', data)
            self.assertNotIn(b'other@example.com', data)
            self.assertTrue(json.loads(data)['revisions'])
            self.assertIn('assets/' + asset['data']['stored_name'], archive.namelist())
            self.assertTrue(json.loads(archive.read('manifest.json'))['files'])

    def test_erasure_phrase_version_hold_and_retention_review(self):
        self.erase(400, confirmation='DELETE')
        self.erase(409, expected_version=99)
        policy = self.record('retention', dict(review_after_days=30, legal_hold=True))
        self.erase(409)
        review = self.http.get(self.prefix + '/privacy/retention-review')
        self.assertEqual(review.status_code, 200, review.text)
        self.assertTrue(review.json()['settings']['legal_hold'])
        response = self.http.put(self.prefix + '/records/retention/' + policy['id'], json=dict(name=policy['name'],
                                 expected_version=policy['version'], data=dict(policy['data'], legal_hold=False)))
        self.assertEqual(response.status_code, 200, response.text)
        self.erase()
        self.assertEqual(self.http.get(self.prefix).status_code, 404)

    def test_erasure_preserves_other_client_and_shared_asset(self):
        shared = self.asset(self.prefix)
        self.asset(self.other)
        campaign = self.record('campaigns', {'objective': 'Test'})
        response = self.http.post(self.prefix + '/records/briefs', json=dict(name='Scoped brief', campaign_id=campaign['id'], data={}))
        self.assertEqual(response.status_code, 201, response.text)
        contact = self.record('contacts', {'email': 'erase@example.com'})
        self.record('contacts', {'email': 'keep@example.com'}, self.other)
        self.erase()
        self.assertTrue((repository.home / 'assets' / shared['data']['stored_name']).is_file())
        self.assertEqual(self.http.get(self.other).status_code, 200)
        records = self.http.get(self.other + '/records?kind=contacts').json()
        self.assertEqual(records['items'][0]['data']['email'], 'keep@example.com')
        with repository.connection() as db:
            for table in ('records', 'revisions', 'documents', 'jobs', 'audit'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table + ' WHERE client_id=?', (self.a['id'],)).fetchone()[0], 0)

    def test_erasure_blocks_running_jobs(self):
        with repository.connection(write=True) as db:
            from agency.database import packed, timestamp
            now = timestamp()
            key = uid()
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)', (key, self.a['id'], 'test', 'running', packed({'id': key}), now, now))
        self.erase(409)

    def test_changed_data_requires_a_fresh_erasure_review(self):
        preview = self.http.get(self.prefix + '/privacy/erasure-preview').json()
        self.record('contacts', {'email': 'new-since-review@example.com'})
        self.erase(409, review_token=preview['review_token'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
