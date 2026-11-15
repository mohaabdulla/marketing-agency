"""Reusable cut/caption behavior, real export and public ownership regression checks.

Speech fixtures isolate algorithm tests; the live-video review separately runs the actual model.
"""
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-quick-tests-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
from fastapi.testclient import TestClient
from PIL import Image
import server
from video_quick_edit import keep_ranges,caption_cues,QuickEdit,build
from video_projects import Project,Clip,Canvas
from video_ffmpeg import ffmpeg


def word(start,end,text):return dict(start=start,end=end,word=text,probability=.95)


class QuickTests(unittest.TestCase):
    def setUp(self):
        self.a=TestClient(server.app,base_url='https://testserver');self.b=TestClient(server.app,base_url='https://testserver');self.a.get('/');self.b.get('/')

    def test_general_tail_rules_and_caption_remapping(self):
        words=[word(.4,.8,'Hello'),word(2,2.5,'world.'),word(7,7.3,'Okay,'),word(7.3,7.6,"that's"),word(7.6,7.8,'it.')]
        ranges,cuts=keep_ranges(8,words)
        self.assertTrue(any(c['reason']=='Trailing recording instruction' for c in cuts))
        cues=caption_cues(words,ranges);self.assertEqual(' '.join(c['text'] for c in cues),'Hello world.')
        self.assertLessEqual(max(c['end'] for c in cues),sum(b-a for a,b in ranges)+.01)
        early=[word(.3,.5,'stop'),word(.5,.8,'recording'),word(7,7.5,'continues')]
        _,cuts=keep_ranges(8,early,tighten=False)
        self.assertFalse(any(c['reason']=='Trailing recording instruction' for c in cuts))
        self.assertEqual(keep_ranges(4,[])[0],[(0,4)])

    def test_ui_asset_revision_reaches_imported_modules(self):
        index=self.a.get('/');self.assertIn('no-store',index.headers['cache-control'])
        version=self.a.get('/api/ui-version').json()['version'];self.assertIn('workspace-navigation.js?v='+version,index.text)
        script=self.a.get('/static/js/video-brand-editor.js?v='+version)
        self.assertIn('no-store',script.headers['cache-control']);self.assertIn('./video-quick-editor.js?v='+version,script.text)

    def test_guest_quick_edit_real_export_and_original_project_preserved(self):
        source=Path(TEMP.name)/'source.mp4';ffmpeg(['-f','lavfi','-i','color=c=0x223344:s=320x240:d=3:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
        asset=self.a.post('/api/video/upload',files={'file':('source.mp4',source.read_bytes())}).json()
        buf=io.BytesIO();Image.new('RGBA',(80,40),'red').save(buf,'PNG');logo=self.a.post('/api/video/upload',files={'file':('logo.png',buf.getvalue())}).json()
        project=self.a.post('/api/video/projects',json=dict(name='Original timeline',canvas=dict(width=320,height=240,fps=24),editing_brief=dict(logo_asset_id=logo['id']),clips=[dict(asset_id=asset['id'],duration=3)])).json()
        body=dict(asset_id=asset['id'],instruction='Add captions and gentle zooms',language='en')
        self.assertEqual(self.b.post('/api/video/projects/'+project['id']+'/quick-edit',json=body).status_code,404)
        self.assertEqual(self.a.post('/api/video/projects/'+project['id']+'/quick-edit',json=dict(body,asset_id=logo['id'])).status_code,400)
        transcript=dict(language='en',segments=[dict(words=[word(.1,.6,'A'),word(.6,1.1,'test.'),word(2.1,2.3,'Okay'),word(2.3,2.5,'stop')])])
        with patch('video_quick_edit.speech_status',return_value={'available':True}),patch('video_quick_edit.transcribe',return_value=transcript):
            response=self.a.post('/api/video/projects/'+project['id']+'/quick-edit',json=body);self.assertEqual(response.status_code,202,response.text);job=response.json()
            for _ in range(600):
                state=self.a.get('/api/video/jobs/'+job['id']).json()
                if state['state'] in {'completed','failed','cancelled'}:break
                time.sleep(.1)
        self.assertEqual(state['state'],'completed',state);result=state['result']
        self.assertNotEqual(result['project_id'],project['id']);self.assertLess(result['duration'],3)
        self.assertEqual([result['width'],result['height']],[320,240]);self.assertGreater(result['edit_report']['caption_count'],0)
        self.assertNotIn('No transcript was supplied.',' '.join(result['edit_report']['warnings']))
        original=self.a.get('/api/video/projects/'+project['id']).json();self.assertEqual(original['clips'],project['clips'])
        self.assertEqual(self.a.get('/api/video/media/'+asset['id']).content,source.read_bytes())
        self.assertEqual(self.b.get('/api/video/download/'+result['id']).status_code,404)
        self.assertGreater(len(self.a.get('/api/video/download/'+result['id']).content),1000)
        review='/api/video/assets/'+result['id']+'/review'
        self.assertEqual(self.a.get(review).json()['state'],'DRAFT')
        self.assertEqual(self.b.get(review).status_code,404)
        self.assertEqual(self.b.post(review,json={'state':'INTERNAL_REVIEW'}).status_code,404)
        self.assertEqual(self.a.post(review,json={'state':'INTERNAL_REVIEW'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.a.post(review,json={'state':'INTERNAL_REVIEW'}).json()['state'],'INTERNAL_REVIEW')
        revision='/api/video/projects/'+result['project_id']+'/revisions/'+result['render_revision_id']
        self.assertEqual(self.b.get(revision).status_code,404)
        self.assertEqual(self.a.get(revision).json()['render_asset_id'],result['id'])


if __name__=='__main__':unittest.main(verbosity=2)
