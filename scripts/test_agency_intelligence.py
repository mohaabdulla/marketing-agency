"""Scoped campaign assistance, real local copy tools, readiness, and browser application.
Run: python scripts/test_agency_intelligence.py [--browser]
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(prefix='agency-intelligence-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
    VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
BROWSER='--browser' in sys.argv
if BROWSER:sys.argv.remove('--browser')
from fastapi.testclient import TestClient
import server
from agency.campaign_quality import text_length,fit_x_text,contrast,review_copy,similarity,x_thread
from agency.creative_eval import evaluator
from image.campaign_generator import generate_enterprise_copy
from image.visual_engine import resolve_brand_theme


class AgencyIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(server.app,base_url='http://localhost');cls.client.get('/')
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        response=cls.client.post('/api/brands',json=dict(brand_name='Acme',primary_hex='#142332',secondary_hex='#e8b34a'))
        assert response.status_code==201,response.text
        cls.brand=response.json()['brand']['id']

    @classmethod
    def tearDownClass(cls):cls.client.close();cls.other.close();TEMP.cleanup()

    def scope(self):
        client=self.client.post('/api/agency/clients',json={'name':'Acme Automation'}).json()['id']
        campaign=self.save(client,'campaigns',{'objective':'Launch warehouse planning tools','primary_kpi':'Qualified demo requests'},name='Workflow launch')
        return client,campaign

    def save(self,client,kind,data,campaign=None,name='Fixture record'):
        response=self.client.post(f'/api/agency/clients/{client}/records/{kind}',json=dict(name=name,campaign_id=campaign,data=data))
        self.assertEqual(response.status_code,201,response.text);return response.json()

    def command(self,client,campaign):
        response=self.client.get(f'/api/agency/clients/{client}/campaigns/{campaign}/command-center')
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def test_scoped_command_center_counts_beyond_first_page_and_excludes_other_campaign(self):
        client,campaign=self.scope();key=campaign['id']
        other=self.save(client,'campaigns',{'objective':'Unrelated launch'})
        self.save(client,'briefs',{'primary_message':'UNRELATED SECRET MESSAGE'},other['id'])
        for i in range(29):self.save(client,'copy',{'text':f'Practical workflow note {i}','format':'linkedin_post'},key)
        center=self.command(client,key)
        self.assertEqual(center['production_board']['copy_variants_count'],29)
        self.assertNotIn('UNRELATED SECRET',json.dumps(center))
        self.assertEqual(center['strategy_summary']['proposition'],'')
        self.assertEqual(center['strategy_summary']['proof'],[])
        self.assertNotIn('100% Local Inference',json.dumps(center))
        self.assertEqual(center['readiness']['status'],'BLOCKED')
        self.assertEqual(center['campaign']['currency'],'BHD')

    def test_requested_and_stale_approvals_are_not_counted_as_approved(self):
        client,campaign=self.scope();key=campaign['id']
        brief=self.save(client,'briefs',{'primary_message':'Warehouse planning tools'},key)
        approval=self.client.post(f'/api/agency/clients/{client}/approvals',json=dict(target_id=brief['id'],reviewer='Client reviewer')).json()
        def stage():return next(s for s in self.command(client,key)['stages'] if s['stage']=='BRIEF')
        self.assertNotEqual(stage()['status'],'APPROVED')
        response=self.client.post(f'/api/agency/clients/{client}/approvals/{approval["id"]}/decision',json=dict(expected_version=approval['version'],decision='approved',reviewer='Client reviewer'))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(stage()['status'],'APPROVED')
        response=self.client.put(f'/api/agency/clients/{client}/records/briefs/{brief["id"]}',json=dict(expected_version=brief['version'],name=brief['name'],campaign_id=key,data={**brief['data'],'primary_message':'Changed after approval'}))
        self.assertEqual(response.status_code,200,response.text);self.assertNotEqual(stage()['status'],'APPROVED')

    def test_explicitly_linked_shared_strategy_is_used(self):
        client,campaign=self.scope()
        strategy=self.save(client,'strategies',{'strategic_idea':'Demonstrate the real planning workflow','current_state':'Manual scheduling','channels':['LinkedIn']})
        response=self.client.put(f'/api/agency/clients/{client}/records/campaigns/{campaign["id"]}',json=dict(expected_version=campaign['version'],name=campaign['name'],data={**campaign['data'],'strategy_id':strategy['id']}))
        self.assertEqual(response.status_code,200,response.text)
        summary=self.command(client,campaign['id'])['strategy_summary']
        self.assertEqual(summary['proposition'],'Demonstrate the real planning workflow')
        self.assertEqual(summary['problem'],'Manual scheduling')

    def test_assistance_uses_saved_context_without_saving_or_fabricating_targets(self):
        client,campaign=self.scope();key=campaign['id']
        self.save(client,'briefs',{'primary_message':'Practical warehouse planning','audience':'Operations managers','cta':'Book a demo'},key)
        with patch('video.brief_assistant.model_message',side_effect=ValueError('No configured inference')):
            response=self.client.post(f'/api/agency/clients/{client}/campaigns/{key}/assist',json={})
        self.assertEqual(response.status_code,200,response.text);draft=response.json()
        self.assertIn('Operations managers',draft['brief']);self.assertIn('Book a demo',draft['brief'])
        self.assertFalse(draft['ai_used']);self.assertIsNone(draft['measurement_plan']['target'])
        self.assertEqual(draft['measurement_plan']['primary_kpi'],'Qualified demo requests')
        self.assertEqual(len(draft['creative_directions']),3)
        self.assertEqual(self.client.get(f'/api/agency/clients/{client}/records?kind=briefs').json()['total'],1)
        self.assertEqual(self.other.post(f'/api/agency/clients/{client}/campaigns/{key}/assist',json={}).status_code,404)

    def test_assistance_research_sources_reused_and_unfounded_model_metrics_rejected(self):
        client,campaign=self.scope();url=f'/api/agency/clients/{client}/campaigns/{campaign["id"]}/assist'
        payload=dict(brand_id=self.brand,company_url='https://acme.example/')
        html=b'<html><title>Acme</title><main><p>Acme makes warehouse planning software for logistics operations teams.</p></main></html>'
        with patch('agency.research.fetch',return_value=(200,'text/html',html,{})),patch('video.brief_assistant.model_message',side_effect=ValueError('No inference')):
            response=self.client.post(url,json=payload)
        self.assertEqual(response.status_code,200,response.text);result=response.json()
        self.assertEqual(result['research_report']['pages_read'],1)
        self.assertIn('warehouse planning software',result['brief'])
        hallucination=dict(brief='Guaranteed revenue improvement of 99999 percent.',creative_directions=['Show a real product'],questions=[])
        with patch('agency.research.fetch',side_effect=AssertionError('Must reuse research')),patch('video.brief_assistant.model_message',return_value=(hallucination,'local-ai')):
            response=self.client.post(url,json={**payload,'action':'enhance','current_brief':'Introduce warehouse planning.','research_context_id':result['research_context_id']})
        self.assertEqual(response.status_code,200,response.text);self.assertFalse(response.json()['ai_used'])
        self.assertNotIn('99999',response.json()['brief'])

    def test_actual_weighted_x_count_handles_urls_emoji_arabic_and_grapheme_trimming(self):
        self.assertEqual(text_length('https://example.com/'+'a'*500,'x_post')['length'],23)
        self.assertEqual(text_length('👨‍👩‍👧‍👦'*140,'x_post')['length'],280)
        self.assertFalse(text_length('👨‍👩‍👧‍👦'*141,'x_post')['valid'])
        self.assertEqual(text_length('مرحبا','x_post')['length'],5)
        fitted=fit_x_text('👨‍👩‍👧‍👦'*150)
        self.assertLessEqual(text_length(fitted,'x_post')['length'],280)
        self.assertEqual(fitted.rstrip('…').replace('👨‍👩‍👧‍👦',''),'')
        long_url='https://example.com/'+('a'*500)
        posts=x_thread('Discover '+long_url+' '+'👨‍👩‍👧‍👦'*160)
        self.assertIn(long_url,' '.join(posts))
        self.assertTrue(all(text_length(post,'x_post')['length']<=280 for post in posts))
        self.assertEqual(' '.join(posts).count('👨‍👩‍👧‍👦'),160)

    def test_media_runner_initializes_fresh_workspace_scratch_directory(self):
        from video import ffmpeg
        with tempfile.TemporaryDirectory(prefix='media-scratch-') as folder,patch.object(ffmpeg,'DATA',Path(folder)):
            output=ffmpeg.run(['-version'],executable='ffprobe',timeout=20)
            self.assertIn('ffprobe version',output)
            self.assertTrue((Path(folder)/'work').is_dir())

    def test_real_rapidfuzz_unicode_and_wcag_reference_contrast(self):
        self.assertEqual(similarity('  CAFÉ  tools','cafe\u0301 tools'),1)
        self.assertGreater(similarity('أدوات تخطيط للمستودعات','أدوات تخطيط للمستودعات.'),.9)
        self.assertAlmostEqual(contrast('#ffffff','#000000'),21)
        self.assertEqual(contrast('#142332','#142332'),1)

    def test_command_center_reports_unreviewed_claims_and_missing_media_rights(self):
        from agency.orchestrator import orchestrator
        risks=orchestrator._compute_risks({'data':{}},{'briefs':[{'id':'b'}],
            'claims':[dict(id='c',data=dict(text='A supplied claim',status='draft',evidence_ids=['e']))],
            'evidence':[{'id':'e'}],'assets':[dict(id='a',name='Campaign image',data={'asset_type':'image'})]})
        self.assertTrue({'CLAIM_REVIEW_REQUIRED','MEDIA_RIGHTS_REVIEW'}.issubset({r.code for r in risks}))

    def test_copy_review_checks_placeholders_localization_brand_rules_and_new_metrics(self):
        copy=dict(linkedin_post='Guaranteed 999 sales [PRODUCT]',instagram_caption='English only',x_thread=['👨‍👩‍👧‍👦'*141])
        review=review_copy(copy,'ar','A product launch',dict(prohibited_terms=['Guaranteed'],mandatory_terms=['Acme']))
        self.assertTrue({'placeholder','localization','brand-term','new-number','length','mandatory-term'}.issubset({i['code'] for i in review['issues']}))
        result=evaluator.evaluate_copy('A useful headline','Discover the new warehouse tools.',channel='linkedin')
        self.assertIsNone(result.model_review['distinctiveness']);self.assertIsNone(result.model_review['brief_alignment'])
        numbered=review_copy(dict(linkedin_post='Discover planning tools.',instagram_caption='Explore planning tools.',x_thread=['1/2 Discover the tools.','2/2 Book a demo.']),'en')
        self.assertFalse(any(i['code']=='new-number' for i in numbered['issues']))

    def test_model_copy_over_limit_and_invalid_x_falls_back(self):
        theme=resolve_brand_theme(brand_name='Acme');request=dict(prompt='Warehouse planning software',post_type='product_launch')
        for written in (dict(linkedin='A'*3001,instagram='Useful planning tools.',x_thread=['Discover Acme.']),
                        dict(linkedin='Planning tools for teams.',instagram='Explore Acme.',x_thread=['👨‍👩‍👧‍👦'*141])):
            with patch('video.brief_assistant.model_message',return_value=(written,'local-ai')):
                result=generate_enterprise_copy(request,theme,'en')
            self.assertEqual(result['copy_source'],'template')

    @unittest.skipUnless(BROWSER,'Pass --browser for the Command Center assistance flow')
    def test_browser_suggestion_edit_apply_and_quality_panel(self):
        from playwright.sync_api import sync_playwright
        client,campaign=self.scope();self.save(client,'briefs',{'audience':'Operations managers','primary_message':'Practical warehouse planning','cta':'Book a demo'},campaign['id'])
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            def proxy(route):
                parsed=urlsplit(route.request.url)
                if parsed.hostname!='localhost':route.abort();return
                with patch('video.brief_assistant.model_message',side_effect=ValueError('Offline browser fixture')):
                    response=self.client.request(route.request.method,parsed.path+('?' + parsed.query if parsed.query else ''),content=route.request.post_data_buffer,headers={k:v for k,v in route.request.headers.items() if k in ('content-type','range')})
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding','set-cookie')})
            page.route('**/*',proxy);page.goto('http://localhost/',wait_until='domcontentloaded')
            page.evaluate('''async campaign=>{const ctx=await import('/static/js/app-context.js');await ctx.setCampaign(campaign);const root=document.createElement('div');root.id='coach-fixture';document.body.append(root);const c=await import('/static/js/campaign-command-center.js');await c.mountCommandCenter(root);}''',campaign)
            root=page.locator('#coach-fixture');root.locator('[data-campaign-assistant] summary').click()
            root.get_by_role('button',name='Suggest campaign brief',exact=True).click();root.locator('[data-proposed-brief]').wait_for(state='visible')
            self.assertIn('Operations managers',root.locator('[data-proposed-brief]').input_value())
            root.locator('[data-proposed-brief]').fill('Approved edited warehouse campaign. Invite viewers to book a demo.')
            root.get_by_role('button',name='Use suggested campaign brief',exact=True).click()
            self.assertTrue(root.locator('#ccc-generation-brief').input_value().startswith('Approved edited'))
            self.assertIn('actual product',root.locator('#ccc-generation-direction').input_value())
            page.evaluate('''()=>{const c=document.createElement('div');c.id='quality-fixture';document.body.append(c);window.renderCampaignDeliverables(c,{quality_review:{copy:{en:{channels:[],issues:[{message:'Replace the product placeholder.'}],notice:'Review the copy.'}},palette:[],palette_notice:'Reference only',accessibility:{alt_text_draft:'Acme campaign artwork'},handoff:{next_steps:['Review final copy.']}}},'en',{download:async()=>{}});}''')
            page.locator('#quality-fixture').get_by_role('tab',name='Campaign Review',exact=True).click()
            self.assertIn('Replace the product placeholder.',page.locator('#quality-fixture').inner_text())
            page.locator('#quality-fixture').get_by_role('button',name='Copy alt text',exact=True).click()
            self.assertEqual(page.evaluate('navigator.clipboard.readText()'),'Acme campaign artwork')
            self.assertFalse(errors,errors);context.unroute_all(behavior='ignoreErrors');browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
