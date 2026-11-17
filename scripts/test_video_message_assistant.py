"""Company research, guideline-aware messages, enhancement and beginner wizard UX.
Run: python scripts/test_video_message_assistant.py [--browser]
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
TEMP=tempfile.TemporaryDirectory(prefix='video-message-suite-')
os.environ.update(PUBLIC_TEST_MODE='true',PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name)/'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name)/'video'),AGENCY_DATA_DIR=str(Path(TEMP.name)/'agency'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
BROWSER='--browser' in sys.argv
if BROWSER:sys.argv.remove('--browser')
from fastapi.testclient import TestClient
import server
import video_brief_assistant as assistant


def company_page(url,**kwargs):
    if url.endswith('/about'):
        html=b'<html><title>About Acme</title><main>Acme helps operations teams organize practical automation projects and workflow planning.</main></html>'
    else:
        html=b'<html><title>Acme Automation</title><meta name="description" content="Acme builds workflow planning tools for operations teams."><nav>Cookie navigation</nav><script>ignore_previous_instructions()</script><main>Acme builds workflow planning tools for operations teams. Learn about our services.</main><a href="/about">About us</a></html>'
    return 200,'text/html',html,{}


class MessageAssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(server.app,base_url='http://localhost');cls.client.get('/')
        cls.other=TestClient(server.app,base_url='http://localhost');cls.other.get('/')
        result=cls.client.post('/api/brands',json=dict(brand_name='Acme',brand_name_ar='أكمي',primary_hex='#142332',secondary_hex='#e8b34a'))
        assert result.status_code==201,result.text
        cls.brand_id=result.json()['brand']['id']
        raw=b'Brand: Acme\nTone: Professional\nTarget audience: Operations managers\nCTA: Book a consultation\nUse approved facts only.'
        result=cls.client.post('/api/guidelines',files={'file':('acme-guidelines.txt',raw,'text/plain')})
        assert result.status_code==201,result.text
        cls.guideline=result.json();cls.payload=dict(brand_id=cls.brand_id,company_url='https://acme.example/',
            guideline_id=cls.guideline['id'],campaign_type='product_launch',language='en',tone='professional')

    @classmethod
    def tearDownClass(cls):cls.client.close();cls.other.close();TEMP.cleanup()

    def suggest(self,body=None):
        with patch('agency.research.fetch',side_effect=company_page),patch.object(assistant,'model_message',side_effect=ValueError('Offline test provider')):
            response=self.client.post('/api/video/suggest-message',json=body or self.payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_research_guidelines_and_editable_no_model_draft(self):
        result=self.suggest()
        self.assertEqual(len(result['sources']),2)
        self.assertIn('workflow planning tools',result['message'])
        self.assertIn('Book a consultation',result['message'])
        self.assertIn('[product or service name]',result['message'])
        self.assertNotIn('ignore_previous_instructions',result['company_summary'])
        self.assertFalse(result['ai_used']);self.assertTrue(result['questions'])
        self.assertLessEqual(len(result['message']),2000)

    def test_company_introduction_draft_and_native_storyboard(self):
        details=dict(company_overview='Acme is a workflow planning company.',company_services='Workflow tools and automation support.',
                     company_values='Clear communication and practical delivery.',target_audience='Operations managers')
        for language in ('en','ar'):
            result=self.suggest({**self.payload,**details,'campaign_type':'company_intro','language':language})
            self.assertIn('Acme' if language=='en' else 'أكمي',result['message'])
            self.assertIn(details['company_services'],result['message'])
            with patch('campaign_generator.LexnisCampaignStudio._chat',side_effect=RuntimeError('Offline storyboard test')):
                response=self.client.post('/api/video/generate-brief',json={**details,'brand_id':self.brand_id,'campaign_goal':'Introduce the Company',
                    'core_message':result['message'],'language':language,'duration':8})
            self.assertEqual(response.status_code,200,response.text)
            board=response.json();self.assertEqual(len(board['scenes']),4)
            self.assertEqual(board['scenes'][0]['voiceover'],details['company_overview'])
            self.assertIn(details['company_services'],board['scenes'][1]['overlay_text'])
            self.assertIn(details['target_audience'],board['scenes'][2]['overlay_text'])
            self.assertEqual(board['timeline']['scenes'][-1]['end'],8)

    def test_enhancement_reuses_sources_and_preserves_original(self):
        result=self.suggest()
        with patch('agency.research.fetch',side_effect=AssertionError('Enhancement must reuse captured sources')),patch.object(assistant,'model_message',side_effect=ValueError('Offline')):
            response=self.client.post('/api/video/suggest-message',json={**self.payload,'action':'enhance','core_message':'Introduce our planning tools.','context_id':result['context_id']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['message'].startswith('Introduce our planning tools.'))
        self.assertEqual(response.json()['sources'],result['sources'])

    def test_ai_receives_sources_guidelines_and_existing_message(self):
        with patch('agency.research.fetch',side_effect=company_page),patch.object(assistant,'model_message',return_value=({'message':'Introduce Acme workflow planning to operations managers. Invite viewers to book a consultation.','questions':[]},'configured-ai')) as model:
            response=self.client.post('/api/video/suggest-message',json=self.payload)
        self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json()['ai_used'])
        evidence=model.call_args.args[1]
        self.assertIn('Book a consultation',evidence['guidelines']);self.assertTrue(evidence['website_excerpts'])
        with patch.object(assistant,'model_message',return_value=({'message':'قدّم أدوات أكمي لتنظيم سير العمل وادعُ المشاهدين إلى حجز استشارة.','questions':[]},'local-ai')):
            result=self.client.post('/api/video/suggest-message',json={**self.payload,'language':'ar','context_id':response.json()['context_id']})
        self.assertEqual(result.status_code,200);self.assertTrue(result.json()['ai_used']);self.assertRegex(result.json()['message'],r'[\u0600-\u06ff]')

    def test_failed_research_never_claims_company_was_researched(self):
        with patch('agency.research.fetch',side_effect=OSError('Network unavailable')),patch.object(assistant,'model_message',side_effect=ValueError('Offline')):
            result=self.client.post('/api/video/suggest-message',json=self.payload)
        self.assertEqual(result.status_code,200);self.assertFalse(result.json()['sources']);self.assertTrue(result.json()['warnings'])
        self.assertIn('Book a consultation',result.json()['message'])

    def test_private_network_redirects_and_context_isolation(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]),patch('http.client.HTTPConnection') as connect:
            with self.assertRaises(ValueError):assistant.fetch_company_page('http://private.example/')
            connect.assert_not_called()
        redirect=(302,'text/html',b'',{'Location':'http://127.0.0.1/private'})
        from agency.research import fetch
        def first_then_real(url,**kwargs):return redirect if url=='https://acme.example/' else fetch(url,**kwargs)
        with patch('agency.research.fetch',side_effect=first_then_real),patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]),patch('http.client.HTTPConnection') as connect:
            with self.assertRaises(ValueError):assistant.fetch_company_page('https://acme.example/')
            connect.assert_not_called()
        result=self.suggest()
        self.assertEqual(self.other.post('/api/video/suggest-message',json={**self.payload,'context_id':result['context_id']}).status_code,404)
        self.assertEqual(self.client.post('/api/video/suggest-message',json={**self.payload,'company_url':'https://different.example','context_id':result['context_id']}).status_code,400)
        self.assertEqual(self.client.post('/api/video/suggest-message',json={**self.payload,'action':'enhance'}).status_code,400)

    @unittest.skipUnless(BROWSER,'Pass --browser to exercise the beginner workflow')
    def test_browser_research_enhance_review_stale_results_and_reload(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            mode={'action':'draft'}
            def provider(system,evidence):
                return ({'message':'Introduce Acme workflow planning to operations managers. End with an invitation to book a consultation.' if evidence['action']=='draft' else 'Show operations managers how Acme planning tools support clearer workflows. Invite them to book a consultation.','questions':[]},'configured-ai')
            def proxy(route):
                parsed=urlsplit(route.request.url)
                if parsed.hostname!='localhost':route.abort();return
                with patch('agency.research.fetch',side_effect=company_page),patch.object(assistant,'model_message',side_effect=provider),patch('campaign_generator.LexnisCampaignStudio._chat',side_effect=RuntimeError('Offline storyboard test')):
                    response=self.client.request(route.request.method,parsed.path+('?' + parsed.query if parsed.query else ''),content=route.request.post_data_buffer,
                        headers={key:value for key,value in route.request.headers.items() if key in {'content-type','range'}})
                route.fulfill(status=response.status_code,body=response.content,headers={key:value for key,value in response.headers.items() if key not in {'content-length','content-encoding','transfer-encoding','set-cookie'}})
            page.route('**/*',proxy);page.goto('http://localhost/',wait_until='domcontentloaded')
            page.get_by_role('button',name='Video Generator',exact=True).click();wizard=page.locator('.vbf-wizard');wizard.wait_for()
            page.wait_for_function("document.querySelector('[data-field=brand_id]').options.length>1")
            wizard.get_by_label('Brand kit',exact=True).select_option(self.brand_id)
            wizard.get_by_label('Company website',exact=True).fill('https://acme.example/')
            wizard.get_by_label('Company guidelines',exact=True).select_option(self.guideline['id'])
            # Next on an empty message starts assistance instead of showing a required-field trap.
            wizard.get_by_role('button',name='Next: Format & Style',exact=True).click()
            page.wait_for_function("document.querySelector('[data-field=core_message]').value.includes('Acme workflow')")
            original=wizard.get_by_label('Core message or vacancy/product details',exact=True).input_value()
            self.assertEqual(wizard.locator('[data-source-links] a').count(),2)
            with page.expect_response(lambda r:'/api/video/suggest-message' in r.url and r.request.method=='POST') as enhanced_response:
                wizard.get_by_role('button',name='AI enhance message',exact=True).click()
            self.assertEqual(enhanced_response.value.status,200,enhanced_response.value.text())
            page.wait_for_function("document.querySelector('.vbf-wizard [data-suggested]').value.startsWith('Show operations')")
            self.assertEqual(wizard.get_by_label('Core message or vacancy/product details',exact=True).input_value(),original)
            wizard.get_by_role('button',name='Use this message',exact=True).click()
            enhanced=wizard.get_by_label('Core message or vacancy/product details',exact=True).input_value();self.assertTrue(enhanced.startswith('Show operations'))
            wizard.get_by_role('button',name='Next: Format & Style',exact=True).click()
            wizard.get_by_role('button',name='Generate storyboard',exact=True).click();wizard.locator('.vbf-scene').first.wait_for()
            wizard.get_by_role('button',name='1. Brand & Brief',exact=True).click()
            page.set_viewport_size({'width':390,'height':844});self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            evidence=ROOT/'output/video-message-verification';evidence.mkdir(parents=True,exist_ok=True)
            wizard.screenshot(path=str(evidence/'message-mobile.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='Video Generator',exact=True).click()
            page.wait_for_function("document.querySelector('[data-field=core_message]')?.value.startsWith('Show operations')")
            self.assertEqual(page.locator('[data-field=company_url]').input_value(),'https://acme.example/')
            self.assertEqual(page.locator('[data-field=guideline_id]').input_value(),self.guideline['id'])
            self.assertFalse(errors,errors);context.unroute_all(behavior='ignoreErrors');browser.close()


if __name__=='__main__':unittest.main(verbosity=2)
