"""Producer workflow acceptance: real local CPU clips/master/PDF/ZIP, scoped gates and adapter contracts.
Run: python scripts/test_video_production_pipeline.py [--browser]
Diffusion adapter tests are protocol mocks. Real GPU inference uses scripts/verify_local_video.py.
"""
import hashlib
import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch,MagicMock
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='producer-pipeline-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
    VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
BROWSER='--browser' in sys.argv
if BROWSER:sys.argv.remove('--browser')
from fastapi.testclient import TestClient
from PIL import Image,ImageDraw
import server
from video import production
from video.ffmpeg import probe
from core.public_access import _guest


class ProducerPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(server.app,base_url='http://localhost');cls.client.get('/')
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        cls.workspace=cls.client.get('/api/session').json()['workspace']
        picture=Image.new('RGBA',(240,80),(0,0,0,0));ImageDraw.Draw(picture).rectangle((10,10,230,70),fill='#78cfa0')
        raw=io.BytesIO();picture.save(raw,'PNG')
        logo=cls.client.post('/api/video/upload',files={'file':('approved-logo.png',raw.getvalue(),'image/png')})
        assert logo.status_code==200,logo.text
        brand=cls.client.post('/api/brands',json=dict(brand_name='Producer Test',brand_name_ar='اختبار الإنتاج',primary_hex='#243746',secondary_hex='#78cfa0',font_preferences=['Arial']))
        assert brand.status_code==201,brand.text
        cls.brand=brand.json()['brand']['id']
        doc=cls.client.post('/api/guidelines',files={'file':('rules.txt',b'Brand: Producer Test\nPrimary: #243746\nSecondary: #78cfa0\nFont: Arial\nCTA: Book a demo','text/plain')})
        assert doc.status_code==201,doc.text
        cls.unconfirmed=doc.json();rules=dict(cls.unconfirmed['rules']);rules.update(primary_colors=['#243746'],secondary_colors=['#78cfa0'],font_preferences=['Arial'],
            logo_asset_id=logo.json()['id'],prohibited_elements=['guaranteed revenue'],required_elements=['logo'],cta='Book a demo')
        reviewed=cls.client.put('/api/guidelines/'+cls.unconfirmed['id'],json=dict(expected_version=cls.unconfirmed['version'],rules=rules,confirmed=True))
        assert reviewed.status_code==200,reviewed.text
        cls.guideline=reviewed.json()
        cls.payload=dict(name='Reviewed company film',brief=dict(brand_id=cls.brand,core_message='Introduce our planning tools.',guideline_id=cls.guideline['id'],
            duration=6,resolution=720,platform_target='1:1'),script_text='Meet our team.\n\nPlan warehouse work.\n\nBook a demo.',use_local_ai=False)

    @classmethod
    def tearDownClass(cls):cls.client.close();cls.other.close();TEMP.cleanup()

    def create(self,payload=None):
        response=self.client.post('/api/video/productions',json=payload or self.payload)
        self.assertEqual(response.status_code,201,response.text);return response.json()

    def get(self,key):
        response=self.client.get('/api/video/productions/'+key);self.assertEqual(response.status_code,200,response.text);return response.json()

    def wait(self,job,timeout=600):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=self.client.get('/api/video/jobs/'+job['id']).json()
            if status['state']=='completed':return status['result']
            if status['state'] in ('failed','cancelled'):
                token=_guest.set(self.workspace)
                try:
                    logs=list((production.DATA/'jobs').glob(job['id']+'*.log'))
                    details='\n'.join(p.read_text(encoding='utf-8')[-3500:] for p in logs)
                finally:_guest.reset(token)
                self.fail(str(status)+'\n'+details)
            time.sleep(.2)
        self.client.post('/api/video/jobs/'+job['id']+'/cancel',json={})
        cancellation_deadline=time.monotonic()+30
        while time.monotonic()<cancellation_deadline:
            if self.client.get('/api/video/jobs/'+job['id']).json()['state'] in ('completed','failed','cancelled'):break
            time.sleep(.2)
        self.fail('Producer test job timed out; cancellation requested before cleanup')

    def approve_script(self,record):
        result=self.client.post('/api/video/productions/'+record['id']+'/approve-script',json=dict(expected_version=record['version'],reviewer='Test producer'))
        self.assertEqual(result.status_code,200,result.text);return result.json()

    def test_01_governance_snapshot_and_stable_shot_ids(self):
        record=self.create()
        self.assertEqual(len(record['shots']),3)
        self.assertEqual(len({s['id'] for s in record['shots']}),3)
        self.assertEqual(record['governance']['rules']['primary_colors'],['#243746'])
        self.assertEqual(record['governance']['guideline_version'],self.guideline['version'])
        self.assertEqual(len(record['governance']['sha256']),64)
        self.assertEqual([s['input']['voiceover'] for s in record['shots']],['Meet our team.','Plan warehouse work.','Book a demo.'])
        self.assertEqual(self.other.get('/api/video/productions/'+record['id']).status_code,404)

    def test_02_local_only_planning_never_calls_hosted_script_provider(self):
        payload={**self.payload,'script_text':'','use_local_ai':True}
        with patch('agency.local_text.endpoint',side_effect=ValueError('Local model not configured')),patch('video.script_writer.chat',side_effect=AssertionError('Hosted fallback is forbidden')):
            record=self.create(payload)
        self.assertEqual(record['script_source'],'local-template');self.assertTrue(record['script_warnings'])

    def test_03_stale_versions_gates_and_incorrect_ownership_are_rejected(self):
        record=self.create();shot=record['shots'][0];prefix='/api/video/productions/'+record['id']
        response=self.client.post(prefix+'/shots/'+shot['id']+'/generate',json=dict(expected_version=record['version'],pass_name='concept'))
        self.assertEqual(response.status_code,400)
        approved=self.approve_script(record)
        stale=self.client.put(prefix+'/shots/'+shot['id'],json=dict(expected_version=record['version'],shot=shot['input']))
        self.assertEqual(stale.status_code,409,stale.text)
        no_gate=self.client.post(prefix+'/shots/'+shot['id']+'/generate',json=dict(expected_version=approved['version'],pass_name='final'))
        self.assertEqual(no_gate.status_code,400)
        self.assertEqual(self.client.get(prefix+'/delivery/zip').status_code,409)
        self.assertEqual(self.other.post(prefix+'/approve-script',json=dict(expected_version=approved['version'],reviewer='Other guest')).status_code,404)

    def test_04_accuracy_critical_shots_do_not_silently_use_diffusion_or_graphics(self):
        record=self.create();shot=record['shots'][0]
        next_input={**shot['input'],'accuracy_critical':True,'method':'text-to-video'}
        changed=self.client.put('/api/video/productions/'+record['id']+'/shots/'+shot['id'],json=dict(expected_version=record['version'],shot=next_input)).json()
        changed=self.approve_script(changed)
        response=self.client.post('/api/video/productions/'+record['id']+'/shots/'+shot['id']+'/generate',json=dict(expected_version=changed['version'],pass_name='concept'))
        self.assertEqual(response.status_code,400);self.assertIn('Accuracy-critical',response.text)

    def test_05_cog_and_wan_worker_adapter_contracts_are_local_only(self):
        from scripts.render_local_video import build_pipeline
        torch=MagicMock();diffusers=MagicMock()
        for model,mode,pipeline in [('cogvideox-2b','text-to-video','CogVideoXPipeline'),('wan22-ti2v-5b','image-to-video','WanImageToVideoPipeline')]:
            request=dict(model=model,mode=mode,model_path='fixture-model',image='fixture-image')
            result=build_pipeline(request,torch,diffusers)
            call=getattr(diffusers,pipeline).from_pretrained.call_args
            self.assertTrue(call.kwargs['local_files_only']);result.enable_sequential_cpu_offload.assert_called_once()
        self.assertTrue(diffusers.WanImageToVideoPipeline.from_pretrained.call_args.kwargs['expand_timesteps'])
        from scripts.render_local_video import encode_cog_prompt
        transformers=MagicMock()
        with patch.dict(sys.modules,{'transformers':transformers}):
            encode_cog_prompt(dict(model_path='fixture',prompt='Clean cinematic plate',camera='static',negative_prompt=''),torch)
        device_map=transformers.T5EncoderModel.from_pretrained.call_args.kwargs['device_map']
        self.assertEqual(device_map,{'shared':0,'encoder':0})
        from scripts.render_local_video import configure_tensor_reader
        import types
        calls=[]
        def factory(filename,framework,device='cpu',*,backend='mmap'):
            calls.append(backend);return 'reader'
        module=types.SimpleNamespace(safe_open=factory)
        self.assertTrue(configure_tensor_reader(module,windows=True))
        self.assertEqual(module.safe_open('fixture','pt'),'reader');self.assertEqual(calls,['pread'])
        module.safe_open('fixture','pt',backend='mmap');self.assertEqual(calls,['pread','pread'])

    def test_06_real_cpu_pipeline_review_render_pdf_archive_and_edit_invalidation(self):
        record=self.approve_script(self.create());key=record['id'];prefix='/api/video/productions/'+key
        for shot_id in [s['id'] for s in record['shots']]:
            for stage in ('concept','continuity','final'):
                record=self.get(key)
                response=self.client.post(prefix+'/shots/'+shot_id+'/generate',json=dict(expected_version=record['version'],pass_name=stage))
                self.assertEqual(response.status_code,202,response.text);self.wait(response.json());record=self.get(key)
                shot=next(s for s in record['shots'] if s['id']==shot_id);take=shot['candidates'][-1]
                self.assertIn('no diffusion',take['notice'])
                self.assertIsNone(take['generation_settings']['inference_steps'])
                response=self.client.post(prefix+'/shots/'+shot_id+'/review',json=dict(expected_version=record['version'],gate=stage,candidate_id=take['id'],
                    reviewer='Test producer',intent_checked=True,continuity_checked=True,readability_checked=True))
                self.assertEqual(response.status_code,200,response.text);record=response.json()
        # Rejecting an earlier accepted gate invalidates its entire downstream
        # chain. The same unchanged files may only be used after explicit re-review.
        reviewed_shot=record['shots'][0];concept=next(c for c in reviewed_shot['candidates'] if c['pass_name']=='concept')
        response=self.client.post(prefix+'/shots/'+reviewed_shot['id']+'/review',json=dict(expected_version=record['version'],
            gate='concept',candidate_id=concept['id'],reviewer='Test producer',approved=False,issue='continuity',note='Recheck consistent appearance across the complete sequence.'))
        self.assertEqual(response.status_code,200,response.text);record=response.json()
        self.assertEqual(record['shots'][0]['approvals'],{})
        blocked=self.client.post(prefix+'/render',json=dict(expected_version=record['version']))
        self.assertEqual(blocked.status_code,400)
        for stage in ('concept','continuity','final'):
            take=next(c for c in reviewed_shot['candidates'] if c['pass_name']==stage)
            response=self.client.post(prefix+'/shots/'+reviewed_shot['id']+'/review',json=dict(expected_version=record['version'],gate=stage,candidate_id=take['id'],
                reviewer='Test producer',intent_checked=True,continuity_checked=True,readability_checked=True,note='Re-reviewed against the complete sequence.'))
            self.assertEqual(response.status_code,200,response.text);record=response.json()
        response=self.client.post(prefix+'/render',json=dict(expected_version=record['version'],variants=['9:16']))
        self.assertEqual(response.status_code,202,response.text);self.wait(response.json());record=self.get(key)
        self.assertEqual(record['render']['native_metadata']['fps'],30)
        self.assertEqual(record['render']['native_metadata']['width'],720)
        self.assertAlmostEqual(record['render']['native_metadata']['duration'],6,delta=.15)
        vertical=record['render']['variants']['9:16']
        token=_guest.set(self.workspace)
        try:
            from video.assets import path_for
            meta=probe(path_for(vertical['asset_id']))
            self.assertEqual((meta['width'],meta['height'],meta['fps']),(1080,1920,30))
            unverified=copy.deepcopy(record);unverified['render']['qa']=None
            with self.assertRaisesRegex(ValueError,'lacks technical QA'):production.release_readiness(unverified)
            from video.production_render import compliance,project_model
            edited=project_model(production.read('projects',record['timeline_project_id']))
            title=next(c for c in edited.clips if c.kind=='title')
            title.graphic_style={**(title.graphic_style or {}),'fill':'#ff00ff'}
            self.assertFalse(compliance(record,edited)['passed'])
        finally:_guest.reset(token)
        checks=self.client.post(prefix+'/check',json={});self.assertEqual(checks.status_code,200,checks.text);self.assertTrue(checks.json()['passed'],checks.text)
        self.assertEqual(self.client.get(prefix+'/delivery/master').status_code,409)
        response=self.client.post(prefix+'/release',json=dict(expected_version=record['version'],reviewer='Test producer',
            story_checked=True,continuity_checked=True,text_checked=True,audio_checked=True,rights_checked=True))
        self.assertEqual(response.status_code,202,response.text);self.wait(response.json());record=self.get(key)
        archive=self.client.get(prefix+'/delivery/zip');self.assertEqual(archive.status_code,200,archive.text[:100])
        evidence=ROOT/'output/producer-verification';evidence.mkdir(parents=True,exist_ok=True);(evidence/'approved-client-kit.zip').write_bytes(archive.content)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            self.assertIsNone(bundle.testzip());manifest=json.loads(bundle.read('manifest.json'))
            for name,item in manifest['files'].items():self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(),item['sha256'])
            import fitz
            for name in ('script/script.pdf','storyboard/storyboard.pdf'):
                with fitz.open(stream=bundle.read(name),filetype='pdf') as pdf:self.assertGreaterEqual(len(pdf),3)
            self.assertIn('Plan warehouse work.',bundle.read('script/script.txt').decode())
            self.assertTrue(bundle.read('captions/subtitles.srt').strip())
        # A saved NLE edit makes the approved export stale immediately.
        raw=self.client.get('/api/video/projects/'+record['timeline_project_id']).json()
        project={k:v for k,v in raw.items() if k not in ('id','created','updated')};project['name']='A changed editorial revision'
        changed=self.client.put('/api/video/projects/'+record['timeline_project_id'],json=project)
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.client.get(prefix+'/delivery/zip').status_code,400)

    def test_08_previous_parent_take_and_abandoned_worker_recovery(self):
        record=self.approve_script(self.create());shot=record['shots'][0]
        token=_guest.set(self.workspace)
        try:
            from video.assets import path_for
            asset_id=record['governance']['brand']['logo_asset_id']
            candidate=dict(id='2'*32,pass_name='continuity',input_sha256=production.shot_digest(record,shot),
                asset_id=asset_id,file_sha256=production.file_hash(path_for(asset_id)),parent_candidate_id='0'*32)
            shot['candidates']=[candidate];shot['approvals']={'concept':{'candidate_id':'1'*32}}
            production.atomic(production.DATA/'productions'/(record['id']+'.json'),record)
        finally:_guest.reset(token)
        response=self.client.post('/api/video/productions/'+record['id']+'/shots/'+shot['id']+'/review',json=dict(
            expected_version=record['version'],gate='continuity',candidate_id=candidate['id'],reviewer='Producer',intent_checked=True,continuity_checked=True))
        self.assertEqual(response.status_code,400);self.assertIn('previous approved parent',response.text)
        token=_guest.set(self.workspace)
        try:
            record['busy_job']='3'*32
            production.atomic(production.DATA/'productions'/(record['id']+'.json'),record)
            production.atomic(production.DATA/'jobs'/('3'*32+'.json'),dict(id='3'*32,state='failed',kind='production-shot'))
        finally:_guest.reset(token)
        recovered=self.get(record['id']);self.assertIsNone(recovered['busy_job']);self.assertGreater(recovered['version'],record['version'])

    def test_09_identity_text_policy_and_named_reviewer_are_required(self):
        record=self.create();prefix='/api/video/productions/'+record['id'];shot=record['shots'][0]
        response=self.client.post(prefix+'/approve-script',json=dict(expected_version=record['version'],reviewer='   '))
        self.assertEqual(response.status_code,422)
        response=self.client.put(prefix+'/shots/'+shot['id'],json=dict(expected_version=record['version'],shot={**shot['input'],'composite_critical_text':False}))
        self.assertEqual(response.status_code,422)

    def test_10_exact_length_real_footage_is_accepted(self):
        from video.ffmpeg import ffmpeg
        source=Path(TEMP.name)/'exact-two-seconds.mp4'
        ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=30','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
        uploaded=self.client.post('/api/video/upload',files={'file':('exact-source.mp4',source.read_bytes(),'video/mp4')})
        self.assertEqual(uploaded.status_code,200,uploaded.text)
        record=self.create();shot=record['shots'][0];prefix='/api/video/productions/'+record['id']
        changed=self.client.put(prefix+'/shots/'+shot['id'],json=dict(expected_version=record['version'],shot={**shot['input'],
            'method':'real-footage','accuracy_critical':True,'source_asset_id':uploaded.json()['id']}))
        self.assertEqual(changed.status_code,200,changed.text);record=self.approve_script(changed.json())
        response=self.client.post(prefix+'/shots/'+shot['id']+'/generate',json=dict(expected_version=record['version'],pass_name='concept'))
        self.assertEqual(response.status_code,202,response.text);self.wait(response.json())
        candidate=self.get(record['id'])['shots'][0]['candidates'][-1]
        self.assertEqual(candidate['method'],'real-footage');self.assertAlmostEqual(candidate['metadata']['duration'],2,delta=.12)

    def test_11_fresh_guest_recovery_preserves_storage_queue_lock_order(self):
        import concurrent.futures
        import threading
        import core.public_access as access
        from video.jobs import jobs
        admitted=threading.Event();original=access._session;recovery_files=[]
        def session(*args,**kwargs):
            result=original(*args,**kwargs)
            # Simulate a queued job left by a previous server run. Without a
            # recovery write, an empty guest directory would not expose inversion.
            path=access.guest_root()/result[0]/'video/jobs'/('4'*32+'.json')
            path.write_text(json.dumps(dict(id='4'*32,state='queued',kind='production-shot')),encoding='utf-8')
            recovery_files.append(path);admitted.set();return result
        def fresh_guest():
            with TestClient(server.app,base_url='http://localhost') as client:return client.get('/').status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor,patch.object(access,'_session',side_effect=session):
            with production.LOCK:
                future=executor.submit(fresh_guest);self.assertTrue(admitted.wait(5))
                time.sleep(.1)
                acquired=jobs.lock.acquire(timeout=.5)
                if acquired:jobs.lock.release()
            self.assertEqual(future.result(timeout=10),200)
        self.assertTrue(acquired,'Fresh-guest recovery held the queue lock while waiting for storage')
        self.assertEqual(json.loads(recovery_files[0].read_text())['state'],'failed')

    def local_script(self,headline='Join our team',voiceover='Join our team.'):
        from video.production_schemas import ProductionCreate
        from video.production_text import plan_script
        governance=self.create()['governance']
        body=ProductionCreate.model_validate({**self.payload,'script_text':'','use_local_ai':True,'continuity_notes':'Same blue jacket',
            'brief':{**self.payload['brief'],'campaign_type':'hiring','tone':'energetic','core_message':'We are hiring designers.'}})
        scenes=[dict(overlay_text=headline,voiceover=voiceover,visual_prompt='Eye-level team in the real workplace, no lettering or logos.') for _ in range(3)]
        session=MagicMock();client=session.return_value.__enter__.return_value
        with patch('agency.local_text.endpoint',return_value='http://127.0.0.1:9999'),patch('agency.local_text.session',session),patch('agency.local_text.bounded_json',
            side_effect=[dict(tokens=[1]*10),dict(choices=[dict(message=dict(content=json.dumps(dict(scenes=scenes))))])]):
            result=plan_script(body,governance)
        sent=client.post.call_args_list[1].kwargs['json']['messages'][1]['content']
        return result,json.loads(sent)

    def test_12_local_script_includes_full_approved_creative_context(self):
        (scenes,source,warnings),context=self.local_script()
        self.assertEqual(source,'local-llama.cpp');self.assertFalse(warnings)
        self.assertEqual(context['campaign_goal'],'hiring');self.assertEqual(context['tone'],'energetic')
        self.assertEqual(context['continuity_notes'],'Same blue jacket');self.assertEqual(context['duration_seconds'],6)
        self.assertEqual(context['aspect_ratio'],'1:1');self.assertEqual(len(scenes),3)

    def test_13_local_script_rejects_unsupported_headlines_banned_words_and_long_narration(self):
        for headline,voice in [('90% growth','Join our team.'),('guaranteed revenue','Join our team.'),('Join our team',' '.join(['Apply']*20))]:
            with self.subTest(headline=headline,voice=voice):
                (scenes,source,warnings),_=self.local_script(headline,voice)
                self.assertEqual(source,'local-template');self.assertTrue(warnings)
                self.assertNotIn('90%',str(scenes));self.assertNotIn('guaranteed revenue',str(scenes))

    def test_14_take_rejection_retains_feedback_and_blocks_later_gates(self):
        record=self.approve_script(self.create());prefix='/api/video/productions/'+record['id'];shot_id=record['shots'][0]['id']
        response=self.client.post(prefix+'/shots/'+shot_id+'/generate',json=dict(expected_version=record['version'],pass_name='concept'))
        self.assertEqual(response.status_code,202,response.text);self.wait(response.json());record=self.get(record['id'])
        candidate=record['shots'][0]['candidates'][-1];original_hash=candidate['file_sha256']
        approved=self.client.post(prefix+'/shots/'+shot_id+'/review',json=dict(expected_version=record['version'],gate='concept',candidate_id=candidate['id'],
            reviewer='Producer',intent_checked=True))
        self.assertEqual(approved.status_code,200,approved.text);record=approved.json()
        body=dict(expected_version=record['version'],gate='concept',candidate_id=candidate['id'],reviewer='Producer',approved=False,issue='continuity')
        missing=self.client.post(prefix+'/shots/'+shot_id+'/review',json=body)
        self.assertEqual(missing.status_code,400)
        rejected=self.client.post(prefix+'/shots/'+shot_id+'/review',json={**body,'note':'The jacket changes between shots.'})
        self.assertEqual(rejected.status_code,200,rejected.text);record=rejected.json();shot=record['shots'][0]
        self.assertNotIn('concept',shot['approvals']);self.assertEqual(shot['candidates'][-1]['file_sha256'],original_hash)
        review=shot['candidates'][-1]['reviews'][-1]
        self.assertFalse(review['approved']);self.assertEqual(review['issue'],'continuity');self.assertIn('wardrobe',review['suggestion'])
        self.assertEqual(record['events'][-1]['detail']['candidate_id'],candidate['id'])
        blocked=self.client.post(prefix+'/shots/'+shot_id+'/generate',json=dict(expected_version=record['version'],pass_name='continuity'))
        self.assertEqual(blocked.status_code,400)
        self.assertIsNone(record['release']);self.assertIsNone(record['render'])

    @unittest.skipUnless(BROWSER,'Pass --browser for producer workspace verification')
    def test_07_browser_create_edit_approve_and_legacy_navigation(self):
        from playwright.sync_api import sync_playwright
        evidence=ROOT/'output/producer-verification';evidence.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def proxy(route):
                parsed=urlsplit(route.request.url)
                if parsed.hostname!='localhost':route.abort();return
                with patch('video.routes.media.statuses',return_value=[]):
                    response=self.client.request(route.request.method,parsed.path+('?' + parsed.query if parsed.query else ''),content=route.request.post_data_buffer,
                        headers={k:v for k,v in route.request.headers.items() if k in ('content-type','range')})
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding','set-cookie')})
            page.route('**/*',proxy);page.goto('http://localhost/',wait_until='domcontentloaded')
            page.get_by_role('button',name='Video Production',exact=True).click();host=page.locator('#video-production-workspace')
            host.locator('[data-vp=brand_id] option[value="'+self.brand+'"]').wait_for(state='attached')
            host.get_by_label('Production brand kit',exact=True).select_option(self.brand)
            host.get_by_role('button',name='Use an example brief for this goal',exact=True).click()
            self.assertIn('Producer Test',host.get_by_label('Core objective and key messages',exact=True).input_value())
            before=host.get_by_label('Core objective and key messages',exact=True).input_value()
            host.get_by_role('button',name='Use an example brief for this goal',exact=True).click()
            self.assertEqual(host.get_by_label('Core objective and key messages',exact=True).input_value(),before)
            host.get_by_label('Core objective and key messages',exact=True).fill('Introduce our warehouse planning tools.')
            host.get_by_label('Optional supplied script',exact=True).fill('Meet our team.\n\nPlan warehouse work.\n\nBook a demo.')
            host.get_by_label('Runtime in seconds',exact=True).fill('6')
            host.get_by_label('Reviewer name',exact=True).fill('Browser producer')
            with page.expect_response(lambda r:r.url.endswith('/api/video/productions') and r.request.method=='POST') as created:
                host.get_by_role('button',name='Create script and storyboard',exact=True).click()
            production_id=created.value.json()['id']
            host.locator('[data-vp-governance] h3').wait_for(state='visible')
            self.assertIn('Font: Arial',host.locator('[data-vp-governance]').inner_text())
            host.get_by_text('Inspect frozen rules and revision',exact=True).click()
            self.assertIn('sha256',host.locator('[data-vp-governance] pre').inner_text())
            host.get_by_text('Inspect frozen rules and revision',exact=True).click()
            host.get_by_role('button',name='3. Shot planning',exact=True).click()
            first=host.locator('[data-vp-shots] .vp-card').first
            second=host.locator('[data-vp-shots] .vp-card').nth(1)
            second.get_by_label('Props',exact=True).fill('The same tablet stays in every scene')
            first.get_by_label('Wardrobe',exact=True).fill('Same blue jacket in every appearance')
            with page.expect_response(lambda r:'/shots/' in r.url and r.request.method=='PUT') as saved:
                first.get_by_role('button',name='Save shot 1',exact=True).click()
            self.assertEqual(saved.value.status,200,saved.value.text())
            self.assertEqual(second.get_by_label('Props',exact=True).input_value(),'The same tablet stays in every scene')
            with page.expect_response(lambda r:'/shots/' in r.url and r.request.method=='PUT'):
                second.get_by_role('button',name='Save shot 2',exact=True).click()
            first.get_by_label('Wardrobe',exact=True).fill('Unsaved local wardrobe change')
            prefix='/api/video/productions/'+production_id;current=self.client.get(prefix).json();remote=current['shots'][0]
            changed=self.client.put(prefix+'/shots/'+remote['id'],json=dict(expected_version=current['version'],shot={**remote['input'],'props':'Approved tablet from another editor'}))
            self.assertEqual(changed.status_code,200,changed.text)
            host.get_by_role('button',name='Refresh',exact=True).click()
            first.locator('[data-draft-status]').filter(has_text='another session').wait_for()
            self.assertEqual(first.get_by_label('Wardrobe',exact=True).input_value(),'Unsaved local wardrobe change')
            first.get_by_role('button',name='Save shot 1',exact=True).click()
            page.wait_for_function("document.querySelector('[data-vp-status]').textContent.includes('changed since')")
            self.assertEqual(self.client.get(prefix).json()['shots'][0]['input']['props'],'Approved tablet from another editor')
            page.screenshot(path=str(evidence/'draft-conflict.png'),full_page=True)
            first.get_by_role('button',name='Discard unsaved edits for shot 1',exact=True).click()
            self.assertEqual(first.get_by_label('Props',exact=True).input_value(),'Approved tablet from another editor')
            first.get_by_label('Still-image motion',exact=True).select_option('pan')
            first.get_by_label('Motion-graphics background',exact=True).select_option('geometric')
            with page.expect_response(lambda r:'/shots/' in r.url and r.request.method=='PUT'):
                first.get_by_role('button',name='Save shot 1',exact=True).click()
            saved_input=self.client.get(prefix).json()['shots'][0]['input']
            self.assertEqual(saved_input['motion'],'pan');self.assertEqual(saved_input['background_style'],'geometric')
            page.screenshot(path=str(evidence/'shot-planning.png'),full_page=True)
            host.get_by_role('button',name='2. Script',exact=True).click()
            host.get_by_role('button',name='Approve current production script',exact=True).click()
            page.wait_for_function("document.querySelector('[data-vp-status]').textContent.includes('Saved')")
            host.get_by_role('button',name='4. Generation',exact=True).click()
            concept=host.locator('[data-review-shot="'+remote['id']+'"][data-review-pass="concept"]')
            concept.get_by_role('button',name='Generate concept · shot 1',exact=True).click()
            page.wait_for_function("document.querySelector('[data-review-pass=concept] [data-candidate]').value!==''",timeout=90000)
            concept.get_by_label('Show rule-of-thirds guides (preview only)',exact=True).check()
            self.assertTrue(concept.locator('.vp-framing-grid').is_visible())
            concept.get_by_label('Review feedback',exact=True).fill('Keep the same wardrobe in every shot.')
            concept.get_by_label('Correction area',exact=True).select_option('continuity')
            concept.get_by_role('button',name='Reject concept · shot 1',exact=True).click()
            concept.locator('[data-take-review]').filter(has_text='Rejected by Browser producer').wait_for()
            self.assertIn('wardrobe',concept.locator('[data-take-preview]').inner_text())
            page.screenshot(path=str(evidence/'take-review.png'),full_page=True)
            host.get_by_role('button',name='2. Script',exact=True).click()
            page.set_viewport_size({'width':390,'height':844});self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            page.screenshot(path=str(evidence/'mobile-production.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.get_by_role('button',name='Image & GIF Studio',exact=True).click()
            self.assertTrue(page.locator('#image-workspace').is_visible())
            # The compiled timeline is covered by test_06. Exercise the same
            # browser bridge independently with an owned, editable media fixture.
            project=self.client.post('/api/video/projects',json=dict(name='Producer editor handoff',canvas=dict(width=1280,height=720,fps=30),
                clips=[dict(asset_id=self.guideline['rules']['logo_asset_id'],duration=2)]))
            self.assertEqual(project.status_code,200,project.text)
            page.evaluate("id=>window.dispatchEvent(new CustomEvent('lexnis:producer-project',{detail:{project_id:id}}))",project.json()['id'])
            page.wait_for_function("document.querySelector('#ve-name').value==='Producer editor handoff'")
            page.locator('#ve-lanes').wait_for(state='visible')
            self.assertIn('approved-logo.png',page.locator('#ve-lanes').inner_text())
            page.screenshot(path=str(evidence/'editor-handoff.png'),full_page=True)
            self.assertFalse(errors,errors);context.unroute_all(behavior='ignoreErrors');browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
