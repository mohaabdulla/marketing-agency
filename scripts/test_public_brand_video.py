"""Real public-cookie isolation, document parsing, branded edits and FFmpeg output."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-public-brand-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
from fastapi.testclient import TestClient
from PIL import Image
import server
from video.ffmpeg import ffmpeg, probe


class PublicBrandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video=Path(TEMP.name)/'source.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=0x202020:s=320x240:d=3:r=24','-c:v','libx264','-pix_fmt','yuv420p',str(cls.video)],timeout=30)
        cls.source_hash=__import__('hashlib').sha256(cls.video.read_bytes()).hexdigest()
        buffer=io.BytesIO();Image.new('RGB',(200,100),'#223344').save(buffer,'PNG');cls.png=buffer.getvalue()

    def setUp(self):
        self.a=TestClient(server.app,base_url='https://testserver')
        self.b=TestClient(server.app,base_url='https://testserver')
        self.assertEqual(self.a.get('/').status_code,200)
        self.assertEqual(self.b.get('/').status_code,200)

    def call(self,method,path,body=None,client=None,status=200,**kwargs):
        response=(client or self.a).request(method,path,json=body,**kwargs)
        self.assertEqual(response.status_code,status,response.text[:1500])
        return response

    def upload(self,data,name):
        return self.call('POST','/api/video/upload',files={'file':(name,data)}).json()

    def project(self):
        asset=self.upload(self.video.read_bytes(),'original.mp4')
        result=self.call('POST','/api/video/projects',dict(name='Guest project',canvas=dict(width=320,height=240,fps=24),
                         clips=[dict(asset_id=asset['id'],kind='video',duration=3)])).json()
        return result,asset

    def guideline(self,raw=None,name='brand.txt'):
        raw=raw or b'Brand: Noor\nPrimary colors: #223344\nFonts: Arial\nCTA: Book a demo\nRequired disclosure: Sponsored\nAnimation: smooth and subtle\nMax duration: 3\n'
        return self.call('POST','/api/guidelines',files={'file':(name,raw)},status=201).json()

    def confirm(self,doc,**changes):
        return self.call('PUT','/api/guidelines/'+doc['id'],dict(expected_version=doc['version'],confirmed=True,
                         rules=dict(doc['rules'],**changes))).json()

    def test_review_accepts_color_names_and_preserves_validated_hex(self):
        doc=self.guideline()
        confirmed=self.confirm(doc,primary_colors=['blue', ' #AbC '],secondary_colors=[' GREEN '],caption_color='White')
        self.assertEqual(confirmed['rules']['primary_colors'],['#0000ff', '#AAbbCC'])
        self.assertEqual(confirmed['rules']['secondary_colors'],['#008000'])
        self.assertEqual(confirmed['rules']['caption_color'],'#ffffff')
        stored=self.call('GET','/api/guidelines/'+doc['id']).json()
        self.assertEqual(stored['rules'],confirmed['rules'])
        for invalid in ['company blue', 'transparent', '#12345678', 'rgb(0,0,255)', 123]:
            response=self.call('PUT','/api/guidelines/'+doc['id'],dict(expected_version=confirmed['version'],
                rules=dict(confirmed['rules'],primary_colors=[invalid])),status=422)
            self.assertIn('CSS color name',response.text)
        self.assertEqual(self.call('GET','/api/guidelines/'+doc['id']).json()['version'],confirmed['version'])

    def test_upload_normalizes_named_colors_in_json_and_text(self):
        for name,raw in [('brand.json',b'{"primary_colors":["blue"],"secondary_colors":["green"]}'),
                         ('brand.txt',b'Primary colors: blue\nSecondary colors: green\nCaption color: white')]:
            doc=self.guideline(raw,name)
            self.assertEqual(doc['rules']['primary_colors'],['#0000ff'])
            self.assertEqual(doc['rules']['secondary_colors'],['#008000'])

    def wait(self,job):
        for _ in range(200):
            state=self.call('GET','/api/video/jobs/'+job['id']).json()
            if state['state'] in {'completed','failed','cancelled'}:
                self.assertEqual(state['state'],'completed',state)
                return state['result']
            time.sleep(.1)
        self.fail('Render deadline exceeded')

    def test_cookie_isolation_admin_and_existing_local_mode(self):
        session=self.call('GET','/api/session').json()
        self.assertTrue(session['guest'])
        self.assertNotEqual(session['workspace'],self.b.get('/api/session').json()['workspace'])
        self.assertIn('HttpOnly',self.a.get('/api/session').headers['set-cookie'])
        project,asset=self.project()
        for path in ['/api/video/projects/'+project['id'],asset['url'],'/api/video/download/'+asset['id']]:
            self.call('GET',path,client=self.b,status=404)
        self.call('GET','/api/video/projects/'+project['id'],client=self.b,status=404,headers={'X-User-ID':session['workspace']})
        self.call('GET','/api/system/capabilities',status=403)
        self.call('POST','/api/video/projects',dict(name='CSRF'),status=403,headers={'Origin':'https://evil.example'})
        self.call('GET','/static/assets/brand_kits.json',status=404)
        self.call('GET','/test_assets/raw_subject.jpg',status=404)
        with patch.dict(os.environ,PUBLIC_TEST_MODE='false'):
            self.assertEqual(TestClient(server.app).get('/api/session').json()['public_test_mode'],False)
            self.assertEqual(TestClient(server.app).get('/api/video/projects').status_code,200)
            self.assertEqual(TestClient(server.app,base_url='http://untrusted.example').get('/api/video/projects').status_code,403)

    def test_shared_image_guideline_upload_and_documents(self):
        legacy=self.call('POST','/api/upload-guidelines',files={'file':('brand.md',b'Brand: Shared\nPrimary color: #abcdef\n')}).json()
        self.assertEqual(legacy['brand_dna']['brand_colors']['primary'],'#abcdef')
        self.assertIn('Shared',legacy['files'][0]['guidelines'])
        self.assertEqual(self.call('GET','/api/guidelines/'+legacy['guideline_id']).json()['rules']['brand_name'],'Shared')
        self.call('GET','/api/guidelines/'+legacy['guideline_id'],client=self.b,status=404)
        import fitz
        pdf=fitz.open();page=pdf.new_page();page.insert_text((30,40),'Brand: Paper\nPrimary color: #123456');raw=pdf.tobytes();pdf.close()
        doc=self.guideline(raw,'brand.pdf');self.assertEqual(doc['rules']['brand_name'],'Paper')
        from docx import Document
        word=Document();word.add_paragraph('Brand: Word Brand');word.add_paragraph('CTA: Contact us');buffer=io.BytesIO();word.save(buffer)
        doc=self.guideline(buffer.getvalue(),'brand.docx');self.assertEqual(doc['rules']['cta'],'Contact us')
        original=self.call('GET',doc['originals'][0]['url'])
        self.assertEqual(original.content,buffer.getvalue())
        self.assertNotIn(str(ROOT),json.dumps(doc))
        for name,raw in [('x.pdf',b'not a pdf'),('x.docx',b'not a zip'),('x.json',b'{"a":NaN}'),('x.txt',b'\x00invalid')]:
            self.call('POST','/api/guidelines',files={'file':(name,raw)},status=422)
        self.call('POST','/api/guidelines',files={'file':('broken.pdf',b'%PDF-1.7\nbroken')},status=422)
        conflict=self.guideline(b'Primary color: #123456\nPrimary color: #abcdef')
        self.assertTrue(conflict['review']['conflicting_rules'])
        reviewed=self.confirm(conflict,brand_name='Operator correction')
        self.assertTrue(reviewed['review']['operator_changes'])
        self.assertIn('Primary color',reviewed['source_text'])

    def test_guest_brand_kits_and_expired_session_cleanup(self):
        image=self.call('POST','/api/upload-visual',files={'file':('logo.png',self.png)}).json()
        kit=self.call('POST','/api/brands',dict(brand_name='Own brand',primary_hex='#123456',accent_hex='#abcdef',
                      logo_path=image['file_url']),status=201).json()['brand']
        self.assertEqual(self.call('GET','/api/brands',client=self.b).json()['brands'],[])
        imported=self.call('POST','/api/guidelines/from-brand/'+kit['id'],status=201).json()
        self.assertEqual(imported['rules']['primary_colors'],['#123456'])
        self.assertTrue(imported['rules']['logo_asset_id'])
        from core.public_access import guest_root
        key=self.a.get('/api/session').json()['workspace']
        record=guest_root()/key/'session.json'
        record.write_text(json.dumps(dict(expires=0)))
        self.call('GET','/api/video/projects',status=401)
        self.a.get('/')
        self.assertNotEqual(self.a.get('/api/session').json()['workspace'],key)
        self.assertEqual(self.a.get('/api/video/projects').json(),[])
        import subprocess
        cleanup=subprocess.run([sys.executable,str(ROOT/'scripts/cleanup_public_workspaces.py'),'--apply'],
                               capture_output=True,text=True,env=os.environ,timeout=20)
        self.assertEqual(cleanup.returncode,0,cleanup.stderr)
        self.assertFalse(record.parent.exists())

    def test_real_edit_preview_apply_render_revision_and_reload(self):
        project,asset=self.project()
        logo=self.upload(self.png,'approved-logo.png')
        doc=self.confirm(self.guideline(),logo_asset_id=logo['id'],logo_placement='top-right')
        project=self.call('POST','/api/video/projects/'+project['id']+'/guidelines',dict(guideline_id=doc['id'])).json()
        url='/api/video/projects/'+project['id']
        plan=self.call('POST',url+'/brand-edit/preview',dict(instruction='Follow our brand and improve the audio balance.',engine='rule_engine')).json()
        self.assertEqual(plan['engine'],'rule_engine')
        self.assertEqual(self.call('GET',url).json()['clips'],project['clips'],'Preview must be non-destructive')
        saved=self.call('POST',url+'/brand-edit/apply',dict(plan_id=plan['id'])).json()
        self.assertTrue(any(c['text']=='Book a demo' for c in saved['clips']))
        self.assertTrue(any(c['asset_id']==logo['id'] for c in saved['clips']))
        report=self.call('GET',url+'/brand-compliance').json()
        self.assertTrue(report['passed'],report)
        self.assertTrue(any(x['state']=='NOT_CHECKED' for x in report['findings']))
        clean={k:v for k,v in saved.items() if k not in {'id','created','updated'}}
        job=self.call('POST','/api/video/export',dict(project=clean,container='mp4',preview=True,audio=False),status=202).json()
        rendered=self.wait(job)
        video=self.call('GET',rendered['url']).content
        self.assertGreater(len(video),1000)
        self.call('GET',rendered['url'],client=self.b,status=404)
        self.assertEqual(self.call('GET',asset['url']).content,self.video.read_bytes())
        self.assertEqual(self.call('GET',url).json()['guideline_id'],doc['id'])
        revision=self.call('POST',url+'/brand-edit/preview',dict(instruction='Make the captions larger.',engine='rule_engine')).json()
        larger=self.call('POST',url+'/brand-edit/apply',dict(plan_id=revision['id'])).json()
        self.assertGreater(next(c['font_size'] for c in larger['clips'] if c['kind']=='title'),next(c['font_size'] for c in saved['clips'] if c['kind']=='title'))
        self.call('POST',url+'/undo',{})
        restored=self.call('POST',url+'/redo',{}).json()
        self.assertEqual(restored['guideline_id'],doc['id'])
        legacy=self.call('POST',url+'/auto-polish',{}).json()
        self.assertEqual(legacy['project']['guideline_id'],doc['id'])
        self.assertTrue(all(op['source']=='rule_engine' for op in legacy['plan']['operations']))

    def test_conflicts_missing_fonts_and_stale_plans(self):
        project,_=self.project();url='/api/video/projects/'+project['id']
        doc=self.confirm(self.guideline(),font_preferences=['Unavailable Font'])
        self.call('POST',url+'/guidelines',dict(guideline_id=doc['id']))
        plan=self.call('POST',url+'/brand-edit/preview',dict(instruction='Use #ff0000 instead',engine='rule_engine')).json()
        self.assertTrue(plan['conflicts'])
        self.call('POST',url+'/brand-edit/apply',dict(plan_id=plan['id']),status=400)
        self.assertTrue(any('fallback' in w for w in plan['plan']['warnings']))
        self.call('POST',url+'/brand-edit/apply',dict(plan_id=plan['id'],confirm_conflicts=True))
        self.call('POST',url+'/brand-edit/apply',dict(plan_id=plan['id'],confirm_conflicts=True),status=400)
        with patch.dict(os.environ,LOCAL_TEXT_URL=''):
            self.call('POST',url+'/brand-edit/preview',dict(instruction='Edit with AI',engine='local_ai'),status=400)
            self.call('POST',url+'/ai/edit',dict(instruction='Edit with AI'),status=409)

    def test_private_image_upload_and_unsafe_paths(self):
        upload=self.call('POST','/api/upload-visual',files={'file':('private.png',self.png,'image/png')}).json()
        self.assertNotIn(str(ROOT),json.dumps(upload))
        self.call('POST','/api/video/import',dict(url='C:/Windows/win.ini'),status=400)
        self.call('POST','/api/creative/bridge-to-video',dict(output_path='C:/Windows/win.ini'),status=400)
        self.call('POST','/api/creative/projects',dict(project=dict(project_id='D:escape')),status=400)
        self.call('POST','/api/video/projects',dict(name='Bad',clips=[dict(kind='video',asset_id='0'*32,duration=2)]),status=404)
        a=self.call('POST','/api/agency/clients',dict(name='Private agency'),status=201).json()
        self.call('GET','/api/agency/clients/'+a['id'],client=self.b,status=404)
        self.call('POST','/api/upload-visual',files={'file':('fake.png',b'not an image')},status=400)
        self.call('POST','/api/upload-visual',files={'file':('unsafe.svg',b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')},status=400)
        self.call('POST','/api/upload-visual',files={'file':('good.png',self.png)},data={'slot':'../../escape'},status=400)
        self.call('POST','/api/upload-visual',files={'file':('external.svg',b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>')},status=400)

    def test_guest_still_gif_and_project_saving(self):
        project=dict(project_id='guest-creative',name='Guest creative',scenes=[dict(scene_id='guest-scene',duration=.5,
                     canvas=dict(width=320,height=240,fps=10,duration=.5),background=dict(type='color',value='#223344'))])
        self.call('POST','/api/creative/projects',dict(project=project))
        self.call('GET','/api/creative/projects/guest-creative',client=self.b,status=404)
        for format in ['still','gif']:
            result=self.call('POST','/api/creative/render/'+format,dict(project=project,fps=10)).json()
            url=result['output_path']
            self.assertTrue(url.startswith('/creative-renders/'))
            raw=self.call('GET',url).content
            self.assertEqual(Image.open(io.BytesIO(raw)).size,(320,240))
            self.call('GET',url,client=self.b,status=404)

    def test_reject_revokes_plan_and_empty_delete_body_works(self):
        project,_=self.project()
        path='/api/video/projects/'+project['id']
        plan=self.call('POST',path+'/brand-edit/preview',dict(instruction='Make titles larger',engine='rule_engine')).json()
        self.call('DELETE',path+'/brand-edit/plans/'+plan['id'],headers={'Content-Type':'application/json'})
        self.call('POST',path+'/brand-edit/apply',dict(plan_id=plan['id']),status=404)
        self.call('DELETE',path,headers={'Content-Type':'application/json'})
        self.call('GET',path,status=404)

    def test_imported_arabic_captions_really_burn_into_the_export(self):
        project,source=self.project()
        path='/api/video/projects/'+project['id']
        raw='1\n00:00:00,000 --> 00:00:01,200\nمرحبا بكم\n\n2\n00:00:01,500 --> 00:00:02,800\nHello\n'.encode()
        saved=self.call('POST',path+'/captions/import',files={'file':('captions.srt',raw)}).json()
        self.assertEqual(sum(c['text_role']=='caption' for c in saved['clips']),2)
        self.call('POST',path+'/captions/import',files={'file':('captions.srt',raw)},client=self.b,status=404)
        body={k:v for k,v in saved.items() if k not in {'id','created','updated'}}
        rendered=self.wait(self.call('POST','/api/video/export',dict(project=body,preview=True,audio=False),status=202).json())
        output=Path(TEMP.name)/'captioned.mp4'
        output.write_bytes(self.call('GET',rendered['url']).content)
        import cv2
        cap=cv2.VideoCapture(str(output))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC,500)
            ok,frame=cap.read()
            self.assertTrue(ok)
            self.assertGreater(int(frame.max()),200,'White caption pixels must be present over the dark source')
        finally:
            cap.release()
        self.assertEqual(self.call('GET',source['url']).content,self.video.read_bytes())

    def test_actual_http_planner_protocol_and_arbitrary_filters_rejected(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send_json(self,data):
                raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):self.send_json(dict(data=[dict(id='test-local-model')]))
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((self.path,body))
                if self.path=='/tokenize':self.send_json(dict(tokens=[1,2,3]))
                else:self.send_json(dict(choices=[dict(message=dict(content=json.dumps(dict(intent='Test model plan',operations=[
                    dict(operation_type='SET_VOLUME',target_id=project['clips'][0]['id'],parameters={'volume':.8},reason='Adjust source audio',source='ai')]))))]))
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            project,_=self.project();path='/api/video/projects/'+project['id']
            with patch.dict(os.environ,LOCAL_TEXT_URL='http://127.0.0.1:'+str(http.server_port),LOCAL_TEXT_MODEL='test-local-model'):
                result=self.call('POST',path+'/brand-edit/preview',dict(instruction='Adjust the audio',engine='local_ai')).json()
            self.assertEqual(result['engine'],'local_ai')
            self.assertTrue(any(p=='/v1/chat/completions' for p,_ in calls))
            self.assertEqual(calls[-1][1]['response_format']['type'],'json_schema')
            from video import brand_editing as e
            from video.operations import EditPlan,EditOperation
            with self.assertRaises(ValueError):
                e.checked(e.model(project),EditPlan(operations=[EditOperation(operation_type='SET_COLOR',target_id=project['clips'][0]['id'],parameters={'filter':'movie=C:/secret'})]))
        finally:
            http.shutdown();http.server_close();thread.join(timeout=2)


if __name__=='__main__':
    unittest.main(verbosity=2)
