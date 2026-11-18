"""Editorial planning, real YAKE/BM25 and scoped review APIs; no paid inference."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='storyboard-coach-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
from fastapi.testclient import TestClient
import server
from video.director import VideoBriefRequest,synthesize_storyboard
from video.storyboard_coach import beats,balance_timing,review_storyboard
from video.stock import keywords,rank_results


class StoryboardCoachTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(server.app,base_url='http://localhost');cls.client.get('/')
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        cls.brand=cls.client.post('/api/brands',json=dict(brand_name='Acme',primary_hex='#142332',secondary_hex='#e8b34a')).json()['brand']
        cls.request=VideoBriefRequest(brand_id=cls.brand['id'],core_message='Warehouse robots move goods for logistics teams.',duration=12)
        with patch('video.brief_assistant.model_message',side_effect=ValueError('No inference for this fixture')):
            response=cls.client.post('/api/video/generate-brief',json=cls.request.model_dump())
        assert response.status_code==200,response.text
        cls.brief=response.json()

    @classmethod
    def tearDownClass(cls):cls.client.close();cls.other.close();TEMP.cleanup()

    def test_distinct_story_beats_and_filmable_directions(self):
        scenes=self.brief['scenes']
        self.assertEqual(beats('explainer',3),['problem','demonstration','next-step'])
        self.assertEqual(len({s['visual_prompt'] for s in scenes}),3)
        self.assertIn('demonstration',scenes[1]['visual_prompt'])
        self.assertIn('end card',scenes[-1]['visual_prompt'])
        self.assertTrue(self.brief['storyboard_review']['scenes'])

    def test_storyboard_uses_shared_local_capable_adapter_and_word_budget(self):
        written={'scenes':[dict(overlay_text='Warehouse robots',voiceover='Robots move warehouse goods.',visual_prompt='A robot carrying a pallet.') for _ in range(3)]}
        with patch('video.brief_assistant.model_message',return_value=(written,'local-ai')) as model:
            scenes,source=synthesize_storyboard(self.request,self.brand)
        self.assertEqual(source,'ai-model')
        # The first call drafts the storyboard; a later call may be the script editor's revision.
        context=model.call_args_list[0].args[1]
        self.assertEqual(context['story_structure'],['hook','product-benefit','invitation'])
        self.assertGreater(context['voiceover_word_budget'],0)
        self.assertEqual(scenes[0].voiceover,'Robots move warehouse goods.')

    def test_balance_preserves_script_assets_and_exact_runtime(self):
        scenes=[{**s,'voiceover':'A short line.' if i!=1 else 'One longer explanation with several useful details about warehouse automation for logistics teams.'} for i,s in enumerate(self.brief['scenes'])]
        result=balance_timing(scenes,12)
        self.assertGreater(result[1]['duration'],result[0]['duration'])
        self.assertAlmostEqual(sum(s['duration'] for s in result),12,places=3)
        for original,new in zip(scenes,result):
            self.assertEqual({k:v for k,v in original.items() if k not in ('start','duration')},{k:v for k,v in new.items() if k not in ('start','duration')})
        self.assertEqual(result[-1]['start']+result[-1]['duration'],12)

    def test_review_flags_real_editorial_risks_without_deleting_text(self):
        scenes=[dict(s) for s in self.brief['scenes']]
        scenes[0].update(voiceover='[INSERT HERE] '+'Long narration '*35,overlay_text='Repeated headline',asset_id='a'*32)
        scenes[1].update(overlay_text='Repeated headline',asset_id='a'*32)
        review=review_storyboard(scenes,self.request.model_dump(),{'a'*32:dict(kind='image',width=320,height=180)})
        codes={item['code'] for item in review['issues']}
        self.assertTrue({'placeholder','narration-pace','repetition','repeated-visual','media-resolution'}.issubset(codes))
        self.assertIn('[INSERT HERE]',scenes[0]['voiceover'])

    def test_real_local_yake_multilingual_queries(self):
        import yake
        with patch.object(yake,'KeywordExtractor',wraps=yake.KeywordExtractor) as extractor:
            query=keywords('Acme professional scene: warehouse robots carrying inventory to picking stations. Brand palette: #123456, #abcdef. typography: Arial.',exclude='Acme')
        extractor.assert_called_once()
        self.assertIn('warehouse',query);self.assertNotIn('abcdef',query);self.assertNotIn('acme',query)
        self.assertRegex(keywords('روبوتات المستودعات تنقل البضائع بين محطات العمل'),r'[\u0600-\u06ff]')

    def test_rank_footage_by_subject_and_format_without_duplicates(self):
        def item(key,description,width=1920,height=1080,duration=8):return dict(provider='pexels',id=key,description=description,page_url='',width=width,height=height,duration=duration)
        irrelevant=item('1','Ocean waves and a beach')
        relevant=item('2','Warehouse robots carry inventory')
        result=rank_results([irrelevant,relevant,relevant,item('3','Warehouse robots',duration=1)],'warehouse robots','landscape',4)
        self.assertEqual([i['id'] for i in result],['2','1'])
        self.assertIn('Search words match provider metadata',result[0]['selection_notes'])

    def test_review_and_balance_apis_are_scoped_and_use_current_edit(self):
        scenes=[{**s,'voiceover':'Check [PRODUCT NAME].' if i==1 else s['voiceover']} for i,s in enumerate(self.brief['scenes'])]
        body=dict(brief_id=self.brief['brief_id'],scenes=scenes)
        response=self.client.post('/api/video/review-storyboard',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(any(i['code']=='placeholder' for i in response.json()['issues']))
        scenes[0]['duration']=5
        result=self.client.post('/api/video/balance-storyboard',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertAlmostEqual(sum(s['duration'] for s in result.json()['scenes']),12)
        self.assertEqual(self.other.post('/api/video/review-storyboard',json=body).status_code,404)
        self.assertEqual(self.other.post('/api/video/balance-storyboard',json=body).status_code,404)


if __name__=='__main__':unittest.main(verbosity=2)
