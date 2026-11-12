"""Offline video API, security, adapters and real FFmpeg export integration tests."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-video-test-')
os.environ['VIDEO_DATA_DIR']=TEMP.name
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from video_api import router
from video_storage import DATA, MAX_UPLOAD, read
from video_ffmpeg import ffmpeg, probe, binary
from video_assets import ingest, path_for
from video_jobs import jobs
from video_engine import Generate, generate
from video_projects import Project, Clip, Canvas
from video_editor import render
from video_security import VideoRequestLimits

app=FastAPI();app.include_router(router)
app.add_middleware(VideoRequestLimits)


def wait(client, job):
    end=time.monotonic()+90
    while time.monotonic()<end:
        item=client.get('/api/video/jobs/'+job['id']).json()
        if item['state'] in ('completed','failed','cancelled'):
            return item
        time.sleep(.1)
    raise AssertionError('Job timeout')


class VideoStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not binary('ffmpeg') or not binary('ffprobe'):
            raise RuntimeError('Install FFmpeg AND FFprobe to execute the required integration tests')
        cls.client=TestClient(app)
        cls.source=DATA/'work/source.mp4'
        ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                '-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(cls.source)])
        with cls.source.open('rb') as f:
            response=cls.client.post('/api/video/upload',files={'file':('real.mp4',f,'video/mp4')})
        assert response.status_code==200,response.text
        cls.video=response.json()
        buf=io.BytesIO();Image.new('RGB',(160,160),'#ff2233').save(buf,format='PNG')
        cls.picture=cls.client.post('/api/video/upload',files={'file':('logo.png',buf.getvalue(),'image/png')}).json()

    def test_metadata_and_range_download(self):
        self.assertEqual(self.video['width'],320)
        self.assertAlmostEqual(self.video['duration'],3,places=1)
        self.assertTrue(self.video['has_audio'])
        result=self.client.get(self.video['url'],headers={'Range':'bytes=0-99'})
        self.assertEqual(result.status_code,206)
        self.assertEqual(len(result.content),100)

    def test_invalid_uploads_and_origin(self):
        for name,data in [('fake.mp4',b'not-a-video'),('bad.svg',b'<svg/>'),('bad.png',b'<svg/>'),('playlist.mp4',b'#EXTM3U\nhttp://attacker/')]:
            with self.subTest(name=name):
                self.assertEqual(self.client.post('/api/video/upload',files={'file':(name,data)}).status_code,400)
        self.assertEqual(self.client.get('/api/video/assets',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/video/assets',headers={'Origin':'http://testserver'}).status_code,200)
        with patch('video_api.MAX_UPLOAD',10):
            self.assertEqual(self.client.post('/api/video/upload',files={'file':('large.png',b'x'*11)}).status_code,413)
        self.assertFalse(list((DATA/'work').glob('tmp*.png')))

    def test_paths_and_limits(self):
        for url in ['C:/Windows/win.ini','file:///etc/passwd','https://host/video.mp4','/renders/../.env','/uploads/%2e%2e%5c.env','/static/assets/../../.env']:
            self.assertEqual(self.client.post('/api/video/import',json={'source_url':url}).status_code,400)
        self.assertEqual(self.client.get('/api/video/download/not-an-id').status_code,400)
        clip=dict(asset_id=self.video['id'],duration=1)
        for project in [dict(canvas={'width':8000}),dict(clips=[clip]*61),dict(clips=[{**clip,'speed':0}]),dict(clips=[{**clip,'duration':999}]),dict(clips=[{**clip,'asset_id':'../../.env'}])]:
            self.assertEqual(self.client.post('/api/video/projects',json=project).status_code,422)
        self.assertEqual(self.client.post('/api/video/export',json={'project':{'clips':[dict(asset_id=self.video['id'],trim=2.5,duration=2)]}}).status_code,400)

    def test_direct_campaign_import_preserves_original(self):
        import hashlib
        from video_storage import uid
        source=ROOT/'output/renders'/('video-import-test-'+uid()+'.png')
        source.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(160,100),'#123456').save(source)
        original=hashlib.sha256(source.read_bytes()).hexdigest()
        try:
            response=self.client.post('/api/video/import',json={'source_url':'/renders/'+source.name})
            self.assertEqual(response.status_code,200,response.text)
            imported=response.json()
            self.assertEqual(hashlib.sha256(path_for(imported['id']).read_bytes()).hexdigest(),original)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
        finally:
            source.unlink(missing_ok=True)

    def test_request_limits_before_multipart_parser(self):
        with patch('video_security.MAX_UPLOAD',10):
            # The middleware's configured limit includes up to one MB of multipart headers.
            response=self.client.post('/api/video/upload',content=b'',headers={'Content-Length':str(2*1024**2)})
            self.assertEqual(response.status_code,413)
        response=self.client.post('/api/video/upload',content=b'not multipart',headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get(self.video['url'],headers={'Range':'bytes=999999999999-'}).status_code,416)

    def test_project_lifecycle(self):
        body={'name':'Original','clips':[{'asset_id':self.video['id'],'duration':1}]}
        project=self.client.post('/api/video/projects',json=body).json();key=project['id']
        self.assertEqual(self.client.get('/api/video/projects/'+key).json()['name'],'Original')
        body['name']='Renamed';self.assertEqual(self.client.put('/api/video/projects/'+key,json=body).status_code,200)
        clone=self.client.post('/api/video/projects/'+key+'/duplicate').json()
        self.assertNotEqual(clone['id'],key)
        self.assertEqual(clone['clips'][0]['asset_id'],self.video['id'])
        self.assertEqual(self.client.delete('/api/video/projects/'+key).status_code,200)
        self.assertEqual(self.client.get('/api/video/projects/'+key).status_code,404)
        self.assertTrue(path_for(self.video['id']).is_file())

    def test_real_timeline_crossfade_overlay_arabic_audio(self):
        project=Project(name='Integration',canvas=Canvas(width=320,height=180),clips=[
            Clip(asset_id=self.video['id'],trim=.25,duration=1.25,brightness=.05,fade_in=.1),
            Clip(asset_id=self.picture['id'],duration=1.25,transition=.25,zoom=1.1,pan=.2),
            Clip(kind='title',text='Welcome / مرحبا',duration=1.5,font_size=48,y=.8,fade_in=.2),
            Clip(kind='overlay',asset_id=self.picture['id'],duration=1,scale=.2,opacity=.7,x=.9,y=.1),
            Clip(kind='audio',asset_id=self.video['id'],duration=2,volume=.15,fade_in=.1,fade_out=.2)])
        response=self.client.post('/api/video/export',json={'project':project.model_dump()})
        self.assertEqual(response.status_code,202,response.text)
        job=wait(self.client,response.json());self.assertEqual(job['state'],'completed',job)
        meta=probe(path_for(job['result']['id']))
        self.assertEqual((meta['width'],meta['height']),(320,180))
        self.assertEqual(meta['video_codec'],'h264');self.assertTrue(meta['has_audio'])
        self.assertAlmostEqual(meta['duration'],2.25,delta=.15);self.assertEqual(meta['fps'],24)
        still=DATA/'work/frame.png';ffmpeg(['-ss','0.5','-i',str(path_for(job['result']['id'])),'-frames:v','1',str(still)])
        with Image.open(still) as im:
            self.assertGreater(im.getpixel((270,25))[0],120)

    def test_cpu_animation_and_webm_without_audio(self):
        response=self.client.post('/api/video/generate',json={'mode':'image-animation','asset_id':self.picture['id'],
                                  'duration':1,'resolution':720,'aspect':'1:1','motion':'zoom-out'})
        job=wait(self.client,response.json());self.assertEqual(job['state'],'completed',job)
        self.assertEqual(job['result']['generation_type'],'deterministic-image-animation')
        self.assertFalse(job['result']['has_audio']);self.assertEqual(job['result']['width'],720)
        project=Project(canvas=Canvas(width=320,height=180,fps=30),clips=[Clip(asset_id=self.video['id'],duration=.5)])
        job=wait(self.client,self.client.post('/api/video/export',json={'project':project.model_dump(),'container':'webm','audio':False}).json())
        self.assertEqual(job['state'],'completed',job);self.assertEqual(job['result']['fps'],30)
        self.assertFalse(job['result']['has_audio'])

    def test_audio_extraction(self):
        job=wait(self.client,self.client.post(f"/api/video/assets/{self.video['id']}/extract-audio").json())
        self.assertEqual(job['state'],'completed',job);self.assertEqual(job['result']['kind'],'audio')

    def test_model_gates_and_adapters(self):
        self.assertEqual(self.client.post('/api/video/generate',json={'prompt':'A robot waves','model':'cogvideox-2b'}).status_code,400)
        self.assertEqual(self.client.post('/api/video/generate',json={'prompt':'A robot waves','mode':'image-to-video','model':'cogvideox-2b','asset_id':self.picture['id']}).status_code,400)
        spec=importlib.util.spec_from_file_location('worker',ROOT/'scripts/render_local_video.py');worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        torch=SimpleNamespace(float16='fp16',bfloat16='bf16',float32='fp32')
        diffusers=Mock();request=dict(model='cogvideox-2b',mode='text-to-video',model_path='managed-cache')
        pipe=worker.build_pipeline(request,torch,diffusers)
        diffusers.CogVideoXPipeline.from_pretrained.assert_called_once_with('managed-cache',torch_dtype='fp16',local_files_only=True,use_safetensors=True)
        pipe.enable_sequential_cpu_offload.assert_called_once()
        worker.build_pipeline(dict(request,model='wan21-i2v-480p',mode='image-to-video',image='managed-image.png'),torch,diffusers)
        diffusers.WanImageToVideoPipeline.from_pretrained.assert_called_once()
        with self.assertRaises(ValueError):worker.build_pipeline(dict(request,mode='image-to-video'),torch,diffusers)

    def test_ai_orchestration_with_mock_worker_and_real_output_validation(self):
        import shutil
        from video_jobs import Job
        from video_models import MODELS
        native=DATA/'work/mock-native.mp4'
        ffmpeg(['-f','lavfi','-i','testsrc2=size=720x480:rate=8','-frames:v','49','-c:v','libx264','-pix_fmt','yuv420p',str(native)])
        cache=DATA/'work/mock-cache';(cache/'cogvideox-2b').mkdir(parents=True)
        (cache/'cogvideox-2b/installation.json').write_text(json.dumps({'revision':'test-fixture'}))
        class Process:
            returncode=0
            def __init__(self):self.calls=0
            def poll(self):
                self.calls+=1
                return None if self.calls==1 else 0
            def wait(self):return 0
        def fake_spawn(args,**kwargs):
            self.assertTrue(args[2].endswith('render_local_video.py'))
            self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'],'1')
            self.assertFalse(kwargs['shell'])
            payload=json.loads(Path(args[-1]).read_text())
            shutil.copyfile(native,payload['output'])
            Path(payload['progress']).write_text(json.dumps({'step':2,'total_steps':20}))
            return Process()
        model=dict(id='cogvideox-2b',**MODELS['cogvideox-2b'],available=True,reasons=[])
        job=Job('mock-ai-contract')
        with patch('video_engine.statuses',return_value=[model]),patch('video_models.hardware',return_value={'gpu':{'free_gb':8}}),\
             patch('video_engine.CACHE',cache),patch('video_engine.spawn_worker',side_effect=fake_spawn),\
             patch.object(job,'update',wraps=job.update) as updates:
            result=generate(Generate(prompt='A robot waves',quality='draft'),job)
            with patch('video_engine.probe',return_value={'width':1,'height':1,'duration':6}):
                with self.assertRaisesRegex(ValueError,'expected native'):
                    generate(Generate(prompt='A robot waves'),Job('bad-native-contract'))
        self.assertEqual(result['generation_type'],'text-to-video')
        self.assertEqual((result['native_width'],result['native_height']),(720,480))
        self.assertEqual(result['revision'],'test-fixture')
        self.assertTrue(any(call.kwargs.get('state')=='running' for call in updates.call_args_list))
        self.assertFalse(list((DATA/'work').glob(job.id+'-*')))

    def test_cancel_real_subprocess_and_persistent_errors(self):
        def slow(job):
            job.update(state='running')
            ffmpeg(['-re','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','30','-f','null','-'],job)
        job=jobs.submit('cancel-test',slow);time.sleep(.3)
        self.client.post('/api/video/jobs/'+job['id']+'/cancel')
        result=wait(self.client,job);self.assertEqual(result['state'],'cancelled')
        self.assertEqual(read('jobs',job['id'])['state'],'cancelled')
        def oom(job):raise RuntimeError('CUDA out of memory')
        failed=wait(self.client,jobs.submit('oom-test',oom))
        self.assertEqual(failed['state'],'failed');self.assertIn('GPU out of memory',failed['error'])
        def sensitive(job):raise OSError('C:/private/secret.env contains token')
        failure=wait(self.client,jobs.submit('private-error',sensitive));self.assertNotIn('private',failure['error'])
        def impossible(job):return render(Project(),job)
        self.assertEqual(wait(self.client,jobs.submit('empty-export',impossible))['state'],'failed')


if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:
        jobs.executor.shutdown(wait=True)
        jobs.gpu_executor.shutdown(wait=True)
        diagnostics=DATA/'work/last-ffmpeg-error.log'
        if diagnostics.is_file():
            (ROOT/'output/video-test-last-error.log').write_text(diagnostics.read_text(encoding='utf-8'),encoding='utf-8')
        TEMP.cleanup()
