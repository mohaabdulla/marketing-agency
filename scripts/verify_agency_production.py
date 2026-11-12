"""Offline tests for content production, assets, approvals, publication packages, analytics,
reports and operations. Uses isolated real SQLite, real files and the real Video Studio store."""
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-agency-production-')
os.environ['AGENCY_DATA_DIR'] = str(Path(TEMP.name) / 'agency')
os.environ['VIDEO_DATA_DIR'] = str(Path(TEMP.name) / 'video')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from agency.api import router
from agency.security import AgencyRequestLimits
from agency.database import repository, uid
from agency.production import experiment_statistics, pricing_summary, script_estimate

app = FastAPI()
app.include_router(router)
app.add_middleware(AgencyRequestLimits)
RENDERS = ROOT / 'output/renders'


class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)
        RENDERS.mkdir(parents=True, exist_ok=True)
        cls.files = []

    @classmethod
    def tearDownClass(cls):
        for path in cls.files:
            path.unlink(missing_ok=True)

    def setUp(self):
        self.a = self.post('/api/agency/clients', dict(name='Alpha ' + uid()[:6]))
        self.b = self.post('/api/agency/clients', dict(name='Beta ' + uid()[:6]))
        self.prefix = '/api/agency/clients/' + self.a['id']
        self.campaign = self.record('campaigns', 'Launch', dict(objective='Introduce HomeCell'))

    # ------------------------------------------------------------ helpers
    def post(self, path, body=None, status=201):
        response = self.http.post(path, json=body or {})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def get(self, path, status=200):
        response = self.http.get(path)
        self.assertEqual(response.status_code, status, response.text)
        return response

    def record(self, kind, name, data=None, campaign=None, status=201, prefix=None):
        return self.post((prefix or self.prefix) + '/records/' + kind,
                         dict(name=name, data=data or {}, project_id=None, campaign_id=campaign), status)

    def update(self, item, data, status=200):
        response = self.http.put(self.prefix + '/records/' + item['kind'] + '/' + item['id'], json=dict(
            name=item['name'], data=data, project_id=item['project_id'], campaign_id=item['campaign_id'], expected_version=item['version']))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def picture(self, color=(200, 30, 60), size=(640, 800), ext='.png'):
        path = RENDERS / f'agency-test-{uid()}{ext}'
        Image.new('RGB', size, color).save(path)
        self.files.append(path)
        return '/renders/' + path.name, path

    def asset(self, **meta):
        url, path = self.picture(meta.pop('color', (200, 30, 60)))
        return self.post(self.prefix + '/assets/register', dict(media_url=url, name='Hero', campaign_id=self.campaign['id'], **meta)), path

    def copy(self, text='Keep your villa powered through every summer peak. Book a consultation.', **data):
        return self.record('copy', 'LinkedIn A', dict(format='linkedin_post', text=text, cta='Book a consultation', **data), self.campaign['id'])

    def approve(self, target, reviewer='Sara'):
        request = self.post(self.prefix + '/approvals', dict(target_id=target['id'], reviewer=reviewer))
        return self.post(self.prefix + f'/approvals/{request["id"]}/decision',
                         dict(expected_version=request['version'], decision='approved', reviewer=reviewer), 200)

    # ------------------------------------------------------------ content
    def test_concept_matrix_crosses_only_supplied_options(self):
        result = self.post(self.prefix + f'/campaigns/{self.campaign["id"]}/concept-matrix', dict(axes=dict(
            hook_type=['authority', 'curiosity'], visual_territory=['Product detail', 'Lifestyle'], cta=['Book a consultation'])))
        self.assertEqual(result['combinations'], 4)
        concepts = result['created']
        self.assertEqual({(c['data']['hook_type'], c['data']['visual_territory']) for c in concepts},
                         {('authority', 'Product detail'), ('authority', 'Lifestyle'), ('curiosity', 'Product detail'), ('curiosity', 'Lifestyle')})
        for concept in concepts:
            self.assertEqual(concept['data']['status'], 'proposed')
            self.assertEqual(concept['data']['strategic_rationale'], '')      # nothing invented
            self.assertEqual(concept['campaign_id'], self.campaign['id'])
        self.post(self.prefix + f'/campaigns/{self.campaign["id"]}/concept-matrix',
                  dict(axes=dict(benefit=[f'b{i}' for i in range(5)], cta=[f'c{i}' for i in range(5)])), 400)
        self.post(self.prefix + f'/campaigns/{self.campaign["id"]}/concept-matrix', dict(axes=dict(hook_type=['not-a-hook'])), 422)

    def test_copy_rules_and_deterministic_checks(self):
        self.record('copy', 'No campaign', dict(text='x'), None, 400)
        self.record('copy', 'Bad format', dict(format='telepathy', text='x'), self.campaign['id'], 400)
        first = self.copy()
        checks = lambda **body: self.post(self.prefix + f'/campaigns/{self.campaign["id"]}/copy-checks', body, 200)
        codes = lambda result: {f['code'] for f in result['flags']}
        long_x = checks(format='x_post', text='word ' * 80, cta='Go')
        self.assertIn('length', codes(long_x))
        self.assertEqual(next(f for f in long_x['flags'] if f['code'] == 'length')['severity'], 'block')
        self.assertEqual(next(f for f in checks(format='ad_headline', text='h' * 60, cta='Go')['flags'] if f['code'] == 'length')['severity'], 'review')
        messy = checks(format='linkedin_post', text='Save 45% with [PRODUCT NAME] today, see www.example', cta='')
        self.assertTrue({'placeholder', 'quantitative_claim_needs_evidence', 'missing_cta', 'link_format'} <= codes(messy), messy)
        duplicate = checks(format='linkedin_post', text=first['data']['text'] + ' ', cta='Book')
        self.assertIn('duplicate', codes(duplicate))
        self.assertNotIn('duplicate', codes(checks(format='linkedin_post', text=first['data']['text'], cta='Book', exclude_id=first['id'])))
        self.assertIn('hashtags', codes(checks(format='instagram_caption', text='Hello ' + ' '.join(f'#t{i}' for i in range(31)), cta='Go')))
        self.assertIn('language_mismatch', codes(checks(format='linkedin_post', text='English only', cta='Go', language='ar')))
        clean = checks(format='linkedin_post', text='A calm, specific line about the product.', cta='Learn more')
        self.assertEqual(clean['export_state'], 'checks-passed', clean)
        sms = checks(format='sms', text='مرحبا ' * 15, cta='x', language='ar')
        self.assertEqual(sms['limit'], 70)

    def test_script_estimate_storyboard_and_real_video_project(self):
        scenes = [dict(heading='Open', narration='word ' * 50, on_screen_text='Meet HomeCell', visual='Villa at dusk'),
                  dict(heading='Close', narration='word ' * 25, dialogue='Book today', visual='Family indoors', duration_seconds=20)]
        script = self.record('scripts', 'Launch film', dict(target_duration_seconds=30, hooks=['One two three'], scenes=scenes), self.campaign['id'])
        estimate = script['computed']
        self.assertEqual(estimate['words'], 53 + 27)
        self.assertAlmostEqual(estimate['scenes'][0]['spoken_seconds'], 53 * 60 / 150, 1)
        self.assertEqual(estimate['scenes'][1]['planned_seconds'], 20.0)       # entered duration is longer than speech
        self.assertGreater(estimate['over_target_seconds'], 0)
        arabic = script_estimate(dict(script['data'], language='ar'))
        self.assertGreater(arabic['estimated_seconds'], script_estimate(dict(script['data'], scenes=script['data']['scenes'][:1]))['estimated_seconds'])
        self.assertAlmostEqual(arabic['scenes'][0]['spoken_seconds'], 53 * 60 / 120, 1)

        made = self.post(self.prefix + f'/scripts/{script["id"]}/storyboard')
        board, shots = made['storyboard'], made['shots']
        self.assertEqual([s['data']['sequence'] for s in shots], [1, 2])
        self.assertEqual(shots[0]['data']['voiceover'], scenes[0]['narration'].strip())
        self.assertEqual(shots[0]['data']['image_prompt'], '')                 # prompts are the operator's to write
        self.assertEqual(shots[0]['campaign_id'], self.campaign['id'])          # inherited from the storyboard
        self.record('shots', 'Orphan', dict(storyboard_id=uid()), None, 404)

        asset, _ = self.asset()
        self.update(shots[0], dict(shots[0]['data'], image_asset_id=asset['id']))
        listed = self.get(self.prefix + f'/storyboards/{board["id"]}/shots').json()
        self.assertEqual(len(listed['shots']), 2)
        project = self.post(self.prefix + f'/storyboards/{board["id"]}/video-project')
        self.assertEqual((project['shots'], project['slates']), (2, 1))
        saved = json.loads((Path(os.environ['VIDEO_DATA_DIR']) / 'projects' / (project['video_project_id'] + '.json')).read_text(encoding='utf-8'))
        self.assertEqual((saved['canvas']['width'], saved['canvas']['height']), (720, 1280))
        kinds = [c['kind'] for c in saved['clips']]
        self.assertEqual(kinds.count('video'), 2)
        self.assertEqual([c['text'] for c in saved['clips'] if c['kind'] == 'title'], ['Meet HomeCell'])
        videos = [c for c in saved['clips'] if c['kind'] == 'video']
        self.assertEqual(videos[1]['start'], videos[0]['duration'])
        for clip in videos:                                                    # every clip points at a real stored file
            self.assertTrue(any((Path(os.environ['VIDEO_DATA_DIR']) / 'assets').glob(clip['asset_id'] + '.*')))
        srt = self.get(self.prefix + f'/storyboards/{board["id"]}/captions?format=srt')
        cues = [block.split('\n') for block in srt.text.strip().split('\n\n')]
        self.assertEqual(cues[0][0:2], ['1', '00:00:00,000 --> ' + cues[0][1].split(' --> ')[1]])
        self.assertTrue(all(len(line) <= 42 for cue in cues for line in cue[2:]) and all(len(cue) <= 4 for cue in cues))
        self.assertEqual(cues[-1][1].split(' --> ')[1], '00:00:41,200')            # 21.2s scene + 20s scene, planned
        self.assertEqual(int(srt.headers['x-caption-cues']), len(cues))
        vtt = self.get(self.prefix + f'/storyboards/{board["id"]}/captions?format=vtt').text
        self.assertTrue(vtt.startswith('WEBVTT\n\n00:00:00.000 --> '))
        caption_file = RENDERS / f'agency-test-{uid()}.srt'
        caption_file.write_text(srt.text, encoding='utf-8')
        self.files.append(caption_file)
        registered = self.post(self.prefix + '/assets/register', dict(media_url='/renders/' + caption_file.name, language='en'))
        self.assertEqual(registered['data']['asset_type'], 'subtitle')
        empty = self.record('storyboards', 'Silent', {}, self.campaign['id'])
        self.get(self.prefix + f'/storyboards/{empty["id"]}/captions', 400)
        export = self.get(self.prefix + f'/storyboards/{board["id"]}/export')
        with zipfile.ZipFile(io.BytesIO(export.content)) as bundle:
            names = bundle.namelist()
            self.assertIn('storyboard.html', names)
            self.assertTrue(any(n.startswith('images/shot-01') for n in names))
            self.assertIn('Villa at dusk', bundle.read('storyboard.html').decode('utf-8'))

    # ------------------------------------------------------------ assets
    def test_asset_registration_integrity_and_versions(self):
        asset, path = self.asset(origin='generated', generation_note=dict(model='local:realvisxl-v5', seed='42', prompt='villa at dusk'))
        data = asset['data']
        self.assertEqual(data['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual((data['asset_type'], data['width'], data['height'], data['mime']), ('image', 640, 800, 'image/png'))
        self.assertEqual(data['generation_note']['model'], 'local:realvisxl-v5')
        stored = repository.home / 'assets' / data['stored_name']
        self.assertEqual(stored.read_bytes(), path.read_bytes())
        self.assertNotIn(str(repository.home), json.dumps(asset))               # no filesystem paths in responses
        for bad in ('/renders/../server.py', 'http://example.com/a.png', '/renders/missing.png', '/renders/a.png?x=1', 'C:\\Windows\\win.ini', '/etc/passwd'):
            response = self.http.post(self.prefix + '/assets/register', json=dict(media_url=bad))
            self.assertIn(response.status_code, (400, 404), bad)
        fake = RENDERS / f'agency-test-{uid()}.png'
        fake.write_text('<script>alert(1)</script>')
        self.files.append(fake)
        self.assertEqual(self.http.post(self.prefix + '/assets/register', json=dict(media_url='/renders/' + fake.name)).status_code, 400)
        self.record('assets', 'Manual', dict(asset_type='image', sha256='0' * 64, size=1, mime='x', stored_name='0' * 64 + '.png'), None, 400)
        self.update(asset, dict(data, sha256='1' * 64), 409)
        edited = self.update(asset, dict(data, notes='Hero for the launch', tags=['hero']))
        self.assertEqual(edited['version'], 2)

        new_url, new_path = self.picture((10, 120, 200))
        self.post(self.prefix + f'/assets/{asset["id"]}/version', dict(expected_version=edited['version'], media_url='/renders/' + path.name), 409)
        third = self.post(self.prefix + f'/assets/{asset["id"]}/version', dict(expected_version=edited['version'], media_url=new_url), 200)
        self.assertEqual(third['version'], 3)
        self.assertEqual(third['data']['notes'], 'Hero for the launch')
        self.assertEqual(self.get(self.prefix + f'/assets/{asset["id"]}/file?version=1').content, path.read_bytes())
        self.assertEqual(self.get(self.prefix + f'/assets/{asset["id"]}/file').content, new_path.read_bytes())
        self.assertTrue(stored.is_file())                                       # the superseded file is retained
        self.get(self.prefix + f'/assets/{asset["id"]}/file?version=9', 404)
        self.get('/api/agency/clients/' + self.b['id'] + f'/assets/{asset["id"]}/file', 404)

    def test_backup_and_restore_carry_every_asset_version(self):
        from agency.exports import backup_bundle, restore_bundle
        asset, first_file = self.asset()
        new_url, second_file = self.picture((5, 5, 90))
        self.post(self.prefix + f'/assets/{asset["id"]}/version', dict(expected_version=1, media_url=new_url), 200)
        backup = backup_bundle()
        self.assertGreaterEqual(backup['assets'], 2)
        archive = repository.home / 'backups' / (backup['id'] + '.zip')
        target = Path(TEMP.name) / ('restore-' + uid())
        restore_bundle(archive, target)
        for original in (first_file, second_file):
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            self.assertEqual((target / 'assets' / (digest + '.png')).read_bytes(), original.read_bytes())
        tampered = Path(TEMP.name) / ('tampered-' + uid() + '.zip')
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, 'w') as out:
            for entry in source.infolist():
                payload = source.read(entry.filename)
                out.writestr(entry.filename, payload[:-1] + b'X' if entry.filename.startswith('assets/') else payload)
        with self.assertRaises(ValueError):
            restore_bundle(tampered, Path(TEMP.name) / ('restore-' + uid()))
        archive.unlink()
        archive.with_suffix('.sqlite3').unlink()
        archive.with_suffix('.json').unlink()

    # ------------------------------------------------------------ approvals
    def test_approvals_bind_to_the_exact_version(self):
        asset, _ = self.asset()
        request = self.post(self.prefix + '/approvals', dict(target_id=asset['id'], reviewer='Sara', note='Final hero?'))
        self.assertEqual((request['data']['target_version'], request['data']['target_sha256']), (1, asset['data']['sha256']))
        self.assertEqual(self.get(self.prefix + f'/record/{asset["id"]}/approval-state').json()['state'], 'in-review')
        self.assertEqual(self.http.put(self.prefix + f'/records/approvals/{request["id"]}', json=dict(
            name='x', data=dict(request['data'], state='approved'), expected_version=1)).status_code, 400)
        self.record('approvals', 'Forged', dict(request['data'], state='approved'), None, 400)
        noted = self.post(self.prefix + f'/approvals/{request["id"]}/comments',
                          dict(expected_version=1, author='Sara', text='Logo is too close to the edge', timecode_seconds=2.5), 200)
        self.post(self.prefix + f'/approvals/{request["id"]}/decision', dict(expected_version=noted['version'], decision='rejected', reviewer='Sara'), 400)
        self.post(self.prefix + f'/approvals/{request["id"]}/decision', dict(expected_version=1, decision='approved', reviewer='Sara'), 409)
        done = self.post(self.prefix + f'/approvals/{request["id"]}/decision',
                         dict(expected_version=noted['version'], decision='approved', reviewer='Sara'), 200)['approval']
        self.assertEqual(done['data']['state'], 'approved')
        self.assertEqual([c['decision'] for c in done['data']['comments']], ['', 'approved'])
        self.assertEqual(self.get(self.prefix + f'/record/{asset["id"]}/approval-state').json()['state'], 'approved')
        self.post(self.prefix + f'/approvals/{request["id"]}/decision', dict(expected_version=done['version'], decision='rejected', reviewer='X', text='late'), 409)

        # Any change to the approved record is a new version: the approval no longer covers it.
        self.update(asset, dict(asset['data'], notes='tweaked after approval'))
        self.assertEqual(self.get(self.prefix + f'/record/{asset["id"]}/approval-state').json()['state'], 'not-approved')
        current = self.get(self.prefix + f'/record/{request["id"]}').json()
        self.assertEqual(current['data']['state'], 'superseded')
        actions = [a['action'] for a in self.get(self.prefix + '/audit?limit=100').json()['items']]
        for action in ('approval.commented', 'approval.approved', 'approval.superseded'):
            self.assertIn(action, actions)
        self.post('/api/agency/clients/' + self.b['id'] + '/approvals', dict(target_id=asset['id'], reviewer='Eve'), 404)
        project = self.record('projects', 'Not approvable')
        self.post(self.prefix + '/approvals', dict(target_id=project['id'], reviewer='Sara'), 400)

    def test_approved_brief_opens_production_tasks_once(self):
        brief = self.record('briefs', 'Brief', dict(primary_message='Hello'), self.campaign['id'])
        self.record('deliverables', 'Feed post EN', dict(platform='LinkedIn', due_date='2030-01-10', owner='Mona'), self.campaign['id'])
        self.record('deliverables', 'Old banner', dict(state='cancelled'), self.campaign['id'])
        result = self.approve(brief)
        self.assertEqual(result['workflow']['tasks_created'], ['Produce: Feed post EN'])
        tasks = self.get(self.prefix + '/records?kind=tasks').json()['items']
        full = self.get(self.prefix + f'/record/{tasks[0]["id"]}').json()
        self.assertEqual((full['data']['origin'], full['data']['due_date'], full['data']['owner']), ('workflow-rule', '2030-01-10', 'Mona'))
        revised = self.update(brief, dict(brief['data'], primary_message='Hello again'))
        self.assertEqual(self.approve(revised)['workflow']['tasks_created'], [])   # idempotent

    # ------------------------------------------------------------ publication package
    def test_publication_package_needs_approved_versions_and_rights(self):
        asset, path = self.asset()
        copy = self.copy(headline='HomeCell is here', hashtags=['#HomeCell'])
        entry = self.record('calendar', 'Launch post', dict(channel='LinkedIn', scheduled_date='2030-02-01', copy_id=copy['id'],
                                                            asset_ids=[asset['id']], alt_text='A villa at dusk'), self.campaign['id'])
        self.record('calendar', 'Bad zone', dict(channel='X', scheduled_date='2030-02-01', timezone='Mars/Olympus'), self.campaign['id'], 422)
        package = lambda draft: self.http.get(self.prefix + f'/calendar/{entry["id"]}/package?draft={str(draft).lower()}')
        blocked = package(False)
        self.assertEqual(blocked.status_code, 409)
        for phrase in ('not-approved', 'Usage rights are not recorded'):
            self.assertIn(phrase, blocked.json()['detail'])
        draft = package(True)
        self.assertEqual(draft.status_code, 200)
        self.assertIn('DRAFT', draft.headers['content-disposition'])
        with zipfile.ZipFile(io.BytesIO(draft.content)) as bundle:
            meta = json.loads(bundle.read('metadata.json'))
            self.assertFalse(meta['cleared'])
            self.assertTrue(bundle.read('posting-checklist.txt').decode().startswith('DRAFT FOR REVIEW'))

        licence = self.record('licenses', 'Generated in-house', dict(license_type='generated', owner='Alpha'))
        asset = self.update(asset, dict(asset['data'], license_id=licence['id']))
        self.approve(asset)
        self.approve(copy)
        final = package(False)
        self.assertEqual(final.status_code, 200, final.text)
        self.assertNotIn('DRAFT', final.headers['content-disposition'])
        with zipfile.ZipFile(io.BytesIO(final.content)) as bundle:
            names = set(bundle.namelist())
            self.assertTrue({'caption.txt', 'title.txt', 'alt-text.txt', 'hashtags.txt', 'disclosure.txt', 'thumbnail.jpg',
                             'metadata.json', 'posting-checklist.txt'} <= names, names)
            meta = json.loads(bundle.read('metadata.json'))
            media = meta['media'][0]
            self.assertEqual(hashlib.sha256(bundle.read(media['file'])).hexdigest(), media['sha256'])
            self.assertEqual(bundle.read(media['file']), path.read_bytes())
            self.assertEqual((meta['cleared'], meta['publishes_externally'], meta['publication_authorized']), (True, False, False))
            self.assertEqual(bundle.read('title.txt').decode(), 'HomeCell is here')
            self.assertIn('Book a consultation', bundle.read('caption.txt').decode())
        self.assertEqual(self.get(self.prefix + f'/record/{entry["id"]}').json()['data']['publish_status'], 'package-exported')
        # Editing the approved copy withdraws clearance for the next final export.
        self.update(copy, dict(copy['data'], text=copy['data']['text'] + ' Now.'))
        self.assertEqual(package(False).status_code, 409)
        schedule = self.get(self.prefix + '/schedule?start=2030-01-01&end=2030-12-31').json()
        self.assertEqual([i['id'] for i in schedule['items']], [entry['id']])

    # ------------------------------------------------------------ analytics, experiments, reports
    def test_csv_import_is_atomic_and_summary_is_exact(self):
        clicks = self.record('metrics', 'Clicks', dict(unit='clicks'))
        self.record('metrics', 'CTR', dict(unit='%', aggregation='mean'))
        upload = lambda text, name='data.csv': self.http.post(self.prefix + '/analytics/import?campaign_id=' + self.campaign['id'],
                                                              files={'file': (name, text.encode('utf-8'), 'text/csv')})
        count = lambda: self.get(self.prefix + '/records?kind=snapshots').json()['total']
        self.assertEqual(upload('date,metric,value\n2030-01-01,Clicks,10\n2030-01-02,Unknown metric,5\n').status_code, 400)
        self.assertEqual(upload('date,metric,value\n2030-01-01,Clicks,10\nnot-a-date,Clicks,5\n').status_code, 400)
        self.assertEqual(upload('date,value\n2030-01-01,10\n').status_code, 400)
        self.assertEqual(upload('date,metric,value\n2030-01-01,Clicks,10\n', 'data.txt').status_code, 400)
        self.assertEqual(count(), 0)                                           # nothing partially saved
        good = upload('date,metric,value,channel\n2030-01-01,Clicks,100,LinkedIn\n2030-01-01,clicks,50,Instagram\n'
                      '2030-01-08,Clicks,180,LinkedIn\n2030-01-01,CTR,2.0,LinkedIn\n2030-01-08,CTR,3.0,LinkedIn\n')
        self.assertEqual(good.status_code, 201, good.text)
        self.assertEqual((good.json()['imported'], count()), (5, 5))
        summary = {m['name']: m for m in self.get(self.prefix + '/analytics/summary?campaign_id=' + self.campaign['id']).json()['metrics']}
        c = summary['Clicks']
        self.assertEqual([p['value'] for p in c['series']], [150.0, 180.0])
        self.assertEqual((c['change'], c['overall'], c['by_channel']), (30.0, 330.0, {'Instagram': 50.0, 'LinkedIn': 280.0}))
        self.assertAlmostEqual(c['change_percent'], 20.0)
        self.assertEqual((summary['CTR']['overall'], summary['CTR']['change']), (2.5, 1.0))
        windowed = self.get(self.prefix + '/analytics/summary?start=2030-01-05').json()['metrics']
        self.assertEqual(next(m for m in windowed if m['name'] == 'Clicks')['observations'], 1)
        self.assertEqual(self.get('/api/agency/clients/' + self.b['id'] + '/analytics/summary').json()['metrics'], [])
        self.record('snapshots', 'Manual', dict(metric_id=clicks['id'], date='2030-01-09', value=5))
        self.record('snapshots', 'Other client metric', dict(metric_id=clicks['id'], date='2030-01-09', value=5),
                    prefix='/api/agency/clients/' + self.b['id'], status=404)

    def test_experiment_statistics_are_computed_not_narrated(self):
        variants = [dict(label='Control', is_control=True, sample_size=1000, conversions=100),
                    dict(label='Curiosity hook', sample_size=1000, conversions=130)]
        experiment = self.record('experiments', 'Hook test', dict(hypothesis='A curiosity hook lifts clicks', variants=variants,
                                                                  conclusion='It was a landslide, 99% better'))
        row = experiment['computed']['comparisons'][0]
        pooled = 230 / 2000
        z = (0.13 - 0.10) / math.sqrt(pooled * (1 - pooled) * (2 / 1000))
        self.assertAlmostEqual(row['z'], z, 9)
        self.assertAlmostEqual(row['p_value'], math.erfc(abs(z) / math.sqrt(2)), 9)
        self.assertTrue(row['significant'])
        self.assertAlmostEqual(row['relative_lift'], 0.3, 9)
        self.assertLess(row['difference_ci95'][0], 0.03)
        self.assertGreater(row['difference_ci95'][1], 0.03)
        small = experiment_statistics([dict(label='C', is_control=True, sample_size=40, conversions=4), dict(label='T', is_control=False, sample_size=40, conversions=9)])
        self.assertFalse(small['computed'])
        self.assertIsNone(small['comparisons'][0]['significant'])
        two = experiment_statistics([dict(label='C', is_control=True, sample_size=1000, conversions=100),
                                     dict(label='A', is_control=False, sample_size=1000, conversions=130),
                                     dict(label='B', is_control=False, sample_size=1000, conversions=131)])
        self.assertEqual(two['alpha_per_comparison'], 0.025)
        self.assertFalse(two['comparisons'][0]['significant'])                  # p≈0.036 does not pass the corrected threshold
        self.assertFalse(experiment_statistics([dict(label='C', is_control=True, sample_size=None, conversions=None),
                                                dict(label='T', is_control=False, sample_size=10, conversions=1)])['computed'])
        self.record('experiments', 'Two controls', dict(hypothesis='x', variants=[dict(label='A', is_control=True), dict(label='B', is_control=True)]), None, 422)
        self.record('experiments', 'Too many conversions', dict(hypothesis='x', variants=[dict(label='A', is_control=True, sample_size=5, conversions=6)]), None, 422)

    def test_report_facts_come_only_from_stored_data(self):
        metric = self.record('metrics', 'Clicks', dict(unit='clicks'))
        for day, value in (('2030-03-01', 120), ('2030-03-15', 180), ('2030-04-20', 999)):
            self.record('snapshots', 'c ' + day, dict(metric_id=metric['id'], date=day, value=value, channel='LinkedIn'), self.campaign['id'])
        experiment = self.record('experiments', 'Hook test', dict(hypothesis='Curiosity wins', variants=[
            dict(label='Control', is_control=True, sample_size=1000, conversions=100), dict(label='Curiosity', sample_size=1000, conversions=130)]))
        self.record('reports', 'Backwards', dict(period_start='2030-03-31', period_end='2030-03-01'), self.campaign['id'], 422)
        report = self.record('reports', 'March report', dict(
            period_start='2030-03-01', period_end='2030-03-31', metric_ids=[metric['id']], experiment_ids=[experiment['id']],
            executive_summary='Clicks exploded to 5,000 <script>alert(1)</script>', interpretation='Audiences liked the hook.',
            recommendations=['Test a second curiosity hook']), self.campaign['id'])
        response = self.get(self.prefix + f'/reports/{report["id"]}/render')
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            page = bundle.read('report.html').decode('utf-8')
            data = bundle.read('data.csv').decode('utf-8-sig')
            stored = json.loads(bundle.read('report.json'))
        self.assertIn('Clicks increased from 120 clicks on 2030-03-01 to 180 clicks on 2030-03-15 (+50.0%).', page)
        self.assertIn('Total for the period: 300 clicks from 2 recorded values.', page)
        self.assertNotIn('999', page)                                           # outside the report period
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)
        facts = page.split('KPI performance')[1].split('Interpretation')[0]
        self.assertNotIn('5,000', facts)                                        # narrative cannot leak into the fact section
        self.assertIn('p=0.0355', page)
        self.assertIn('statistically significant', page)
        self.assertEqual(data.splitlines()[1:], ['Clicks,clicks,2030-03-01,120.0,sum', 'Clicks,clicks,2030-03-15,180.0,sum'])
        self.assertEqual(stored['metrics']['metrics'][0]['overall'], 300.0)

    # ------------------------------------------------------------ operations and knowledge
    def test_pricing_arithmetic_tasks_learning_and_overview(self):
        pricing = self.record('pricing', 'Retainer + media', dict(
            fee_model='hybrid', internal_hourly_cost=20, expected_hours=100, billable_rate=0, monthly_retainer=1500, retainer_months=3,
            media_spend=10000, media_fee_percent=10, pass_through_costs=800, pass_through_markup_percent=5, discount_percent=10,
            other_internal_costs=250, target_margin_percent=50))['computed']
        self.assertEqual((pricing['gross_fees'], pricing['discount'], pricing['pass_through_markup']), (5500.0, 550.0, 40.0))
        self.assertEqual((pricing['agency_revenue'], pricing['internal_cost'], pricing['gross_margin']), (4990.0, 2250.0, 2740.0))
        self.assertEqual(pricing['gross_margin_percent'], 54.91)
        self.assertEqual((pricing['revenue_needed_for_target_margin'], pricing['meets_target']), (4500.0, True))
        self.assertEqual((pricing['client_invoice_total'], pricing['external_spend_not_revenue']), (5790.0, 10000.0))
        empty = pricing_summary(dict(self.get('/api/agency/schemas').json()['records']['pricing']['properties'] and {
            k: 0 for k in ('internal_hourly_cost', 'expected_hours', 'billable_rate', 'fixed_fee', 'monthly_retainer', 'retainer_months',
                           'package_price', 'package_quantity', 'media_spend', 'media_fee_percent', 'performance_fee', 'other_internal_costs',
                           'pass_through_costs', 'pass_through_markup_percent', 'discount_percent', 'target_margin_percent')}, currency='BHD'))
        self.assertIsNone(empty['gross_margin_percent'])                        # no division by zero, no invented default
        first = self.record('tasks', 'Write script', dict(due_date='2020-01-01'))
        second = self.record('tasks', 'Shoot', dict(depends_on_ids=[first['id']]))
        self.update(second, dict(second['data'], depends_on_ids=[second['id']]), 400)
        self.assertEqual(self.http.post(self.prefix + f'/record/{first["id"]}/archive', json=dict(expected_version=1)).status_code, 409)
        self.record('learnings', 'Unproven', dict(finding='Curiosity hooks win', status='validated'), None, 422)
        experiment = self.record('experiments', 'Hook test', dict(hypothesis='x', status='running'))
        self.record('learnings', 'Proven', dict(finding='Curiosity hooks win', status='validated', experiment_ids=[experiment['id']]))
        self.record('scope', 'Feed posts', dict(deliverable='Feed post', quantity=8))
        self.record('costs', 'Stock photo', dict(category='external-expense', amount=12.5, pass_through=True))
        asset, _ = self.asset()
        self.post(self.prefix + '/approvals', dict(target_id=asset['id'], reviewer='Sara'))
        overview = self.get(self.prefix + '/overview').json()
        self.assertEqual((overview['awaiting_approval'], overview['open_tasks'], overview['overdue_tasks'], overview['running_experiments'],
                          overview['registered_assets'], overview['assets_without_rights']), (1, 2, 1, 1, 1, 1))
        self.assertEqual(self.get('/api/agency/clients/' + self.b['id'] + '/overview').json()['registered_assets'], 0)
        specs = self.get('/api/agency/channel-specs').json()
        self.assertEqual(specs['formats']['x_post']['max_chars'], 280)
        self.assertIn('not been re-verified', specs['notice'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
