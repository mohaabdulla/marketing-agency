"""Motion footage for storyboard videos: real photos instead of logo cards, the company's own website
videos, and licensed stock video (Pexels / Pixabay) with credits.

Run: python scripts/test_video_footage.py
Offline: the company website, the stock libraries and their downloads are local fixtures shaped like the
documented API responses; video files are generated with FFmpeg. Nothing is sent to any service.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='video-footage-suite-')
os.environ.update(PUBLIC_TEST_MODE='true', PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name) / 'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name) / 'video'), AGENCY_DATA_DIR=str(Path(TEMP.name) / 'agency'))
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter
import agency.research
import server
from brand import kits as brand_kits
from image import campaign_generator
from video import brief_assistant, company_intro, stock
from video.ffmpeg import ffmpeg, probe

SITE = 'https://acme-robotics.example'
MEDIA = Path(TEMP.name) / 'media'
MEDIA.mkdir()


def photo(seed, size=(1600, 1000)):
    """A photograph stand-in: textured, many colours, no flat areas."""
    rng = np.random.default_rng(seed)
    field = rng.normal(size=(size[1] // 4, size[0] // 4, 3)).cumsum(axis=0).cumsum(axis=1)
    field = ((field - field.min()) / np.ptp(field) * 255).astype('uint8')
    image = Image.fromarray(field).resize(size).filter(ImageFilter.GaussianBlur(1))
    out = io.BytesIO(); image.save(out, 'JPEG', quality=90)
    return out.getvalue()


def logo_card():
    """The kind of Open Graph image that caused the problem: a logo on a flat background."""
    image = Image.new('RGB', (1200, 630), '#050505')
    draw = ImageDraw.Draw(image)
    draw.polygon([(60, 200), (200, 315), (60, 430)], fill='#5fd16b')
    draw.rectangle((260, 230, 1100, 400), fill='#2d2d2d')
    out = io.BytesIO(); image.save(out, 'JPEG', quality=70)
    return out.getvalue()


def clip(name, seconds, size='1280x720', audio=True):
    path = MEDIA / name
    args = ['-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=30:duration={seconds}']
    if audio:
        args += ['-f', 'lavfi', '-i', f'sine=frequency=880:duration={seconds}', '-c:a', 'aac']
    ffmpeg([*args, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-shortest', str(path)])
    return path.read_bytes()


HOME = f'''<html lang="en"><head><title>Acme Robotics | Warehouse robots</title>
<meta property="og:image" content="/share/og-card.jpg"><meta name="theme-color" content="#0A3D62">
<meta name="description" content="Acme Robotics builds autonomous warehouse robots for logistics teams."></head><body>
<h1>Robots that keep warehouses moving</h1>
<video autoplay muted loop playsinline poster="/media/poster.jpg"><source src="/media/hero.mp4" type="video/mp4"></video>
<p>Acme Robotics designs and builds autonomous mobile robots that move goods safely through busy warehouses every day.</p>
<p>Our fleet software plans routes, balances work across robots and reports throughput to operations managers in real time.</p>
<img src="/photos/floor.jpg" alt="Robots on the warehouse floor" width="1600"><img src="/photos/team.jpg" alt="Engineering team">
<a href="/about">About us</a></body></html>'''
ABOUT = '''<html><body><h1>About Acme Robotics</h1><p>Founded by logistics engineers, Acme Robotics serves retailers and
third-party logistics providers across the region with robots, software and on-site support.</p></body></html>'''


class Site:
    def __init__(self):
        self.files = {f'{SITE}/': ('text/html', HOME.encode()), f'{SITE}/about': ('text/html', ABOUT.encode()),
                      f'{SITE}/share/og-card.jpg': ('image/jpeg', logo_card()),
                      f'{SITE}/photos/floor.jpg': ('image/jpeg', photo(1)), f'{SITE}/photos/team.jpg': ('image/jpeg', photo(2)),
                      f'{SITE}/media/hero.mp4': ('video/mp4', clip('hero.mp4', 8))}
        self.requested = []

    def fetch(self, url, path=None, max_bytes=None, public_page=False, include_headers=False):
        url = url if url.startswith(SITE) else url
        self.requested.append(url)
        key = url if url in self.files else url.rstrip('/') + '/' if url.rstrip('/') + '/' in self.files else url
        if key not in self.files:
            return (404, 'text/plain', b'missing')
        mime, body = self.files[key]
        if max_bytes and len(body) > max_bytes:
            raise ValueError('Research response is compressed or exceeds its size limit')
        return (200, mime, body, {}) if include_headers else (200, mime, body)


class StockLibrary:
    """Pexels and Pixabay responses in their documented shapes, with local downloads."""

    def __init__(self):
        self.calls = []
        self.downloads = {
            'https://videos.pexels.example/robot-arm-hd.mp4': clip('pexels-hd.mp4', 12),
            'https://videos.pexels.example/robot-arm-sd.mp4': clip('pexels-sd.mp4', 12, '640x360'),
            'https://cdn.pixabay.example/warehouse-medium.mp4': clip('pixabay-medium.mp4', 9),
            'https://images.pexels.example/robot-arm.jpg': photo(3, (640, 360)),
            'https://cdn.pixabay.example/warehouse-thumb.jpg': photo(4, (640, 360)),
        }

    def get(self, url, params=None, headers=None, timeout=None, stream=False, allow_redirects=True):
        self.calls.append(dict(url=url, params=params, headers=headers))
        if 'api.pexels.com' in url:
            assert headers == {'Authorization': 'pexels-test-key'}, headers
            return Response(200, json.dumps(dict(page=1, per_page=8, total_results=1, videos=[dict(
                id=1001, width=1920, height=1080, url='https://www.pexels.com/video/robot-arm-1001/', image='https://images.pexels.example/robot-arm.jpg',
                duration=12, user=dict(id=7, name='Dana Lens', url='https://www.pexels.com/@dana'),
                video_files=[dict(id=1, quality='hd', file_type='video/mp4', width=1280, height=720, fps=30, link='https://videos.pexels.example/robot-arm-hd.mp4'),
                             dict(id=2, quality='sd', file_type='video/mp4', width=640, height=360, fps=30, link='https://videos.pexels.example/robot-arm-sd.mp4')],
                video_pictures=[dict(id=1, picture='https://images.pexels.example/robot-arm.jpg', nr=0)])])).encode())
        if 'pixabay.com/api/videos' in url:
            assert params['key'] == 'pixabay-test-key'
            return Response(200, json.dumps(dict(total=2, totalHits=2, hits=[
                dict(id=2002, pageURL='https://pixabay.com/videos/warehouse-2002/', type='film', tags='warehouse, logistics', duration=9,
                     videos=dict(medium=dict(url='https://cdn.pixabay.example/warehouse-medium.mp4', width=1280, height=720, size=1, thumbnail='https://cdn.pixabay.example/warehouse-thumb.jpg'),
                                 tiny=dict(url='https://cdn.pixabay.example/warehouse-medium.mp4', width=640, height=360, size=1, thumbnail='https://cdn.pixabay.example/warehouse-thumb.jpg')),
                     user_id=55, user='pixa_maker'),
                dict(id=2003, pageURL='https://pixabay.com/videos/vertical-2003/', type='film', tags='vertical', duration=20,
                     videos=dict(medium=dict(url='https://cdn.pixabay.example/vertical.mp4', width=1080, height=1920, size=1, thumbnail='')), user_id=56, user='tall')])).encode())
        if url in self.downloads:
            return Response(200, self.downloads[url], 'video/mp4' if url.endswith('.mp4') else 'image/jpeg')
        return Response(404, b'missing')


class Response:
    def __init__(self, status, body, content_type='application/json'):
        self.status_code, self.body, self.headers, self.is_redirect = status, body, {'Content-Type': content_type}, False

    def json(self):
        return json.loads(self.body)

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def close(self):
        pass


def fake_model(system, evidence):
    raise ValueError('No configured text model')   # the offline template writer is used


class Footage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.site, cls.library = Site(), StockLibrary()
        store = Path(TEMP.name) / 'brands.json'
        shutil.copy(brand_kits.STORE, store) if brand_kits.STORE.is_file() else store.write_text('[]', encoding='utf-8')
        for target, name, value in [(agency.research, 'fetch', cls.site.fetch), (brief_assistant, 'model_message', fake_model),
                                    (brand_kits, 'STORE', store), (stock.requests, 'get', cls.library.get)]:
            cls.stack.enter_context(patch.object(target, name, value))
        cls.stack.enter_context(patch('agency.research.target', return_value=None))
        cls.stack.enter_context(patch.object(campaign_generator.LexnisCampaignStudio, 'search_google', staticmethod(lambda q, n=6: [])))
        cls.stack.enter_context(patch.object(campaign_generator.LexnisCampaignStudio, '_chat', side_effect=RuntimeError('offline')))
        cls.stack.enter_context(patch.dict(os.environ, PEXELS_API_KEY='pexels-test-key', PIXABAY_API_KEY='pixabay-test-key'))
        cls.client = TestClient(server.app, base_url='http://localhost')
        cls.client.get('/')
        response = cls.client.post('/api/video/company-intro/research', json=dict(company_url='acme-robotics.example', duration=15,
                                   platform_target='16:9', resolution=720, web_search=False))
        assert response.status_code == 202, response.text
        cls.proposal = cls.wait(response.json())

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.client.close()
        TEMP.cleanup()

    @classmethod
    def wait(cls, job, limit=240):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            value = cls.client.get('/api/video/jobs/' + job['id']).json()
            if value['state'] == 'completed':
                return value['result']
            if value['state'] in {'failed', 'cancelled'}:
                raise AssertionError(value)
            time.sleep(.2)
        raise AssertionError('Job did not finish in time')

    def test_1_photos_exclude_logo_cards_and_flag_resolution(self):
        verdict = company_intro.image_kind(Image.open(io.BytesIO(logo_card())))
        self.assertTrue(verdict['graphic'], verdict)
        self.assertFalse(company_intro.image_kind(Image.open(io.BytesIO(photo(1))))['graphic'])
        real = Image.open(ROOT / 'static/assets/raw_subject.jpg')
        self.assertFalse(company_intro.image_kind(real)['graphic'])
        sources = [image['source_url'] for image in self.proposal['images']]
        self.assertEqual(sources, [f'{SITE}/photos/floor.jpg', f'{SITE}/photos/team.jpg'])   # the logo card is not a "photo"
        self.assertTrue(all(image['kind'] == 'photo' and image['low_resolution'] is False for image in self.proposal['images']))

    def test_2_company_website_video_is_collected_and_previewable(self):
        videos = self.proposal['videos']
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]['source_url'], f'{SITE}/media/hero.mp4')
        self.assertAlmostEqual(videos[0]['duration'], 8, delta=.2)
        served = self.client.get(f"/api/video/company-intro/{self.proposal['proposal_id']}/videos/0")
        self.assertEqual(served.status_code, 200)
        path = Path(TEMP.name) / 'served.mp4'; path.write_bytes(served.content)
        meta = probe(path)
        self.assertEqual(meta['video_codec'], 'h264'); self.assertFalse(meta['has_audio'])   # muted, browser-friendly copy
        poster = self.client.get(f"/api/video/company-intro/{self.proposal['proposal_id']}/videos/0/poster")
        self.assertEqual((poster.status_code, poster.headers['content-type']), (200, 'image/jpeg'))
        # The website video leads the proposal; photos follow; the closing scene stays a clean brand end card.
        scenes = self.proposal['scenes']
        self.assertEqual(scenes[0]['video'], 0)
        self.assertIsNone(scenes[-1]['video']); self.assertIsNone(scenes[-1]['image'])
        self.assertTrue(all(scene.get('stock_query') for scene in scenes))

    def test_3_stock_search_is_credited_cached_and_orientation_aware(self):
        status = self.client.get('/api/video/stock/status').json()
        self.assertEqual({p['id']: p['configured'] for p in status['providers']}, {'pexels': True, 'pixabay': True})
        self.assertIn('GIPHY', status['gifs'])
        before = len(self.library.calls)
        found = self.client.post('/api/video/stock/search', json=dict(query='robot arm warehouse', orientation='landscape', min_seconds=6)).json()
        ids = [(r['provider'], r['id']) for r in found['results']]
        self.assertEqual(ids, [('pexels', '1001'), ('pixabay', '2002')])   # the vertical Pixabay clip is filtered out
        pexels = found['results'][0]
        self.assertEqual((pexels['author'], pexels['provider_label']), ('Dana Lens', 'Pexels'))
        self.assertEqual(self.client.get(pexels['preview_url']).headers['content-type'], 'image/jpeg')
        api_calls = len([c for c in self.library.calls[before:] if 'api' in c['url']])
        self.client.post('/api/video/stock/search', json=dict(query='robot arm warehouse', orientation='landscape', min_seconds=6))
        self.assertEqual(len([c for c in self.library.calls[before:] if 'api' in c['url']]), api_calls)   # cached for 24 hours
        long_only = self.client.post('/api/video/stock/search', json=dict(query='robot arm warehouse', orientation='landscape', min_seconds=10)).json()
        self.assertEqual([r['id'] for r in long_only['results']], ['1001'])
        with patch.dict(os.environ, PEXELS_API_KEY='', PIXABAY_API_KEY=''):
            refused = self.client.post('/api/video/stock/search', json=dict(query='robots', orientation='landscape'))
        self.assertEqual(refused.status_code, 400)
        self.assertIn('PEXELS_API_KEY', refused.json()['detail'])
        self.assertEqual(self.client.post('/api/video/stock/search', json=dict(query='x' * 101)).status_code, 422)
        self.assertEqual(self.client.get('/api/video/stock/pexels/../preview').status_code, 404)

    def test_4_approved_footage_renders_with_motion_muted_and_credited(self):
        proposal = self.proposal
        self.client.post('/api/video/stock/search', json=dict(query='robot arm warehouse', orientation='landscape', min_seconds=2))
        scenes = [dict(section=s['section'], overlay_text=s['overlay_text'], voiceover=s['voiceover'], visual_prompt=s['visual_prompt'],
                       duration=s['duration'], motion=s['motion'], background_style=s['background_style'], image=None, video=None, stock=None)
                  for s in proposal['scenes']]
        scenes[0]['video'] = 0
        scenes[1]['stock'] = dict(provider='pexels', id='1001')
        scenes[2]['image'] = 0
        both = dict(scenes[3], image=0, video=0)
        self.assertEqual(self.client.post(f"/api/video/company-intro/{proposal['proposal_id']}/approve",
                                          json=dict(scenes=[*scenes[:3], both, scenes[4]], burn_subtitles=False)).status_code, 422)
        response = self.client.post(f"/api/video/company-intro/{proposal['proposal_id']}/approve", json=dict(scenes=scenes, burn_subtitles=False))
        self.assertEqual(response.status_code, 202, response.text)
        result = self.wait(response.json()['job'], 400)
        self.assertAlmostEqual(result['duration'], sum(s['duration'] for s in scenes), delta=.12)
        kit = zipfile.ZipFile(io.BytesIO(self.client.get(result['bundle_zip_url']).content))
        credits = kit.read('credits.txt').decode('utf-8')
        self.assertIn('Video by Dana Lens on Pexels (https://www.pexels.com/video/robot-arm-1001/)', credits)
        self.assertIn(f'{SITE}/media/hero.mp4', credits)
        project = json.loads(kit.read('project.json'))
        videos = [c for c in project['clips'] if c['kind'] == 'video']
        self.assertEqual(videos[0]['volume'], 0)          # footage sound never competes with narration or music
        self.assertEqual(videos[1]['volume'], 0)
        path = Path(TEMP.name) / 'footage.mp4'; path.write_bytes(kit.read('video/campaign.mp4'))
        from video.measure import frame_at
        first, later = frame_at(path, .8), frame_at(path, 2.2)
        self.assertGreater(float(np.abs(first.astype(float) - later.astype(float)).mean()), 4)   # real motion in the website video scene
        self.assertFalse(probe(path)['has_audio'])


    def test_5_browser_scene_visuals_offer_website_video_and_stock_search(self):
        from urllib.parse import urlsplit
        from playwright.sync_api import sync_playwright
        captured = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context(viewport={'width': 1440, 'height': 1000}).new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def proxy(route):
                parsed = urlsplit(route.request.url)
                if parsed.hostname != 'localhost':
                    route.abort()          # the page itself never contacts a stock library
                    return
                if parsed.path.endswith('/approve'):
                    captured['body'] = json.loads(route.request.post_data)
                    route.fulfill(status=409, body=json.dumps(dict(detail='Approval captured by the test')), headers={'content-type': 'application/json'})
                    return
                response = self.client.request(route.request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                                               content=route.request.post_data_buffer,
                                               headers={k: v for k, v in route.request.headers.items() if k in {'content-type', 'range'}})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={k: v for k, v in response.headers.items() if k not in {'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}})
            page.route('**/*', proxy)
            page.goto('http://localhost/', wait_until='domcontentloaded')
            page.get_by_role('button', name='Video Generator', exact=True).click()
            wizard = page.locator('.vbf-wizard')
            wizard.wait_for()
            wizard.get_by_label('Campaign goal').select_option('company_intro')
            intro = wizard.locator('[data-company-intro]')
            intro.wait_for(state='visible')
            intro.get_by_label('Company website', exact=True).fill('acme-robotics.example')
            intro.get_by_label('Video length').select_option('15')
            intro.get_by_label('Export quality').select_option('720')
            intro.get_by_role('button', name='Research company & propose video').click()
            intro.locator('[data-ci-proposal]').wait_for(state='visible', timeout=120000)
            first, second = intro.locator('.vbf-scene').nth(0), intro.locator('.vbf-scene').nth(1)
            # The company's own footage leads, previewed as video; photos are whole, never logo cards.
            self.assertEqual(first.get_by_label('Visual', exact=True).input_value(), 'video:0')
            first.locator('.vbf-ci-visual video').wait_for(state='attached')
            options = second.get_by_label('Visual', exact=True).locator('option').evaluate_all('nodes=>nodes.map(n=>n.textContent)')
            self.assertTrue(any(o.startswith('Website video 1') for o in options) and any(o.startswith('Website photo') for o in options), options)
            panel = second.locator('[data-stock]')
            panel.locator('summary').click()
            panel.get_by_role('button', name=re.compile('^Search')).click()
            panel.locator('.vbf-stock-item').first.wait_for(timeout=60000)
            self.assertIn('Dana Lens', panel.locator('.vbf-stock-item').first.inner_text())
            self.assertTrue(panel.locator('.vbf-stock-item img').first.evaluate('img=>img.complete&&img.naturalWidth>0'))
            panel.locator('.vbf-stock-item').first.click()
            self.assertEqual(second.get_by_label('Visual', exact=True).input_value(), 'stock')
            self.assertIn('Pexels · Dana Lens', second.locator('.vbf-ci-visual em').inner_text())
            intro.get_by_role('button', name='Approve & create video').click()
            page.wait_for_function("document.querySelector('[data-ci-status]').textContent.includes('Approval captured')")
            self.assertFalse(errors, errors)
            browser.close()
        scenes = captured['body']['scenes']
        self.assertEqual((scenes[0]['video'], scenes[0]['image'], scenes[0]['stock']), (0, None, None))
        self.assertEqual((scenes[1]['stock'], scenes[1]['image'], scenes[1]['video']), (dict(provider='pexels', id='1001'), None, None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
