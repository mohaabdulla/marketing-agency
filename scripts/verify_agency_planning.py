"""Real planning arithmetic, linked creator briefs, lineage and dependency cycles."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-planning-')
os.environ['AGENCY_DATA_DIR'] = str(Path(TEMP.name) / 'agency')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agency.api import router
from agency.security import AgencyRequestLimits
app = FastAPI()
app.include_router(router)
app.add_middleware(AgencyRequestLimits)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(app)
        self.client = self.http.post('/api/agency/clients', json=dict(name='Planning test')).json()['id']
        self.prefix = '/api/agency/clients/' + self.client
        self.campaign = self.record('campaigns', dict(objective='Launch'))

    def record(self, kind, data, status=201):
        response = self.http.post(self.prefix + '/records/' + kind, json=dict(name='Plan', data=data,
                                  campaign_id=getattr(self, 'campaign', {}).get('id')))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_paid_arithmetic_utm_export_and_missing_assumptions(self):
        plan = self.record('paid-plans', dict(objective='Leads', daily_budget=10, days=30, assumed_cpc=2,
                           assumed_conversion_percent=10, destination_url='https://example.com/a?ref=keep&utm_source=old#form',
                           utm_source='linkedin', utm_campaign='Solar launch'))
        result = self.http.get(self.prefix + '/paid-plans/' + plan['id'] + '/scenario').json()
        self.assertEqual(result['planned_external_ad_spend'], 300)
        self.assertEqual(result['scenario_clicks'], 150)
        self.assertEqual(result['scenario_conversions'], 15)
        self.assertIn('ref=keep&utm_source=linkedin&utm_medium=paid&utm_campaign=Solar+launch#form', result['tracked_url'])
        self.assertIn('AD SPEND IS EXTERNAL', result['notice'])
        response = self.http.get(self.prefix + '/planning/' + plan['id'] + '/export')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(json.loads(archive.read('plan.json'))['computed']['planned_external_ad_spend'], 300)
            self.assertIn('Nothing was sent', archive.read('review-checklist.txt').decode())
        unknown = self.record('paid-plans', dict(objective='Unknown forecast', daily_budget=20))
        self.assertIsNone(self.http.get(self.prefix + '/paid-plans/' + unknown['id'] + '/scenario').json()['scenario_clicks'])

    def test_creator_and_organic_lineage_with_client_isolation(self):
        creator = self.record('creators', dict(handle='@public', source='Client provided'))
        brief = self.record('creator-briefs', dict(creator_id=creator['id'], disclosure_text='Paid partnership',
                            deliverables=['One short'], paid_use=False))
        self.assertTrue(brief['data']['disclosure_required'])
        pillar = self.record('content-pillars', dict(purpose='Educate', topics=['Solar']))
        series = self.record('content-series', dict(pillar_id=pillar['id'], recurring_concept='Explain a solar question'))
        self.assertEqual(series['reference_versions'][0]['version'], 1)
        other = self.http.post('/api/agency/clients', json=dict(name='Other')).json()['id']
        response = self.http.post('/api/agency/clients/' + other + '/records/content-series', json=dict(name='Bad link', data=dict(pillar_id=pillar['id'])))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.http.get(self.prefix + '/planning/' + series['id'] + '/export').status_code, 200)

    def test_task_cycle_is_rejected_transactionally(self):
        first = self.record('tasks', {})
        second = self.record('tasks', dict(depends_on_ids=[first['id']]))
        response = self.http.put(self.prefix + '/records/tasks/' + first['id'], json=dict(name=first['name'],
                                 campaign_id=first['campaign_id'], data=dict(first['data'], depends_on_ids=[second['id']]), expected_version=1))
        self.assertEqual(response.status_code, 400, response.text)
        current = self.http.get(self.prefix + '/record/' + first['id']).json()
        self.assertEqual(current['version'], 1)
        self.assertEqual(current['data']['depends_on_ids'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
