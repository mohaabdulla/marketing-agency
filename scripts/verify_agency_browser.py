"""Real-server browser scenario for client-scoped agency planning. No AI/provider calls."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-agency-browser-') as tmp:
        tmp=Path(tmp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        env={**os.environ,'AGENCY_DATA_DIR':str(tmp/'agency'),'VIDEO_DATA_DIR':str(tmp/'video'),'PYTHONIOENCODING':'utf-8'}
        evidence=ROOT/'output/agency-browser';evidence.mkdir(parents=True,exist_ok=True)
        with (evidence/'server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],
                cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin+'/api/agency/health',timeout=1).status_code==200:break
                    except requests.RequestException:time.sleep(.25)
                    if server.poll() is not None:raise RuntimeError('Agency server failed; inspect its log')
                def record(client,kind,name,data=None,project=None,campaign=None):
                    response=requests.post(origin+f'/api/agency/clients/{client}/records/{kind}',
                        json=dict(name=name,data=data or {},project_id=project,campaign_id=campaign),timeout=10)
                    assert response.status_code==201,response.text
                    return response.json()
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':1500,'height':1100},accept_downloads=True)
                    errors=[];generations=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('request',lambda req:generations.append(req.url) if req.method=='POST' and req.url.endswith(('/api/generate','/api/campaign/generate')) else None)
                    def external(route):
                        if 'lucide' in route.request.url:route.fulfill(body='window.lucide={createIcons(){}};',content_type='application/javascript')
                        else:route.abort()
                    page.route('https://**/*',external)
                    page.goto(origin,wait_until='domcontentloaded')
                    page.wait_for_selector('.agency-context')
                    assert page.locator('#image-workspace').is_visible()
                    page.locator('#prompt-input').fill('Keep this unsaved image draft')
                    def nav(label):page.get_by_role('button',name=label,exact=True).click()
                    def area(key):return page.locator('#agency-'+key+'-workspace')
                    def new(root,name=None):
                        root.locator('[data-new]').click()
                        root.locator('[data-form]').wait_for()
                        if name:root.locator('[name=record_name]').fill(name)
                    def save(root):
                        root.locator('button[type=submit]').click()
                        page.wait_for_function("(id)=>document.querySelector(id+' .ag-status').textContent.startsWith('Saved ·')",arg='#'+root.get_attribute('id'),timeout=15000)
                    nav('Clients & Brands');root=area('clients')
                    new(root);root.locator('[data-field=name]').fill('Alpha Client')
                    root.locator('[data-field=description]').fill('عميل AI · Bahrain')
                    save(root)
                    client=page.locator('#agency-context-client').input_value();assert len(client)==32
                    root.get_by_role('tab',name='Projects',exact=True).click();new(root,'Launch project');root.locator('[data-field=objective]').fill('Introduce a client product');save(root)
                    projects=requests.get(origin+f'/api/agency/clients/{client}/records?kind=projects').json()['items'];project=projects[0]
                    page.locator('#agency-context-project').select_option(project['id'])
                    root.get_by_role('tab',name='Brand kits',exact=True).click();new(root,'Alpha Brand')
                    root.locator('[data-field=primary_color]').fill('#112233');root.locator('[data-field=accent_color]').fill('#44ccaa')
                    root.locator('[data-field=voice]').fill('Practical and precise')
                    root.locator('[data-field=legal_disclosures]').fill('Results vary.')
                    save(root)
                    root.locator('[data-field=voice]').fill('Practical, precise and evidence-led');save(root)
                    root.locator('[data-history] > summary').click()
                    root.locator('[data-versions]').get_by_text('Version 1',exact=True).wait_for()
                    brand=requests.get(origin+f'/api/agency/clients/{client}/records?kind=brands').json()['items'][0]
                    assert brand['version']==2
                    root.get_by_role('tab',name='Terminology',exact=True).click();new(root,'Official brand terminology')
                    root.locator('[data-field=source_term]').fill('LEXNIS')
                    root.locator('[data-field=approved_english]').fill('LEXNIS')
                    root.locator('[data-field=approved_arabic]').fill('لكسنيس')
                    save(root)
                    nav('Research');root=area('research');new(root,'Reviewed benchmark source')
                    root.locator('[data-field=content]').fill('Client reviewed benchmark supports reduced setup effort.')
                    root.locator('[data-field=evidence_state]').select_option('verified_source')
                    root.locator('[data-field=credibility]').select_option('high');save(root)
                    source=requests.get(origin+f'/api/agency/clients/{client}/records?kind=sources').json()['items'][0]
                    root.get_by_role('tab',name='Findings',exact=True).click();new(root,'Setup finding')
                    root.locator('[data-field=statement]').fill('Reviewed benchmark supports lower setup effort.')
                    root.locator('[data-field=source_ids]').select_option(source['id'])
                    root.locator('[data-field=classification]').select_option('fact')
                    root.locator('[data-field=evidence_state]').select_option('verified_source');save(root)
                    nav('Clients & Brands');root=area('clients')
                    root.get_by_role('tab',name='Evidence',exact=True).click();new(root,'Benchmark evidence')
                    root.locator('[data-field=summary]').fill('Reviewed client source')
                    root.locator('[data-field=source_type]').select_option('research-source')
                    root.locator('[data-field=source_ids]').select_option(source['id'])
                    root.locator('[data-field=state]').select_option('verified_source')
                    root.locator('[data-field=reviewer]').fill('Local reviewer');save(root)
                    proof=requests.get(origin+f'/api/agency/clients/{client}/records?kind=evidence').json()['items'][0]
                    root.get_by_role('tab',name='Claims',exact=True).click();new(root,'Approved setup claim')
                    root.locator('[data-field=text]').fill('Reduces setup effort.')
                    root.locator('[data-field=status]').select_option('verified')
                    root.locator('[data-field=reviewer]').fill('Local reviewer')
                    root.locator('[data-field=evidence_ids]').select_option(proof['id']);save(root)
                    claim=requests.get(origin+f'/api/agency/clients/{client}/records?kind=claims').json()['items'][0]
                    nav('Strategy');root=area('strategy')
                    root.get_by_role('tab',name='Audience segments',exact=True).click();new(root,'Operations teams')
                    root.locator('[data-field=source_ids]').select_option(source['id'])
                    root.locator('[data-field=needs]').fill('Reduce setup effort');save(root)
                    audience=requests.get(origin+f'/api/agency/clients/{client}/records?kind=audiences').json()['items'][0]
                    strategy=record(client,'strategies','Evidence-led strategy',dict(business_context='Client product launch',
                        audience_ids=[audience['id']],channels=['LinkedIn']),project=project['id'])
                    nav('Campaigns');root=area('campaigns');new(root,'Alpha campaign')
                    root.locator('[data-field=brand_id]').select_option(brand['id'])
                    root.locator('[data-field=strategy_id]').select_option(strategy['id'])
                    root.locator('[data-field=objective]').fill('Introduce the client product')
                    root.locator('[data-field=primary_kpi]').fill('Qualified enquiries');save(root)
                    campaign=requests.get(origin+f'/api/agency/clients/{client}/records?kind=campaigns').json()['items'][0]
                    root.locator('[data-use-campaign]').click()
                    page.wait_for_function("(key)=>document.querySelector('#agency-context-campaign').value===key",arg=campaign['id'])
                    root.locator('[data-build-brief]').click()
                    root.locator('[data-field=primary_message]').wait_for()
                    root.locator('[data-field=primary_message]').fill('Reduces setup effort.')
                    root.locator('[data-field=supporting_messages]').fill('Results vary.')
                    root.locator('[data-field=claim_ids]').select_option(claim['id'])
                    root.locator('[data-field=cta]').fill('Request a demo')
                    root.locator('[data-field=visual_direction]').fill('Use the actual client product, clean studio lighting')
                    save(root);root.locator('[data-checks]').click()
                    root.locator('[data-check-result]').get_by_text('No configured flags found.',exact=True).wait_for()
                    page.evaluate('window.scrollTo(0,0)');root.locator('[data-editor]').evaluate('e=>e.scrollTop=0');page.screenshot(path=str(evidence/'desktop.png'),full_page=True)
                    nav('Image & GIF Studio')
                    assert page.locator('#prompt-input').input_value()=='Keep this unsaved image draft'
                    nav('Campaigns');root.locator('[data-image]').click()
                    page.wait_for_function("!document.querySelector('#image-workspace').hidden")
                    assert 'Introduce the client product' in page.locator('#prompt-input').input_value()
                    assert page.locator('#brand-input').input_value()=='Alpha Brand'
                    assert page.evaluate('window.agencyProductionContext.campaign_id')==campaign['id']
                    assert not generations,generations
                    nav('Campaigns');root.get_by_role('tab',name='Campaigns',exact=True).click();root.locator('[data-open]').first.click()
                    with page.expect_download() as download:root.get_by_role('link',name='Export review plan (.zip)').click()
                    assert download.value.suggested_filename.endswith('.zip')
                    page.reload(wait_until='domcontentloaded')
                    page.wait_for_function("(id)=>document.querySelector('#agency-context-client')?.value===id",arg=client)
                    assert page.locator('#agency-context-campaign').input_value()==campaign['id']
                    page.locator('#rail-collapse').click();assert page.locator('body').evaluate("e=>e.classList.contains('rail-collapsed')")
                    page.locator('#rail-collapse').click()
                    beta=requests.post(origin+'/api/agency/clients',json=dict(name='Beta Client')).json()
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#agency-context-client').select_option(beta['id'])
                    nav('Research');root=area('research')
                    root.get_by_role('tab',name='Sources',exact=True).click()
                    root.get_by_text('No records yet. Create the first one with + New.',exact=True).wait_for()
                    new(root,'Beta source');assert root.locator('[data-field=content]').input_value()==''
                    page.locator('#agency-context-language').select_option('ar')
                    assert root.locator('.ag').get_attribute('dir')=='rtl'
                    root.locator('[data-field=content]').fill('منتج AI · 15 BHD · 2026/11/12 <script>window.injected=true</script>')
                    save(root);assert page.evaluate('window.injected') is None
                    nav('Dashboard')
                    page.locator('#ag-backup').click()
                    backup_link=page.locator('#ag-backup-result a')
                    backup_link.wait_for()
                    with page.expect_download() as backed_up:backup_link.click()
                    with zipfile.ZipFile(backed_up.value.path()) as bundle:
                        assert 'agency.sqlite3' in bundle.namelist() and 'manifest.json' in bundle.namelist()
                    mobile=browser.new_page(viewport={'width':390,'height':844})
                    mobile.route('https://**/*',external)
                    mobile.goto(origin,wait_until='domcontentloaded')
                    mobile.locator('.studio-mobile-toggle').click()
                    mobile.get_by_role('button',name='Clients & Brands',exact=True).click()
                    mobile.wait_for_selector('#agency-clients-workspace h1')
                    assert mobile.locator('.studio-mobile-toggle').get_attribute('aria-expanded')=='false'
                    assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    mobile.locator('.studio-mobile-toggle').click();mobile.keyboard.press('Escape')
                    assert mobile.locator('.studio-mobile-toggle').evaluate('e=>e===document.activeElement')
                    mobile.screenshot(path=str(evidence/'mobile.png'),full_page=True)
                    assert not errors,errors
                    browser.close()
                (evidence/'result.json').write_text(json.dumps(dict(passed=True,scenario='client → brand → research → evidence → claim → strategy → campaign → brief → checks → image handoff → ZIP export',real_ai_inference=False),indent=2))
                print('PASS: real agency browser workflow, persistence, client isolation, RTL, mobile, version history, checks, Image Studio handoff and ZIP export')
            finally:
                server.terminate();server.wait(timeout=15)


if __name__=='__main__':main()
