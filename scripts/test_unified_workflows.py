"""Guest prompt assistance and real brand-aware video generation regressions.

The local HTTP model is a protocol fixture, never proof of real model inference.
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-unified-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
from fastapi.testclient import TestClient
from PIL import Image
import server


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.a=TestClient(server.app,base_url='https://testserver')
        self.b=TestClient(server.app,base_url='https://testserver')
        self.a.get('/');self.b.get('/')

    def call(self,method,path,body=None,status=200,client=None,**kwargs):
        r=(client or self.a).request(method,path,json=body,**kwargs)
        self.assertEqual(r.status_code,status,r.text[:1800]);return r.json()

    def guide(self):
        doc=self.call('POST','/api/guidelines',files={'file':('brand.md',b'Brand: Noor Solar\nPrimary color: #ffffff\nFonts: Arial\nCTA: Book a demo\nAnimation: smooth and subtle\n')},status=201)
        return self.call('PUT','/api/guidelines/'+doc['id'],dict(expected_version=doc['version'],rules=doc['rules'],confirmed=True))

    def test_editing_setup_drives_prompt_titles_logo_and_real_export(self):
        source=io.BytesIO();Image.new('RGB',(320,240),'#223344').save(source,'PNG')
        logo=io.BytesIO();Image.new('RGBA',(80,40),'#e4572e').save(logo,'PNG')
        media=self.call('POST','/api/video/upload',files={'file':('footage.png',source.getvalue())})
        mark=self.call('POST','/api/video/upload',files={'file':('logo.png',logo.getvalue())})
        brief=dict(purpose='team_welcome',person_name='Amal Hassan',person_position='Marketing Manager',logo_asset_id=mark['id'],instruction='Keep the introduction clean.')
        suggestion=self.call('POST','/api/creative/assistant/suggest',dict(task='video-edit',editing_brief=brief,max_chars=1000))
        for expected in ['team welcome','Amal Hassan','Marketing Manager','uploaded logo']:
            self.assertIn(expected,suggestion['prompt'])
        project=self.call('POST','/api/video/projects',dict(name='Welcome setup',canvas=dict(width=320,height=240,fps=24),editing_brief=brief,clips=[dict(asset_id=media['id'],duration=1)]))
        self.assertEqual(project['editing_brief'],brief)
        path='/api/video/projects/'+project['id']
        proposed=self.call('POST',path+'/brand-edit/preview',dict(engine='rule_engine',instruction=suggestion['prompt']))
        saved=self.call('POST',path+'/brand-edit/apply',dict(plan_id=proposed['id'],confirm_conflicts=True))
        self.assertTrue(any(c['kind']=='overlay' and c['asset_id']==mark['id'] for c in saved['clips']))
        self.assertTrue(any(c['text']=='Amal Hassan' and c['text_role']=='speaker_name' for c in saved['clips']))
        self.assertTrue(any(c['text']=='Marketing Manager' and c['text_role']=='speaker_role' for c in saved['clips']))
        again=self.call('POST',path+'/brand-edit/preview',dict(engine='rule_engine',instruction='Polish again'))
        self.assertEqual(sum(c['text_role']=='speaker_name' for c in again['proposed_project']['clips']),1)
        job=self.call('POST','/api/video/export',dict(project=proposed['proposed_project'],container='mp4',audio=False),status=202)
        for _ in range(600):
            state=self.call('GET','/api/video/jobs/'+job['id'])
            if state['state'] in {'completed','failed','cancelled'}:break
            time.sleep(.1)
        self.assertEqual(state['state'],'completed',state)
        output=Path(TEMP.name)/'setup-export.mp4';output.write_bytes(self.a.get('/api/video/download/'+state['result']['id']).content)
        from video.ffmpeg import ffmpeg
        frame=Path(TEMP.name)/'setup-frame.png'
        ffmpeg(['-i',str(output),'-ss','0.5','-frames:v','1',str(frame)],timeout=30)
        with Image.open(frame).convert('RGB') as image:
            crop=image.crop((240,15,305,60))
            red=sum(r>150 and r>g*1.4 and r>b*1.4 for r,g,b in [crop.getpixel((x,y)) for x in range(crop.width) for y in range(crop.height)])
            self.assertGreater(red,100,'Uploaded logo must be visible in the actual exported pixels')
        self.assertEqual(self.a.get('/api/video/media/'+media['id']).content,source.getvalue())

    def test_editing_logo_is_private_and_conflicting_guideline_requires_review(self):
        raw=io.BytesIO();Image.new('RGB',(80,40),'#ff0000').save(raw,'PNG')
        first=self.call('POST','/api/video/upload',files={'file':('brand-logo.png',raw.getvalue())})
        second=self.call('POST','/api/video/upload',files={'file':('replacement.png',raw.getvalue())})
        brief=dict(purpose='team_welcome',logo_asset_id=second['id'])
        self.call('POST','/api/creative/assistant/suggest',dict(task='video-edit',editing_brief=brief),client=self.b,status=404)
        doc=self.guide();rules=dict(doc['rules'],logo_asset_id=first['id'])
        project=self.call('POST','/api/video/projects',dict(name='Logo conflict',brand_rules=rules,editing_brief=brief,
            clips=[dict(asset_id=first['id'],duration=1),dict(kind='overlay',asset_id=first['id'],duration=1,scale=.15)]))
        path='/api/video/projects/'+project['id']
        result=self.call('POST',path+'/brand-edit/preview',dict(engine='rule_engine',instruction='Use the uploaded logo'))
        self.assertTrue(any('logo' in item for item in result['conflicts']))
        self.call('POST',path+'/brand-edit/apply',dict(plan_id=result['id']),status=400)
        self.assertFalse(any(c['kind']=='overlay' and c['asset_id']==first['id'] for c in result['proposed_project']['clips']))

    def test_task_aware_templates_actual_context_and_isolation(self):
        doc=self.guide();texts=[]
        for task in ['image','gif','video-generation','video-edit','campaign','copy','audio','web','crm']:
            result=self.call('POST','/api/creative/assistant/suggest',dict(task=task,prompt='Welcome Amal to our team',
                objective='Introduce our new colleague',platform='LinkedIn',output_format='portrait',guideline_id=doc['id']))
            self.assertFalse(result['ai_used']);self.assertEqual(result['engine'],'template')
            self.assertIn('Welcome Amal',result['prompt']);self.assertIn('Noor Solar',result['prompt'])
            self.assertIn('LinkedIn',result['prompt']);self.assertIn('Book a demo',result['prompt']);texts.append(result['prompt'])
        self.assertEqual(len(set(texts)),9)
        self.call('POST','/api/creative/assistant/suggest',dict(task='gif',prompt='Welcome',guideline_id=doc['id']),client=self.b,status=404)
        self.call('POST','/api/creative/assistant/suggest',dict(task='image'),status=400)
        self.call('POST','/api/creative/assistant/suggest',dict(task='image',prompt='Idea',command='run'),status=422)
        self.call('POST','/api/creative/assistant/suggest',dict(task='image',prompt='Idea'),headers={'Origin':'https://evil.test'},status=403)
        with patch.dict(os.environ,{'LOCAL_TEXT_URL':''}):
            cap=self.call('GET','/api/creative/assistant/capabilities');self.assertFalse(cap['ai']['available'])
            self.call('POST','/api/creative/assistant/suggest',dict(task='gif',prompt='Idea',engine='local_ai'),status=409)

    def test_real_cpu_generation_applies_guideline_and_preserves_source(self):
        doc=self.guide();buffer=io.BytesIO();Image.new('RGB',(320,240),'#223344').save(buffer,'PNG');source=buffer.getvalue()
        asset=self.call('POST','/api/video/upload',files={'file':('employee.png',source)})
        job=self.call('POST','/api/video/generate',dict(mode='image-animation',asset_id=asset['id'],duration=1,
            motion='still',guideline_id=doc['id'],guideline_version=doc['version'],prompt='Welcome Amal',objective='Welcome a colleague',platform='LinkedIn'),status=202)
        for _ in range(600):
            state=self.call('GET','/api/video/jobs/'+job['id'])
            if state['state'] in {'failed','completed','cancelled'}:break
            time.sleep(.1)
        self.assertEqual(state['state'],'completed',state)
        result=state['result'];self.assertEqual(result['guideline_id'],doc['id'])
        project=self.call('GET','/api/video/projects/'+result['project_id'])
        self.assertEqual(project['brand_rules']['brand_name'],'Noor Solar')
        self.assertEqual(project['creative_context']['objective'],'Welcome a colleague')
        self.assertEqual(project['creative_context']['platform'],'LinkedIn')
        self.assertTrue(any(c['text']=='Book a demo' for c in project['clips']))
        self.assertIn('Welcome Amal',result['creation_prompt'])
        self.assertEqual(self.a.get('/api/video/media/'+asset['id']).content,source)
        self.assertGreater(len(self.a.get('/api/video/download/'+result['id']).content),1000)
        self.call('GET','/api/video/projects/'+result['project_id'],client=self.b,status=404)
        self.assertEqual(self.b.get('/api/video/download/'+result['id']).status_code,404)
        # Project revisions and checked operations remain available for further edits.
        history=self.call('GET','/api/video/projects/'+result['project_id']+'/revisions')
        self.assertTrue(history['revisions'])

    def test_generation_rejects_unreviewed_stale_and_other_guest_documents(self):
        doc=self.guide();buffer=io.BytesIO();Image.new('RGB',(64,64)).save(buffer,'PNG')
        asset=self.call('POST','/api/video/upload',files={'file':('photo.png',buffer.getvalue())})
        body=dict(mode='image-animation',asset_id=asset['id'],guideline_id=doc['id'],guideline_version=doc['version']+1)
        self.call('POST','/api/video/generate',body,status=400)
        raw=self.call('POST','/api/guidelines',files={'file':('unreviewed.txt',b'Brand: Unreviewed')},status=201)
        self.call('POST','/api/video/generate',dict(body,guideline_id=raw['id'],guideline_version=None),status=400)
        self.call('POST','/api/video/generate',dict(body,guideline_version=None),client=self.b,status=404)
        self.call('POST','/api/video/generate',dict(body,brand_rules={'brand_name':'Override'}),status=422)

    def test_real_http_model_protocol(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.send(dict(data=[dict(id='fixture-model')]))
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body))
                self.send(dict(tokens=[1,2,3]) if self.path=='/tokenize' else dict(choices=[dict(message=dict(content=json.dumps(dict(prompt='Review a portrait welcome animation for Amal using the approved CTA.',missing_details=['Confirm audience']))))]))
            def send(self,data):
                raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        fixture=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=fixture.serve_forever,daemon=True);thread.start()
        try:
            doc=self.guide()
            with patch.dict(os.environ,dict(LOCAL_TEXT_URL='http://127.0.0.1:'+str(fixture.server_port),LOCAL_TEXT_MODEL='fixture-model')):
                result=self.call('POST','/api/creative/assistant/suggest',dict(task='gif',prompt='Welcome Amal',guideline_id=doc['id'],engine='local_ai'))
                self.assertTrue(result['ai_used']);self.assertIn('Amal',result['prompt'])
            chat=next(body for path,body in calls if path=='/v1/chat/completions')
            self.assertIn('Noor Solar',chat['messages'][1]['content']);self.assertIn('Welcome Amal',chat['messages'][1]['content'])
            self.assertIn('json_schema',chat['response_format'])
        finally:fixture.shutdown();fixture.server_close();thread.join(timeout=5)


if __name__=='__main__':unittest.main(verbosity=2)
