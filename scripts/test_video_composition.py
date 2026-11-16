"""Composition/timing regressions: exact source words, real raster geometry, real HTTP planning."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-composition-')
os.environ['VIDEO_DATA_DIR']=TEMP.name
import numpy as np
from PIL import Image
from video_caption_timing import optimize
from video_captions import CaptionStyle,render_caption_image,cue_style
from video_projects import Project,Canvas,Clip
from video_layout import solve,analyze_frame,intersection,readable_plate
from video_assets import ingest
from video_platforms import profile,outside_share
from brand_guidelines import Rules
from video_director import LocalSemanticProvider,SemanticPlan,plan_story


def word(start,end,text,p=.95):return dict(start=start,end=end,word=text,probability=p)


class TimingTests(unittest.TestCase):
    def test_fast_caption_is_retimed_without_changing_words(self):
        words=[word(.2,.35,'We'),word(.36,.5,'had'),word(.51,.65,'a'),word(.66,.85,'meeting'),word(.86,1.,'with'),word(1.,1.2,'Mr.'),word(1.21,1.45,'Khawar'),word(1.46,1.65,'and'),word(1.66,1.9,'Ahmad.')]
        cues,report=optimize(words,3.4)
        self.assertEqual(' '.join(c['text'] for c in cues),' '.join(w['word'] for w in words))
        self.assertTrue(report['changes'])
        self.assertLessEqual(max(c['cps'] for c in cues),20.1)
        self.assertTrue(all(a['end']<=b['start'] for a,b in zip(cues,cues[1:])))
        self.assertEqual(sum(len(c['words']) for c in cues),len(words))

    def test_impossible_density_is_reviewed_not_truncated(self):
        words=[word(i*.07,(i+1)*.07,'uncertainword') for i in range(15)]
        cues,report=optimize(words,1.2)
        self.assertEqual(sum(len(c['words']) for c in cues),15)
        self.assertTrue(report['unresolved'])
        self.assertTrue(all(c['end']<=1.2 for c in cues))

    def test_arabic_keeps_logical_words_and_burns_pixels(self):
        text='مرحبا بكم في مكتبنا اليوم نشارككم تفاصيل العمل'
        style=CaptionStyle(id='ar',name='Arabic',font_family='arabic',font_size_px=28,reference_width=464,max_width_pct=.7)
        im=render_caption_image(text,464,832,style)
        self.assertEqual(' '.join(im.info['caption_layout']['logical_lines']),text)
        self.assertGreater((np.array(im)[:,:,3]>200).sum(),1000)
        self.assertFalse(im.info['caption_layout']['truncated'])


class LayoutTests(unittest.TestCase):
    def test_dark_brand_ink_gets_a_readable_plate(self):
        from creative.colors import parse_color
        from video_measure import contrast_ratio
        style=CaptionStyle(id='cta',name='CTA',fill='#131724',background='#131724ee',font_size_px=26)
        fixed=readable_plate(style,['#131724','#53B849'])
        self.assertEqual(fixed.fill,'#131724')
        self.assertGreaterEqual(contrast_ratio(parse_color(fixed.fill)[:3],parse_color(fixed.background)[:3]),7.)
        self.assertEqual(fixed.background[:7].lower(),'#53b849')
    def scene(self,w=464,h=832):
        face=dict(x=.43,y=.36,width=.2,height=.13)
        frame=np.full((h,w,3),190,'uint8')
        return face,analyze_frame(frame,face,extra_regions=[dict(kind='hand',box=[.05,.68,.28,.85],basis='TEST_MEASURED_REGION')])

    def project(self):
        file=Path(TEMP.name)/'logo.png';Image.new('RGBA',(240,80),'#227755').save(file)
        logo=ingest(file,'logo.png')
        project=Project(canvas=Canvas(width=464,height=832),clips=[Clip(asset_id='a'*32,duration=15),
            Clip(asset_id=logo['id'],kind='overlay',duration=15,logo_backplate=True),
            Clip(kind='title',text='Follow our team',text_role='cta',start=12,duration=3,color='#ffffff')],
            caption_tracks=[dict(id='dialogue',kind='captions',style_id='quick-social',segments=[dict(start=0,end=3,text='Welcome to our office.'),dict(start=12,end=15,text='A useful meeting with the team.')]),
                            dict(id='speaker',kind='lower-third',style_id='lower-third',segments=[dict(start=.3,end=3.3,text='Speaker · Office update')])])
        return project

    def test_joint_layout_reserves_cta_and_protects_face_hands(self):
        p=self.project();face,scene=self.scene();platform=profile('tiktok-ltr')
        plan=solve(p,platform,face,scene,Rules(primary_colors=['#152335'],font_preferences=['Arial']))
        elements=plan['elements']
        face_box=[face['x']*464,face['y']*832,(face['x']+face['width'])*464,(face['y']+face['height'])*832]
        for i,a in enumerate(elements):
            self.assertLessEqual(outside_share(a['box'],platform,464,832),.001)
            self.assertEqual(intersection(a['box'],face_box),0)
            self.assertLessEqual(a['evidence']['hand_overlap'],.001)
            for b in elements[i+1:]:
                if min(a['end'],b['end'])>max(a['start'],b['start'])+.01:self.assertEqual(intersection(a['box'],b['box']),0,(a,b))
        cta=next(e for e in elements if e['role']=='CTA')
        self.assertGreaterEqual(cta['font_size_px'],24)
        self.assertGreater(cta['font_size_px'],next(e for e in elements if e['role']=='DIALOGUE_CAPTION')['font_size_px'])
        track=p.caption_tracks[0];s=track['segments'][-1]
        image=render_caption_image(s['text'],464,832,cue_style(track,s))
        self.assertEqual(image.info['caption_layout']['box'],s['layout_box'])
        alpha=np.array(image)[:,:,3];ys,xs=np.nonzero(alpha)
        box=s['layout_box']
        self.assertGreaterEqual(xs.min(),box[0]);self.assertLessEqual(xs.max(),box[2]);self.assertGreaterEqual(ys.min(),box[1]);self.assertLessEqual(ys.max(),box[3])


class SemanticHTTPTests(unittest.TestCase):
    def test_real_http_schema_rejects_invented_words_and_sentence_ids(self):
        requests=[];outputs=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,body))
                value={'tokens':[1]*100} if self.path=='/tokenize' else {'choices':[{'message':{'content':json.dumps(outputs.pop(0))}}]}
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        evidence=dict(sentences=[dict(id='sentence-1',start=0,end=1,text='Keep this exact sentence.',asr_confidence=.9)])
        valid=dict(sentences=[dict(sentence_id='sentence-1',role='important',importance=.9,confidence=.95,action='keep',reason='Retain the source meaning')],summary='Keep the statement')
        try:
            with patch.dict(os.environ,LOCAL_TEXT_URL=f'http://127.0.0.1:{server.server_port}',LOCAL_TEXT_MODEL='test'):
                outputs.append(valid)
                result=LocalSemanticProvider().plan(evidence)
                self.assertEqual(result.sentences[0].sentence_id,'sentence-1')
                outputs.append(dict(valid,sentences=[dict(valid['sentences'][0],text='Invented replacement words')]))
                with self.assertRaises(ValueError):LocalSemanticProvider().plan(evidence)
                outputs.append(dict(valid,sentences=[dict(valid['sentences'][0],sentence_id='invented-id')]))
                with self.assertRaises(ValueError):LocalSemanticProvider().plan(evidence)
        finally:server.shutdown();server.server_close();thread.join()
        sent=next(body for path,body in requests if path=='/v1/chat/completions')
        self.assertEqual(sent['response_format']['json_schema']['schema']['additionalProperties'],False)
        self.assertIn('UNTRUSTED DATA',sent['messages'][0]['content'])

    def test_asr_uncertainty_cannot_be_promoted_by_a_confident_llm(self):
        result=SemanticPlan(sentences=[dict(sentence_id='sentence-1',role='recording-instruction',importance=0.,confidence=.99,action='propose-drop',reason='Recording instruction')])
        with patch('video_brand_editing.ai_status',return_value={'available':True}),patch.object(LocalSemanticProvider,'plan',return_value=result):
            plan=plan_story([word(0,.4,'Okay',.5),word(.4,.8,'stop.',.5)],1,{}, {}, {},'aggressive')
        self.assertTrue(plan['candidates'][0]['requires_approval'])
        self.assertLessEqual(plan['candidates'][0]['confidence'],.5)

    def test_important_source_fact_still_requires_approval(self):
        result=SemanticPlan(sentences=[dict(sentence_id='sentence-1',role='important',importance=.95,confidence=.99,action='propose-drop',reason='Contradictory model suggestion')])
        with patch('video_brand_editing.ai_status',return_value={'available':True}),patch.object(LocalSemanticProvider,'plan',return_value=result):
            plan=plan_story([word(0,.4,'Retain',.99),word(.4,.8,'facts.',.99)],1,{}, {}, {},'aggressive')
        self.assertTrue(plan['candidates'][0]['requires_approval'])


class FinishingTests(unittest.TestCase):
    def test_authored_line_break_is_kept_for_name_and_role(self):
        style=CaptionStyle(id='lt',name='Lower third',max_lines=2)
        info=render_caption_image('Salman Almahari\nCyber Security Engineer',464,824,style).info['caption_layout']
        self.assertEqual(info['logical_lines'],['Salman Almahari','Cyber Security Engineer'])
        flowed=render_caption_image('Salman Almahari · Cyber Security Engineer',464,824,style).info['caption_layout']
        self.assertTrue(any('·' in line for line in flowed['logical_lines']))   # the old dangling separator

    def test_subject_lift_follows_the_backlight_not_only_the_range_floor(self):
        from video_grade import plan_regional,LOOKS
        backlit=dict(before=dict(face_luma=.431,background_luma=.653,backlight_difference=.222))
        even=dict(before=dict(face_luma=.431,background_luma=.47,backlight_difference=.04))
        strong,weak=plan_regional(backlit,'a'*32).subject,plan_regional(even,'a'*32).subject
        self.assertGreater(strong.gamma,1.2)
        self.assertLess(weak.gamma,1.1)
        self.assertLessEqual(strong.gamma,1.34)
        # Predicted face stays inside the look's range; chroma is restored with the lift.
        self.assertLess(.431**(1/strong.gamma),LOOKS['polished-organic']['face_range'][1])
        self.assertGreater(strong.saturation,1.1)
        bright=plan_regional(dict(before=dict(face_luma=.6,background_luma=.9,backlight_difference=.3)),'a'*32).subject
        self.assertEqual(bright.gamma,1.)        # already at the top of the range: never pushed further

    def test_slight_lift_is_not_reported_as_done(self):
        import video_quick_edit
        source=Path(video_quick_edit.__file__).read_text(encoding='utf-8')
        self.assertIn("'FULFILLED' if correction.get('subject_lift_effective', True) else 'PARTIALLY_FULFILLED'",source)


if __name__=='__main__':unittest.main(verbosity=2)
