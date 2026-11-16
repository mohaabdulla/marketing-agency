"""Actual editor setup: purpose, separate logo, identity, contextual prompt and export."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import requests
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-editing-setup-') as folder:
        tmp=Path(folder);os.environ['VIDEO_DATA_DIR']=str(tmp/'tools');sys.path.insert(0,str(ROOT))
        from video_ffmpeg import ffmpeg
        source=tmp/'original.mp4';ffmpeg(['-f','lavfi','-i','color=c=0x223344:s=320x240:d=2:r=24','-c:v','libx264','-pix_fmt','yuv420p',str(source)],timeout=30)
        logo=tmp/'company-logo.png';Image.new('RGBA',(160,80),'#e4572e').save(logo)
        bad=tmp/'not-a-logo.svg';bad.write_text('<svg></svg>',encoding='utf-8')
        guide=tmp/'brand.md';guide.write_text('Brand: Noor Solar\nPrimary color: #ffffff\nFonts: Arial\nCTA: Book a demo\nAnimation: smooth and subtle\n',encoding='utf-8')
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';evidence=ROOT/'output/video-editing-setup';evidence.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'PUBLIC_TEST_MODE':'true','PUBLIC_TEST_DATA_DIR':str(tmp/'guests'),'VIDEO_DATA_DIR':str(tmp/'video'),'AGENCY_DATA_DIR':str(tmp/'agency'),'LOCAL_TEXT_URL':'','PYTHONIOENCODING':'utf-8'}
        with (evidence/'server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin+'/api/session',timeout=1).ok:break
                    except requests.RequestException:time.sleep(.25)
                    if server.poll() is not None:raise RuntimeError('Server stopped; inspect server.log')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True);ctx=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000});page=ctx.new_page();errors=[]
                    page.on('pageerror',lambda error:errors.append(error.stack));page.route('https://**/*',lambda route:route.abort())
                    page.goto(origin,wait_until='domcontentloaded');page.get_by_role('button',name='Video Editor',exact=True).click();page.locator('#vs-tab-editor').click()
                    page.get_by_role('button',name='Advanced editor',exact=True).click()
                    panel=page.locator('#ve-brand-editor');flow=panel.locator('[data-workflow=video-edit]')
                    assert flow.locator(':scope > [data-flow-step]').count()==10
                    headings=flow.locator(':scope > [data-flow-step] > h2').all_text_contents()
                    assert 'Your prompt & enhancer' in headings[7] and 'Settings' in headings[6]
                    assert panel.locator('[data-video-purpose]').count()==9
                    panel.locator('[data-video-purpose=team_welcome]').click()
                    page.locator('#vs-upload-input').set_input_files(str(source));page.wait_for_function("()=>document.querySelectorAll('#ve-lanes [data-clip]').length===1")
                    panel.locator('[data-person-name]').fill('Amal Hassan');panel.locator('[data-person-position]').fill('Marketing Manager')
                    panel.locator('[data-logo-file]').set_input_files(str(bad));page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-logo-status]').textContent.includes('PNG')")
                    with page.expect_response(lambda r:r.url.endswith('/api/video/upload') and r.request.method=='POST') as uploaded:
                        panel.locator('[data-logo-file]').set_input_files(str(logo))
                    assert uploaded.value.ok,uploaded.value.text();logo_asset=uploaded.value.json()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-logo-status]').textContent.includes('Logo ready')")
                    assert page.locator('#ve-lanes [data-clip]').count()==1,'Uploading a logo must not add it as primary footage'
                    assert panel.locator('[data-logo-preview] img').get_attribute('src').endswith(logo_asset['id'])
                    panel.locator('[data-file]').set_input_files(str(guide));panel.locator('[data-confirm]').wait_for();panel.locator('[data-confirm]').click()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-associated]').textContent.includes('Applied guideline')")
                    panel.locator('[data-objective=objective]').fill('Welcome our new colleague')
                    panel.locator('[data-objective=platform]').fill('LinkedIn')
                    flow.locator('[data-focused]').check();flow.locator('nav button').nth(4).click()
                    flow.locator('[data-flow-step="5"] .flow-controls').get_by_role('button',name='Next',exact=True).click()
                    flow.locator('[data-flow-step="6"] .flow-controls').get_by_role('button',name='Back',exact=True).click()
                    assert panel.locator('[data-person-name]').input_value()=='Amal Hassan'
                    flow.locator('nav button').nth(0).click();page.screenshot(path=str(evidence/'purpose-desktop.png'),full_page=True)
                    flow.locator('nav button').nth(7).click()
                    assistant=panel.locator('[data-prompt-assistant]')
                    with page.expect_response(lambda r:r.url.endswith('/api/creative/assistant/suggest')) as suggested:
                        assistant.locator('[data-assist=generate]').click()
                    assert suggested.value.ok,suggested.value.text();payload=suggested.value.request.post_data_json
                    assert payload['editing_brief']['purpose']=='team_welcome'
                    assert payload['editing_brief']['logo_asset_id']==logo_asset['id']
                    for detail in ['Amal Hassan','Marketing Manager','LinkedIn','Noor Solar','uploaded logo']:
                        assert detail in suggested.value.json()['prompt'],detail
                    assistant.locator('[data-use]').click();accepted=panel.locator('[data-instruction]').input_value()
                    with page.expect_response(lambda r:r.url.endswith('/brand-edit/preview') and r.request.method=='POST') as planned:
                        panel.locator('[data-polish]').click()
                    assert planned.value.ok,planned.value.text();assert planned.value.request.post_data_json['instruction']==accepted
                    proposal=planned.value.json();clips=proposal['proposed_project']['clips']
                    assert any(c['text']=='Amal Hassan' for c in clips)
                    assert any(c['text']=='Marketing Manager' for c in clips)
                    assert any(c['kind']=='overlay' and c['asset_id']==logo_asset['id'] for c in clips)
                    panel.locator('[data-apply-plan]').click();page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-plan]').textContent.includes('Edits applied')")
                    page.screenshot(path=str(evidence/'prompt-desktop.png'),full_page=True)
                    flow.locator('nav button').nth(9).click()
                    with page.expect_response(lambda r:r.url.endswith('/api/video/export') and r.request.method=='POST') as exported:
                        page.locator('#ve-export').click()
                    assert exported.value.ok,exported.value.text();job=exported.value.json()
                    page.locator('[data-job="'+job['id']+'"][data-state=completed]').wait_for(timeout=90000)
                    result=ctx.request.get(origin+'/api/video/jobs/'+job['id']).json()['result']
                    download=ctx.request.get(origin+'/api/video/download/'+result['id']);assert download.ok and len(download.body())>1000
                    assert ctx.request.get(origin+'/api/video/media/'+proposal['proposed_project']['clips'][0]['asset_id']).body()==source.read_bytes()
                    page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='Video Editor',exact=True).click();page.locator('#vs-tab-editor').click()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-person-name]').value==='Amal Hassan'")
                    assert panel.locator('[data-person-position]').input_value()=='Marketing Manager'
                    assert panel.locator('[data-instruction]').input_value()==accepted
                    assert panel.locator('[data-video-purpose=team_welcome]').get_attribute('aria-pressed')=='true'
                    assert panel.locator('[data-logo-library]').input_value()==logo_asset['id']
                    flow.locator('nav button').nth(4).click();page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(evidence/'name-position-mobile.png'),full_page=True)
                    assert not errors,errors
                    ctx.unroute_all(behavior='ignoreErrors');browser.close()
                (evidence/'result.json').write_text(json.dumps(dict(passed=True,steps=10,real_ffmpeg=True,real_ai_inference=False,purpose=True,logo_upload=True,identity=True,prompt_context=True,persistence=True,mobile=True),indent=2),encoding='utf-8')
                print('PASS: video purpose, logo upload, identity, contextual enhancer, actual edit/export, reload and mobile',flush=True)
            finally:server.terminate();server.wait(timeout=15)


if __name__=='__main__':main()
