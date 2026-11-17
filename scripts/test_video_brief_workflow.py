"""Brand-guided storyboarding, real FFmpeg sequence exports and optional Chromium UX.

Run: python scripts/test_video_brief_workflow.py [--browser]
No model downloads or paid inference. Text-model responses are mocked explicitly.
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import ExitStack,contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='video-brief-suite-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
BROWSER='--browser' in sys.argv
if BROWSER:sys.argv.remove('--browser')
from fastapi.testclient import TestClient
from PIL import Image
import server
import campaign_generator
from video_director import VideoBriefRequest,StoryboardScene,synthesize_storyboard
from video_engine import build_sequence_project
from video_ffmpeg import ffmpeg,probe
from video_storage import read
from video_assets import path_for
from public_access import _guest


class VideoBriefWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.stack.enter_context(patch.object(campaign_generator.LexnisCampaignStudio,'_chat',side_effect=RuntimeError('Offline test provider')))
        cls.client=TestClient(server.app,base_url='http://localhost');cls.client.get('/')
        cls.workspace=cls.client.get('/api/session').json()['workspace']
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        logo=io.BytesIO();Image.new('RGB',(120,40),'#ef3434').save(logo,'PNG')
        uploaded=cls.client.post('/api/upload-logo',files={'file':('brief-logo.png',logo.getvalue(),'image/png')})
        assert uploaded.status_code==200,uploaded.text
        brand=cls.client.post('/api/brands',json=dict(brand_name='Brief Test Company',brand_name_ar='شركة الاختبار',
            primary_hex='#142332',secondary_hex='#e8b34a',font_preferences=['Arial'],tagline='Practical ideas for teams.',logo_path=uploaded.json()['file_url']))
        assert brand.status_code==201,brand.text
        cls.brand=brand.json()['brand']
        cls.payload=dict(brand_id=cls.brand['id'],core_message='نعلن إطلاق مخطط عمل جديد للفرق. تواصل معنا لاكتشاف التفاصيل.',
            campaign_type='Product Launch',platform_target='Feed (1:1)',tone='Professional',language='Arabic',
            duration=6,resolution=720,pacing='balanced',transition='fade')
        response=cls.client.post('/api/video/generate-brief',json=cls.payload)
        assert response.status_code==200,response.text
        cls.brief=response.json();cls.renders=[];cls.commands=[]
        # Real uploaded music and recorded-voiceover fixtures, not synthesized speech.
        audio=Path(TEMP.name)/'recording.wav'
        ffmpeg(['-f','lavfi','-i','sine=frequency=330:duration=6','-c:a','pcm_s16le',str(audio)])
        response=cls.client.post('/api/video/upload',files={'file':('recording.wav',audio.read_bytes(),'audio/wav')})
        assert response.status_code==200,response.text
        cls.audio=response.json()['id']
        def tracked(args,*a,**kw):cls.commands.append(list(args));return ffmpeg(args,*a,**kw)
        with patch('video_editor.ffmpeg',side_effect=tracked):
            for burn in (True,False):
                response=cls.client.post('/api/video/render-sequence',json=dict(brief_id=cls.brief['brief_id'],burn_subtitles=burn,
                    voiceover_asset_id=cls.audio,music_asset_id=cls.audio))
                assert response.status_code==202,response.text
                cls.renders.append(cls.wait(response.json()))
        cls.evidence=ROOT/'output/video-brief-verification';cls.evidence.mkdir(parents=True,exist_ok=True)
        (cls.evidence/'video-client-kit.zip').write_bytes(cls.client.get(cls.renders[0]['bundle_zip_url']).content)
        (cls.evidence/'campaign.mp4').write_bytes(cls.client.get(cls.renders[0]['mp4_url']).content)
        (cls.evidence/'brief.json').write_text(json.dumps(cls.brief,ensure_ascii=False,indent=2),encoding='utf-8')

    @classmethod
    def wait(cls,job):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            response=cls.client.get('/api/video/jobs/'+job['id']);assert response.status_code==200,response.text
            value=response.json()
            if value['state']=='completed':return value['result']
            if value['state'] in {'failed','cancelled'}:raise AssertionError(value)
            time.sleep(.1)
        raise AssertionError('Render did not complete within 120 seconds')

    @classmethod
    def tearDownClass(cls):
        cls.stack.close();cls.client.close();cls.other.close();TEMP.cleanup()

    def stored(self,folder,key):
        token=_guest.set(self.workspace)
        try:return read(folder,key)
        finally:_guest.reset(token)

    def test_director_scene_timings_brand_and_native_arabic(self):
        self.assertEqual(self.brief['status'],'ready');cursor=0
        for scene in self.brief['scenes']:
            self.assertAlmostEqual(scene['start'],cursor,places=2);cursor+=scene['duration']
            self.assertRegex(scene['overlay_text'],r'[\u0600-\u06ff]')
            self.assertTrue(scene['visual_prompt']);self.assertTrue(scene['voiceover'])
        self.assertAlmostEqual(cursor,6,places=2)
        self.assertEqual(self.brief['brand']['primary_hex'],self.brand['primary_hex'])
        self.assertEqual(self.brief['brand']['secondary_hex'],self.brand['accent_hex'])
        self.assertEqual(self.brief['brand']['font_family'],'Arial')

    def test_mocked_ai_storyboard_and_malformed_provider_fallback(self):
        request=VideoBriefRequest(**{**self.payload,'language':'English'})
        scenes=[dict(overlay_text='A new planner',voiceover='A planner for the team.',visual_prompt='A clean desk with planning cards.') for _ in range(3)]
        with patch.object(campaign_generator,'LexnisCampaignStudio') as studio:
            studio.return_value.text_engine='custom';studio.return_value._chat.return_value=json.dumps({'scenes':scenes})
            result,source=synthesize_storyboard(request,self.brand)
            self.assertEqual(source,'ai-model');self.assertEqual(result[0].overlay_text,'A new planner')
            studio.return_value._chat.return_value='{"scenes": [{"command":"run arbitrary command"}]}'
            result,source=synthesize_storyboard(request,self.brand)
            self.assertEqual(source,'local-template');self.assertEqual(len(result),3)

    def test_real_outputs_and_professional_archive(self):
        for result in self.renders:
            self.assertEqual(self.client.get(result['video_url']).status_code,200)
            raw=self.client.get(result['mp4_url']);self.assertEqual(raw.status_code,200)
            path=Path(TEMP.name)/(result['sequence_id']+'.mp4');path.write_bytes(raw.content);meta=probe(path)
            self.assertEqual((meta['width'],meta['height']),(720,720));self.assertAlmostEqual(meta['fps'],30,delta=.01)
            self.assertAlmostEqual(meta['duration'],6,delta=.12);self.assertEqual(meta['video_codec'],'h264')
            self.assertTrue(meta['has_audio']);self.assertEqual(meta['audio_codec'],'aac')
            with zipfile.ZipFile(io.BytesIO(self.client.get(result['bundle_zip_url']).content)) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('video/campaign.mp4'),raw.content)
                self.assertIn('copy/subtitles.srt',archive.namelist());self.assertIn('project.json',archive.namelist())
                self.assertIn(self.brief['scenes'][0]['voiceover'],archive.read('copy/script.txt').decode('utf-8'))

    def test_ffmpeg_composition_brand_styles_and_subtitle_toggle(self):
        graph=' '.join(' '.join(command) for command in self.commands)
        self.assertIn('xfade=transition=fade',graph);self.assertIn('libx264',graph);self.assertIn('-r 30',graph)
        for index,result in enumerate(self.renders):
            project=self.stored('projects',result['project_id'])
            self.assertEqual(project['caption_tracks'][0]['burn_in'],index==0)
            style=project['caption_tracks'][0]['brand_style'];self.assertEqual(style['font_name'],'Arial')
            self.assertEqual(style['stroke'],self.brand['primary_hex'])
            lower=next(c for c in project['clips'] if c['text_role']=='lower_third')
            self.assertEqual(lower['graphic_style']['fill'],self.brand['accent_hex'])
            self.assertEqual(project['canvas']['fps'],30)
            self.assertTrue(any(c['kind']=='overlay' and c['asset_id']==self.brief['brand']['logo_asset_id'] for c in project['clips']))
        # The checkbox changes pixels in the encoded file, not just project metadata.
        import cv2,numpy as np
        frames=[]
        for result in self.renders:
            token=_guest.set(self.workspace)
            try:source=path_for(result['asset_id'])
            finally:_guest.reset(token)
            cap=cv2.VideoCapture(str(source));cap.set(cv2.CAP_PROP_POS_MSEC,1000);ok,frame=cap.read();cap.release()
            self.assertTrue(ok);frames.append(frame)
        self.assertGreater(np.abs(frames[0][450:650].astype(float)-frames[1][450:650].astype(float)).mean(),1)

    def test_invalid_scenes_foreign_assets_and_missing_brands(self):
        self.assertEqual(self.client.post('/api/video/generate-brief',json={**self.payload,'brand_id':'missing'}).status_code,404)
        self.assertEqual(self.client.post('/api/video/generate-brief',json={**self.payload,'core_message':' '}).status_code,422)
        self.assertEqual(self.client.post('/api/video/generate-brief',json={**self.payload,'platform_target':'invalid'}).status_code,422)
        scenes=json.loads(json.dumps(self.brief['scenes']));scenes[1]['start']+=1
        self.assertEqual(self.client.post('/api/video/render-sequence',json=dict(brief_id=self.brief['brief_id'],scenes=scenes)).status_code,400)
        self.assertEqual(self.other.get('/api/video/briefs/'+self.brief['brief_id']).status_code,404)
        self.assertEqual(self.other.post('/api/video/render-sequence',json=dict(brief_id=self.brief['brief_id'])).status_code,404)
        self.assertEqual(self.other.get(self.renders[0]['bundle_zip_url']).status_code,404)

    def test_inline_render_brief_and_missing_tools_checked_before_queue(self):
        import video_api
        with patch.object(video_api.jobs,'submit',return_value=dict(id='0'*32,state='queued',kind='storyboard-sequence')) as submit:
            body={**self.payload,'burn_subtitles':False};body['prompt']=body.pop('core_message')
            response=self.client.post('/api/video/render-sequence',json=body)
            self.assertEqual(response.status_code,202,response.text);submit.assert_called_once()
        with patch.object(video_api,'binary',return_value=None),patch.object(video_api.jobs,'submit') as submit:
            response=self.client.post('/api/video/render-sequence',json=dict(brief_id=self.brief['brief_id']))
            self.assertEqual(response.status_code,503);submit.assert_not_called()

    def test_all_formats_pacing_cuts_and_frozen_brand_snapshot(self):
        from types import SimpleNamespace
        from video_director import RenderSequenceRequest
        token=_guest.set(self.workspace)
        try:
            for ratio,size in [('9:16',(720,1280)),('16:9',(1280,720)),('1:1',(720,720))]:
                brief=json.loads(json.dumps(self.brief));brief['request'].update(platform_target=ratio,transition='cut')
                with tempfile.TemporaryDirectory() as directory:
                    project=build_sequence_project(brief,RenderSequenceRequest(brief_id=brief['brief_id']),
                        SimpleNamespace(cancelled=lambda:False,update=lambda **kw:None),Path(directory))
                self.assertEqual((project.canvas.width,project.canvas.height),size)
                self.assertTrue(all(c.transition==0 for c in project.clips if c.kind=='video'))
        finally:_guest.reset(token)
        changed={**self.brand,'primary_hex':'#553322'}
        self.assertEqual(self.client.post('/api/brands',json=changed).status_code,200)
        self.assertEqual(self.client.get('/api/video/briefs/'+self.brief['brief_id']).json()['brand']['primary_hex'],self.brand['primary_hex'])
        self.client.post('/api/brands',json=self.brand)

    @contextmanager
    def live_server(self):
        import socket,subprocess,requests
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        with (self.evidence/'browser-server.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'scripts/agency_regression_worker.py','--serve',str(port)],
                cwd=ROOT,env={**os.environ,'PYTHONIOENCODING':'utf-8'},stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(120):
                    try:
                        if requests.get(origin+'/api/session',timeout=1).ok:break
                    except requests.RequestException:time.sleep(.2)
                    if process.poll() is not None:raise AssertionError('Browser test server failed to start')
                else:raise AssertionError('Browser test server did not become ready')
                yield origin
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

    @unittest.skipUnless(BROWSER,'Pass --browser for Chromium wizard verification')
    def test_browser_wizard_edit_render_download_and_reload(self):
        from playwright.sync_api import sync_playwright
        with self.live_server() as origin,sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            context.add_cookies([{'name':'lexnis_guest','value':self.client.cookies.get('lexnis_guest'),'url':origin,'httpOnly':True,'sameSite':'Lax'}])
            page.route('https://**/*',lambda route:route.abort())
            page.goto(origin+'/',wait_until='domcontentloaded')
            page.get_by_role('button',name='Video Generator',exact=True).click()
            wizard=page.locator('.vbf-wizard');wizard.wait_for()
            page.wait_for_function("[...document.querySelector('[data-field=brand_id]').options].length>1")
            wizard.get_by_label('Brand kit',exact=True).select_option(self.brand['id'])
            wizard.get_by_label('Core message or vacancy/product details').fill('Introduce our workflow planner for growing teams.')
            wizard.get_by_role('button',name='Next: Format & Style').click()
            wizard.get_by_label('Platform format').select_option('16:9')
            wizard.get_by_label('Total duration (seconds)').fill('6')
            wizard.get_by_role('button',name='Generate storyboard',exact=True).click()
            wizard.locator('.vbf-scene').first.wait_for()
            self.assertEqual(wizard.locator('.vbf-scene').count(),3)
            wizard.get_by_label('Text overlay',exact=True).first.fill('Your next planning chapter')
            wizard.get_by_label('Voiceover script',exact=True).first.fill('Plan the next chapter with our team.')
            wizard.get_by_label('Recorded voiceover',exact=True).select_option(self.audio)
            wizard.get_by_label('Licensed music track',exact=True).select_option(self.audio)
            wizard.get_by_role('button',name='Next: Render & Export').click()
            wizard.get_by_label('Burn subtitles into the video').uncheck()
            with page.expect_response(lambda response:'/api/video/render-sequence' in response.url and response.request.method=='POST') as submitted:
                wizard.get_by_role('button',name='Render complete video',exact=True).click()
            self.assertEqual(submitted.value.status,202,submitted.value.text())
            posted=submitted.value.request.post_data_json
            self.assertFalse(posted['burn_subtitles'])
            self.assertEqual(posted['scenes'][0]['overlay_text'],'Your next planning chapter')
            wizard.get_by_role('link',name='Download MP4',exact=True).wait_for(timeout=120000)
            self.assertEqual(wizard.get_by_label('Video render progress').get_attribute('value'),'100')
            self.assertEqual(wizard.get_by_label('Storyboard video preview').count(),1)
            with page.expect_download() as download:wizard.get_by_role('link',name='Download Full Video Kit (.ZIP)',exact=True).click()
            with zipfile.ZipFile(download.value.path()) as archive:self.assertIsNone(archive.testzip())
            wizard.screenshot(path=str(self.evidence/'wizard-desktop.png'))
            page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='Video Generator',exact=True).click()
            page.wait_for_function("document.querySelector('[data-field=brand_id]')?.value!=='' && document.querySelector('[data-step=\"3\"]')?.disabled===false")
            wizard.get_by_role('button',name='4. Render & Export',exact=True).click()
            wizard.get_by_role('link',name='Download MP4',exact=True).wait_for()
            page.set_viewport_size({'width':390,'height':844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            wizard.screenshot(path=str(self.evidence/'wizard-mobile.png'))
            self.assertFalse(errors,errors)
            context.unroute_all(behavior='ignoreErrors');browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
