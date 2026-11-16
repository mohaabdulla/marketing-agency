"""Real HTTP/ASGI, Pillow, FFmpeg and ZIP verification; isolated brands and no paid providers.

Run: python scripts/test_unified_enterprise_suite.py
Add --browser to verify the deliverables dashboard and clipboard controls with Chromium.
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='enterprise-suite-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
# Remote fonts are intentionally unavailable in the offline browser test.
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
BROWSER = '--browser' in sys.argv
if BROWSER:sys.argv.remove('--browser')
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import numpy as np
import server
import campaign_generator as campaign
import visual_engine as visual
from agency_suite import DELIVERABLE_NAMES
from video_ffmpeg import probe


class EnterpriseSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.stack.enter_context(patch.object(campaign.LexnisCampaignStudio,'_chat',side_effect=RuntimeError('Offline verification provider')))
        cls.stack.enter_context(patch.object(campaign.LexnisCampaignStudio,'analyze_company_website',return_value={}))
        cls.stack.enter_context(patch.object(campaign.LexnisCampaignStudio,'search_google',return_value=[]))
        cls.stack.enter_context(patch.object(visual,'preferred_local_model',return_value=None))
        cls.client=TestClient(server.app,base_url='http://localhost')
        cls.client.get('/')
        cls.workspace=cls.client.get('/api/session').json()['workspace']
        # A separate guest session must not be able to fetch any of this client's results.
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        logo=Image.new('RGBA',(220,60),(0,0,0,0))
        ImageDraw.Draw(logo).rectangle((6,6,214,54),fill='#ef3434')
        raw=io.BytesIO();logo.save(raw,'PNG')
        response=cls.client.post('/api/upload-logo',files={'file':('enterprise-logo.png',raw.getvalue(),'image/png')})
        assert response.status_code==200,response.text
        cls.logo=response.json()['file_url']
        cls.brand=dict(brand_name='Enterprise Test Works',brand_name_ar='أعمال الاختبار',primary_hex='#142332',secondary_hex='#a754df',
                       logo_path=cls.logo,tagline='Ideas into useful work.',hashtag='#EnterpriseTestWorks')
        response=cls.client.post('/api/brands',json=cls.brand)
        assert response.status_code==201,response.text
        cls.brand_id=response.json()['brand']['id']
        cls.results=[]
        cls.payload=dict(prompt='Hiring an AI Engineer at Enterprise Test Works. Help us build useful tools.',post_type='hiring',
                         brand_id=cls.brand_id,language='both',use_search=False,use_local_sdxl=False,seed=712,
                         generate_companion=False,output_format='landscape',
                         # A stale browser profile must not override an updated saved kit.
                         brand_profile_json=json.dumps({'brand_colors':{'primary':'#000000','accent':'#00ff00'}}),
                         key_points=['Build practical tools with the team'],key_points_ar=['بناء أدوات عملية مع الفريق'])
        cls.results.append(cls.generate(cls.payload))
        update={**cls.brand,'id':cls.brand_id,'primary_hex':'#263728','secondary_hex':'#e0a431','tagline':'A fresh direction for useful work.'}
        response=cls.client.post('/api/brands',json=update)
        assert response.status_code==200,response.text
        cls.results.append(cls.generate({**cls.payload,'prompt':'Product launch: a new workflow planner from Enterprise Test Works.','post_type':'product_launch','language':'ar'}))
        cls.evidence=ROOT/'output/enterprise-verification';cls.evidence.mkdir(parents=True,exist_ok=True)
        archive=cls.client.get(cls.results[-1]['bundle_zip_url'])
        (cls.evidence/'full-client-agency-kit.zip').write_bytes(archive.content)
        (cls.evidence/'response.json').write_text(json.dumps(cls.results[-1],ensure_ascii=False,indent=2),encoding='utf-8')

    @classmethod
    def generate(cls,payload):
        response=cls.client.post('/api/campaign/generate',json=payload)
        assert response.status_code==200,response.text[:2000]
        return response.json()

    @classmethod
    def tearDownClass(cls):
        cls.stack.close();cls.client.close();cls.other.close();TEMP.cleanup()

    def disk_path(self,url):
        return Path(TEMP.name)/'guests'/self.workspace/'renders'/Path(urlsplit(url).path).name

    def test_complete_contract_urls_disk_and_canvas_sizes(self):
        for data in self.results:
            self.assertEqual(data['status'],'completed')
            self.assertEqual(data['primary_image_url'],data['image_url'])
            self.assertFalse(any(key.endswith('_path') for key in data))
            for language,kit in data['agency_kits'].items():
                for key in [*DELIVERABLE_NAMES,'primary_image_url','bundle_zip_url']:
                    url=kit[key]
                    self.assertTrue(url.startswith('http://localhost/'),url)
                    response=self.client.get(url)
                    self.assertEqual(response.status_code,200,(language,key,response.text[:100] if not response.content else ''))
                    self.assertTrue(response.content)
                    self.assertTrue(self.disk_path(url).is_file(),url)
                    if key in {'image_url','primary_image_url','companion_image_url','story_url','landscape_url'}:
                        expected=(1080,1920) if key=='story_url' else (1200,628) if key=='landscape_url' else (1080,1350)
                        with Image.open(io.BytesIO(response.content)) as image:self.assertEqual(image.size,expected)
            self.assertEqual(self.client.get(data['bundle_zip_url']).status_code,200)

    def test_real_motion_framerate_loop_duration_and_changing_frames(self):
        import cv2
        for data in self.results:
            for kit in data['agency_kits'].values():
                video=self.disk_path(kit['animation_mp4_url'])
                meta=probe(video)
                self.assertAlmostEqual(meta['fps'],30,delta=.01)
                self.assertEqual((meta['width'],meta['height']),(1080,1350))
                self.assertAlmostEqual(meta['duration'],130/30,delta=.08)
                self.assertEqual(meta['video_codec'],'h264')
                capture=cv2.VideoCapture(str(video));samples=[]
                for frame in (8,9,10):
                    capture.set(cv2.CAP_PROP_POS_FRAMES,frame);ok,image=capture.read();self.assertTrue(ok);samples.append(image)
                capture.release()
                self.assertGreater(np.abs(samples[0].astype(float)-samples[1].astype(float)).mean(),.005)
                self.assertGreater(np.abs(samples[1].astype(float)-samples[2].astype(float)).mean(),.005)
                with Image.open(self.disk_path(kit['animation_url'])) as gif:
                    self.assertEqual(gif.info['loop'],0)
                    self.assertGreater(gif.n_frames,100)
                    total=0
                    for index in range(gif.n_frames):gif.seek(index);total+=gif.info['duration']
                    self.assertAlmostEqual(total/1000,meta['duration'],delta=.05)

    def test_bilingual_channel_copy_threads_and_strategy(self):
        for data in self.results:
            for language in ('en','ar'):
                copy=data['copywriting'][language]
                for key in ('linkedin_post','instagram_caption','x_post'):
                    self.assertTrue(copy[key].strip())
                self.assertTrue(copy['hashtags']);self.assertTrue(copy['hashtag_strategy']['brand'])
                self.assertGreaterEqual(len(copy['x_thread']),2)
                self.assertTrue(all(len(post)<=280 for post in copy['x_thread']))
                if language=='ar':self.assertRegex(copy['linkedin_post'],r'[\u0600-\u06ff]')
            self.assertEqual(data['copywriting']['linkedin_post'],data['copywriting'][data['language']]['linkedin_post'])

    def test_archive_integrity_markdown_and_file_hashes(self):
        for data in self.results:
            response=self.client.get(data['bundle_zip_url'])
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                self.assertIsNone(archive.testzip())
                manifest=json.loads(archive.read('campaign_manifest.json'))
                self.assertEqual(set(manifest['deliverables']),{'en','ar'})
                for language,files in manifest['deliverables'].items():
                    for key,entry in files.items():
                        raw=archive.read(entry['file'])
                        self.assertEqual(len(raw),entry['size'])
                        self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                        self.assertEqual(raw,self.client.get(data['agency_kits'][language][key]).content)
                    for channel in ('linkedin','instagram','x_thread','hashtags'):
                        self.assertGreater(len(archive.read(f'copy/{language}/{channel}.md')),20)
                self.assertIn('README.md',archive.namelist())

    def test_updated_brand_colors_logo_and_tagline_are_used(self):
        for index,data in enumerate(self.results):
            expected='#a754df' if index==0 else '#e0a431'
            self.assertEqual(data['brand_dna']['brand_colors']['accent'],expected)
            self.assertEqual(data['brand_dna']['tagline'],self.brand['tagline'] if index==0 else 'A fresh direction for useful work.')
            for key in ('primary_image_url','companion_image_url','story_url','landscape_url'):
                with Image.open(io.BytesIO(self.client.get(data[key]).content)) as source:
                    image=np.array(source.convert('RGB')).astype(int)
                red=(image[:,:,0]>180)&(image[:,:,1]<95)&(image[:,:,2]<95)
                self.assertGreater(red.sum(),100,(index,key,'Custom logo not visible'))

    def test_incomplete_requests_invalid_brands_and_workspace_isolation(self):
        self.assertEqual(self.client.post('/api/campaign/generate',json={'prompt':'  '}).status_code,422)
        self.assertEqual(self.client.post('/api/campaign/generate',json={**self.payload,'brand_id':'missing'}).status_code,404)
        self.assertEqual(self.client.post('/api/brands',json={**self.brand,'secondary_hex':'green'}).status_code,422)
        for key in ('primary_image_url','bundle_zip_url'):
            self.assertEqual(self.other.get(self.results[0][key]).status_code,404)
        with patch.object(server,'generate_campaign_endpoint',return_value={'agency_kits':{}}):
            self.assertEqual(self.client.post('/api/campaign/generate',json=self.payload).status_code,502)

    def test_absolute_urls_survive_redaction_but_filesystem_paths_do_not(self):
        from public_access import _guest, _clean
        token=_guest.set(self.workspace)
        try:
            url='http://localhost/renders/public.jpg'
            clean=_clean(dict(url=url,private='C:\\private\\secrets.json',unix='/etc/private'))
            self.assertEqual(clean['url'],url)
            self.assertEqual(clean['private'],'Managed workspace asset')
            self.assertEqual(clean['unix'],'Managed workspace asset')
        finally:_guest.reset(token)

    def test_legacy_endpoint_keeps_optional_motion_and_relative_urls(self):
        response=self.client.post('/api/generate',json={**self.payload,'generate_companion':False,'language':'en'})
        self.assertEqual(response.status_code,200,response.text[:300])
        data=response.json()
        self.assertTrue(data['image_url'].startswith('/renders/'))
        self.assertFalse(data.get('animation_url'))

    def test_returned_absolute_urls_can_be_reused_only_in_the_same_workspace(self):
        kit=self.results[0]['agency_kits']['en']
        response=self.client.post('/api/campaign/bundle',json=dict(deliverables={key:kit[key] for key in DELIVERABLE_NAMES},copywriting=kit['copywriting']))
        self.assertEqual(response.status_code,200,response.text[:300])
        self.assertEqual(self.client.get(response.json()['bundle_zip_url']).status_code,200)
        logo='http://localhost'+self.logo
        update={**self.brand,'id':self.brand_id,'logo_path':logo}
        self.assertEqual(self.client.post('/api/brands',json=update).status_code,200)
        update['logo_path']='https://foreign.invalid'+self.logo
        self.assertEqual(self.client.post('/api/brands',json=update).status_code,400)

    def test_tagline_changes_affect_rendered_headers_and_cached_art_identity(self):
        frames=[];themes=[]
        for tagline in ['First direction.','A completely new direction.']:
            theme=visual.resolve_brand_theme(brand_name='Enterprise Test Works',brand_profile={'tagline':tagline})
            image=Image.new('RGB',(1080,180),'#142332')
            visual.draw_brand_header(image,theme)
            frames.append(np.array(image));themes.append(theme)
        self.assertGreater(np.abs(frames[0][122:].astype(float)-frames[1][122:].astype(float)).sum(),100)
        self.assertNotEqual(campaign._brand_theme_fingerprint(themes[0]),campaign._brand_theme_fingerprint(themes[1]))

    @unittest.skipUnless(BROWSER,'Pass --browser for the real Chromium dashboard checks')
    def test_results_dashboard_tabs_bilingual_clipboard_and_download(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,
                                        permissions=['clipboard-read','clipboard-write'])
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def proxy(route):
                parsed=urlsplit(route.request.url)
                if parsed.hostname not in {'localhost','127.0.0.1','testserver'}:
                    route.abort();return
                path=parsed.path+('?' + parsed.query if parsed.query else '')
                headers={key:value for key,value in route.request.headers.items() if key in {'content-type','range'}}
                response=self.client.request(route.request.method,path,content=route.request.post_data_buffer,headers=headers)
                route.fulfill(status=response.status_code,body=response.content,
                    headers={key:value for key,value in response.headers.items() if key.lower() not in {'content-length','content-encoding','transfer-encoding','set-cookie'}})
            page.route('**/*',proxy)
            page.goto('http://localhost/',wait_until='domcontentloaded')
            page.wait_for_function('typeof renderCarouselPreview === "function" && !!window.renderCampaignDeliverables')
            page.evaluate("data=>{document.getElementById('results-section').classList.remove('hidden');renderCarouselPreview('carousel-preview',data,'en');for(let p=document.getElementById('carousel-preview');p;p=p.parentElement){p.classList.remove('hidden');if(p.tagName==='DETAILS')p.open=true;}}",self.results[0])
            root=page.locator('[data-campaign-delivery]')
            self.assertEqual(root.locator('.campaign-format-card').count(),4)
            root.get_by_role('tab',name='Visual Formats Grid').focus()
            page.keyboard.press('ArrowRight')
            self.assertEqual(root.get_by_role('tab',name='Motion Preview').get_attribute('aria-selected'),'true')
            self.assertEqual(root.locator('video').get_attribute('loop'),'')
            root.get_by_role('tab',name='Copywriting Hub').click()
            root.get_by_role('button',name='Copy LinkedIn',exact=True).click()
            page.wait_for_function("document.querySelector('.campaign-delivery-status[role=status]').textContent.includes('Copied')")
            self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n','\n'),self.results[0]['copywriting']['en']['linkedin_post'])
            root.get_by_label('Campaign delivery language').select_option('ar')
            self.assertEqual(root.locator('.campaign-copy-card pre').first.get_attribute('dir'),'rtl')
            root.get_by_role('button',name='Copy LinkedIn',exact=True).click()
            page.wait_for_function("document.querySelector('.campaign-delivery-status[role=status]').textContent.includes('Copied')")
            self.assertEqual(page.evaluate('navigator.clipboard.readText()').replace('\r\n','\n'),self.results[0]['copywriting']['ar']['linkedin_post'])
            tag=root.locator('.campaign-hashtags button').first
            tag.click()
            self.assertEqual(page.evaluate('navigator.clipboard.readText()'),tag.inner_text())
            with page.expect_download() as download:
                root.locator('[data-master-kit]').click()
            with zipfile.ZipFile(download.value.path()) as archive:self.assertIsNone(archive.testzip())
            root.screenshot(path=str(self.evidence/'delivery-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            overflow=page.evaluate("[...document.querySelectorAll('body *')].filter(el=>el.getClientRects().length&&el.getBoundingClientRect().right>innerWidth+1).slice(0,8).map(el=>({tag:el.tagName,id:el.id,classes:el.className,right:el.getBoundingClientRect().right}))")
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),overflow)
            root.screenshot(path=str(self.evidence/'delivery-mobile.png'))
            self.assertFalse(errors,errors)
            context.unroute_all(behavior='ignoreErrors');browser.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
