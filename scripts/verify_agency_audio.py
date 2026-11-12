"""Private real-FFmpeg audio render and subtitle validation. Does not mock ASR inference."""
import hashlib
import io
import math
import os
import struct
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-audio-')
os.environ['AGENCY_DATA_DIR'] = str(Path(TEMP.name) / 'agency')
os.environ['VIDEO_DATA_DIR'] = str(Path(TEMP.name) / 'video')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agency.api import router
from agency.database import uid, repository
from agency.security import AgencyRequestLimits

app = FastAPI()
app.include_router(router)
app.add_middleware(AgencyRequestLimits)


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)
        cls.fixture = ROOT / 'output/renders' / ('audio-test-' + uid() + '.wav')
        cls.fixture.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(cls.fixture), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b''.join(struct.pack('<h', round(2000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(32000)))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.unlink(missing_ok=True)

    def setUp(self):
        self.client = self.http.post('/api/agency/clients', json={'name': 'Audio client'}).json()['id']
        self.prefix = '/api/agency/clients/' + self.client

    def record(self, kind, data, status=201):
        response = self.http.post(self.prefix + '/records/' + kind, json=dict(name='Audio test', data=data))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def register(self):
        response = self.http.post(self.prefix + '/assets/register', json=dict(media_url='/renders/' + self.fixture.name, origin='owned'))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def wait(self, job):
        for _ in range(150):
            response = self.http.get(self.prefix + '/jobs/' + job['id'])
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()
            if item['state'] in {'completed', 'failed', 'cancelled'}:
                return item
            time.sleep(.1)
        self.fail('Audio job did not finish within 15 seconds')

    def test_real_trim_normalize_and_private_immutable_asset(self):
        caps = self.http.get('/api/agency/audio/capabilities').json()
        self.assertTrue(caps['ffmpeg'] and caps['ffprobe'], 'This verification requires real FFmpeg and FFprobe')
        asset = self.register()
        project = self.record('audio-projects', dict(asset_id=asset['id'], start_seconds=.25, end_seconds=1.25, normalize=True))
        response = self.http.post(self.prefix + '/audio-projects/' + project['id'] + '/render')
        self.assertEqual(response.status_code, 202, response.text)
        job = self.wait(response.json())
        self.assertEqual(job['state'], 'completed', job)
        result = job['result']
        self.assertEqual(result['data']['parent_asset_id'], asset['id'])
        content = self.http.get(self.prefix + '/assets/' + result['id'] + '/file')
        self.assertEqual(content.status_code, 200, content.text[:100] if content.status_code != 200 else '')
        self.assertEqual(hashlib.sha256(content.content).hexdigest(), result['data']['sha256'])
        with wave.open(io.BytesIO(content.content), 'rb') as wav:
            self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 1, places=2)
            self.assertEqual(wav.getframerate(), 48000)
            self.assertEqual(wav.getnchannels(), 2)
        self.assertTrue((repository.home / 'assets' / result['data']['stored_name']).is_file())
        self.assertEqual(result['data']['original_url'], '')
        other = self.http.post('/api/agency/clients', json={'name': 'Other'}).json()['id']
        self.assertEqual(self.http.get('/api/agency/clients/' + other + '/jobs/' + job['id']).status_code, 404)
        self.assertEqual(self.http.get('/api/agency/clients/' + other + '/assets/' + result['id'] + '/file').status_code, 404)

    def test_captions_actual_timing_rtl_validation_and_safe_vtt(self):
        record = self.record('subtitles', dict(language='ar', cues=[
            dict(start_seconds=0, end_seconds=1.25, text='مرحبا <b>بكم</b>'),
            dict(start_seconds=1.5, end_seconds=3, text='أهلا وسهلا')]))
        srt = self.http.get(self.prefix + '/subtitles/' + record['id'] + '/export').text
        self.assertIn('00:00:00,000 --> 00:00:01,250', srt)
        self.assertIn('أهلا وسهلا', srt)
        vtt = self.http.get(self.prefix + '/subtitles/' + record['id'] + '/export?format=vtt').text
        self.assertTrue(vtt.startswith('WEBVTT'))
        self.assertIn('&lt;b&gt;', vtt)
        self.record('subtitles', dict(cues=[dict(start_seconds=1, end_seconds=2, text='one'), dict(start_seconds=1.5, end_seconds=3, text='two')]), 422)
        self.record('subtitles', dict(cues=[dict(start_seconds=0, end_seconds=.0001, text='too short')]), 422)
        self.record('subtitles', dict(timing_origin='local-asr'), 400)

    def test_optional_asr_is_truthful_and_does_not_download(self):
        caps = self.http.get('/api/agency/audio/capabilities').json()
        self.assertFalse(caps['tts']['available'])
        if not caps['asr']['available']:
            asset = self.register()
            response = self.http.post(self.prefix + '/assets/' + asset['id'] + '/transcribe', json={'language': 'en'})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn('no model is downloaded', response.text.lower())
        self.assertFalse(caps['asr']['verified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
