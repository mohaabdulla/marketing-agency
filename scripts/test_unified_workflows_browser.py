"""Real browser parity: shared guidelines, assistants, still/GIF/MP4 output and agency navigation.

Cloud providers are disabled by the existing offline test worker. Rendering is real;
editable templates and CPU animation are explicitly not AI model inference.
"""
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
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-unified-browser-') as folder:
        tmp=Path(folder);guide=tmp/'brand.md';guide.write_text('Brand: Noor Solar\nPrimary color: #ffffff\nFonts: Arial\nCTA: Book a demo\nAnimation: smooth and subtle\n',encoding='utf-8')
        invalid=tmp/'invalid.pdf';invalid.write_bytes(b'not a brand guideline')
        image=tmp/'employee.png';Image.new('RGB',(480,600),'#223344').save(image)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';evidence=ROOT/'output/unified-workflows';evidence.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'PUBLIC_TEST_MODE':'true','PUBLIC_TEST_DATA_DIR':str(tmp/'guests'),
             'VIDEO_DATA_DIR':str(tmp/'video'),'AGENCY_DATA_DIR':str(tmp/'agency'),'LOCAL_TEXT_URL':'','PYTHONIOENCODING':'utf-8'}
        with (evidence/'server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'scripts/agency_regression_worker.py','--serve',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin+'/api/session',timeout=1).ok:break
                    except requests.RequestException:time.sleep(.25)
                    if server.poll() is not None:raise RuntimeError('Server failed; inspect output/unified-workflows/server.log')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True);ctx=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000});page=ctx.new_page();errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error.stack)))
                    page.route('https://**/*',lambda route:route.abort())
                    page.goto(origin,wait_until='domcontentloaded');page.locator('[data-workflow=image-gif]').wait_for()
                    page.wait_for_function("()=>document.querySelector('#engine-status-text').textContent.includes('ONLINE')")
                    assert not errors,errors
                    # Back/Next in focused mode preserve the same prompt element and input.
                    flow=page.locator('[data-workflow=image-gif]');page.locator('#prompt-input').fill('Welcome Amal, our new engineer, to Noor Solar.')
                    flow.locator('[data-focused]').check();flow.locator('nav button').nth(2).click()
                    flow.locator('[data-flow-step="3"] .flow-controls').get_by_role('button',name='Next',exact=True).click()
                    flow.locator('[data-flow-step="4"] .flow-controls').get_by_role('button',name='Back',exact=True).click()
                    assert page.locator('#prompt-input').input_value().startswith('Welcome Amal')
                    flow.locator('[data-focused]').uncheck()
                    # Invalid uploads must leave an error, never manufacture successful extraction.
                    with page.expect_response(lambda r:'/api/upload-guidelines' in r.url and r.request.method=='POST') as bad:
                        page.locator('#guidelines-file-input').set_input_files(str(invalid))
                    assert not bad.value.ok
                    page.wait_for_function("()=>document.querySelector('#toast-message').textContent.includes('Could not load guidelines')")
                    with page.expect_response(lambda r:'/api/upload-guidelines' in r.url and r.request.method=='POST') as uploaded:
                        page.locator('#guidelines-file-input').set_input_files(str(guide))
                    assert uploaded.value.ok,uploaded.value.text();document=uploaded.value.json()
                    assert document['id']
                    page.locator('[data-image-guideline-review] [data-confirm]').click()
                    page.wait_for_function("()=>document.querySelector('[data-shared-status]').textContent==='Ready.'&&window.brandProfile?.brand_name==='Noor Solar'")
                    # Image assistant accepts reviewed suggestions into the actual campaign request.
                    assistant=flow.locator('[data-prompt-assistant]');assistant.locator('summary').click()
                    assistant.locator('[data-assist=improve]').click();assistant.locator('[data-use]').wait_for()
                    assert 'no AI inference' in assistant.locator('[data-assistant-status]').inner_text()
                    assistant.locator('[data-use]').click();assert 'Noor Solar' in page.locator('#prompt-input').input_value()
                    with page.expect_response(lambda r:'/api/upload-visual' in r.url and r.request.method=='POST') as source:
                        page.locator('#subject-file-input').set_input_files(str(image))
                    assert source.value.ok,source.value.text()
                    for key,value in [('pt-member-name','Amal'),('pt-member-role','Engineer')]:
                        if page.locator('#'+key).is_visible():page.locator('#'+key).fill(value)
                    page.locator('#review-prompt-toggle').uncheck();page.locator('#search-toggle').uncheck()
                    with page.expect_response(lambda r:r.url.endswith('/api/campaign/generate') and r.request.method=='POST',timeout=600000) as generated:
                        page.locator('#generate-btn').click()
                    assert generated.value.ok,generated.value.text()[:2000];kit=generated.value.json()
                    posted=generated.value.request.post_data_json;assert 'Noor Solar' in posted['prompt']
                    assert all('/test_assets/' not in value for value in posted['uploaded_image_urls'])
                    page.locator('#carousel-preview img').first.wait_for();assert kit['animation_url']
                    with page.expect_download() as static:page.locator('#carousel-preview').get_by_role('button',name='Download Static Card 1',exact=True).first.click()
                    with Image.open(static.value.path()) as card:assert card.width>100 and card.format in {'JPEG','PNG'}
                    # Generate again with the accepted GIF-specific instructions, then download that new loop.
                    page.locator('#creative-output-kind').select_option('gif');assistant.locator('[data-assist=generate]').click();assistant.locator('[data-use]').wait_for()
                    assert 'loop' in assistant.locator('[data-suggested]').input_value().lower()
                    assistant.locator('[data-use]').click()
                    gif_prompt=page.locator('#prompt-input').input_value()
                    with page.expect_response(lambda r:r.url.endswith('/api/campaign/generate') and r.request.method=='POST',timeout=600000) as animated:
                        page.locator('#generate-btn').click()
                    assert animated.value.ok,animated.value.text()[:2000]
                    assert animated.value.request.post_data_json['prompt']==gif_prompt
                    gif_kit=animated.value.json()
                    page.wait_for_function("url=>[...document.querySelectorAll('#carousel-preview img')].some(img=>img.src.endsWith(url))",arg=gif_kit['animation_url'])
                    with page.expect_download() as gif:page.locator('#carousel-preview').get_by_role('button',name='Download GIF',exact=True).first.click()
                    with Image.open(gif.value.path()) as animation:assert animation.is_animated and animation.info['loop']==0
                    print('PASS: real Image/GIF generation, assistant handoff, downloads and step navigation',flush=True)
                    # Video Generation: the shared upload is visible before opening the editor.
                    page.get_by_role('button',name='Video Generator',exact=True).click();page.locator('#vg-mode').select_option('image-animation')
                    panel=page.locator('#vg-brand-guidelines');panel.locator('[data-file]').set_input_files(str(invalid))
                    page.wait_for_function("()=>document.querySelector('#vg-brand-guidelines [data-status]').textContent!=='Working…'&&document.querySelector('#vg-brand-guidelines [data-status]').textContent!=='Ready.'")
                    panel.locator('[data-file]').set_input_files(str(guide));panel.locator('[data-confirm]').wait_for();panel.locator('[data-confirm]').click()
                    page.wait_for_function("()=>document.querySelector('#vg-brand-guidelines [data-associated]').textContent.includes('Selected for generation')")
                    page.locator('#vg-upload').click();page.locator('#vs-upload-input').set_input_files(str(image))
                    page.wait_for_function("()=>!!document.querySelector('#vg-image').value")
                    page.locator('#vg-prompt').fill('Welcome Amal with a gentle brand entrance.')
                    page.locator('#vg-form [data-objective=objective]').fill('Welcome a new engineer')
                    va=page.locator('#vg-form [data-prompt-assistant]');va.locator('summary').click()
                    with page.expect_response(lambda r:r.url.endswith('/api/creative/assistant/suggest')) as suggested:
                        va.locator('[data-assist=brand]').click()
                    assert suggested.value.ok,suggested.value.text()
                    va.locator('[data-use]').wait_for();va.locator('[data-use]').click()
                    accepted=page.locator('#vg-prompt').input_value();assert 'Noor Solar' in accepted
                    page.locator('#vg-duration').fill('1')
                    with page.expect_response(lambda r:r.url.endswith('/api/video/generate') and r.request.method=='POST') as video:
                        page.locator('#vg-generate').click()
                    assert video.value.ok,video.value.text();body=video.value.request.post_data_json
                    assert body['guideline_id'] and body['prompt']==accepted
                    job=video.value.json();page.locator('[data-job="'+job['id']+'"][data-state=completed]').wait_for(timeout=120000)
                    page.locator('#vg-preview video').wait_for()
                    with page.expect_download() as mp4:page.locator('#vg-result').get_by_role('link',name='Download video',exact=True).click()
                    assert Path(mp4.value.path()).stat().st_size>1000
                    page.locator('#vg-add-result').click();page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-associated]').textContent.includes('Applied guideline')")
                    page.get_by_role('button',name='Advanced editor',exact=True).click();editor=page.locator('#ve-brand-editor');editor.locator('[data-instruction]').fill('Make the opening shorter and follow the brand guidelines.')
                    ea=editor.locator('[data-prompt-assistant]');ea.evaluate('(node)=>node.open=true');ea.locator('[data-assist=professional]').click();ea.locator('[data-use]').wait_for();ea.locator('[data-use]').click()
                    editor.locator('[data-polish]').click();editor.locator('[data-apply-plan]').wait_for();editor.locator('[data-apply-plan]').click()
                    editor.locator('[data-compliance-result] h3').wait_for();assert editor.locator('[data-ai]').is_disabled()
                    print('PASS: visible video guideline upload, real branded CPU output and editor prompt handoff',flush=True)
                    # Exercise every existing top-level destination, with empty-state errors treated explicitly.
                    destinations=page.locator('#studio-navigation [data-workspace]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.workspace)')
                    for name in destinations:
                        page.locator('#studio-navigation [data-workspace="'+name+'"]').click()
                        page.locator('#'+('video' if name=='video-editor' else name)+'-workspace').wait_for(state='visible')
                    # Explicit context, escaping and the corrected POST ZIP download in Command Center.
                    client=ctx.request.post(origin+'/api/agency/clients',data={'name':'Browser client'}).json()
                    campaign=ctx.request.post(origin+'/api/agency/clients/'+client['id']+'/records/campaigns',data={'name':'<img src=x onerror="window.cccInjected=true">','data':{'objective':'Launch'}}).json()
                    page.evaluate("async record=>{const module=await import('/static/js/app-context.js?v='+window.lexnisUiVersion);await module.setCampaign(record)}",campaign)
                    page.locator('#studio-navigation [data-workspace=agency-command-center]').click();page.locator('#ccc-export-pkg-btn').wait_for()
                    assert not page.evaluate('window.cccInjected||false')
                    with page.expect_download() as archive:page.locator('#ccc-export-pkg-btn').click()
                    with zipfile.ZipFile(archive.value.path()) as bundle:assert bundle.namelist()
                    page.get_by_role('button',name='Video Generator',exact=True).click();page.locator('#vs-tab-generate').click();assert page.locator('#vg-prompt').input_value()==accepted
                    page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='Video Generator',exact=True).click();page.locator('#vs-tab-generate').click()
                    assert page.locator('#vg-prompt').input_value()==accepted
                    page.wait_for_function("()=>document.querySelector('#vg-model-info').textContent.includes('Deterministic image animation')")
                    page.wait_for_function("()=>document.querySelector('#vg-brand-guidelines [data-associated]').textContent.includes('Selected for generation')")
                    page.locator('#vg-preview video').wait_for()
                    page.locator('#vg-result').get_by_role('link',name='Download video',exact=True).wait_for()
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(evidence/'mobile.png'),full_page=True)
                    assert not errors,errors
                    page.set_viewport_size({'width':1440,'height':1000});page.screenshot(path=str(evidence/'desktop.png'),full_page=True)
                    ctx.unroute_all(behavior='ignoreErrors');browser.close()
                (evidence/'result.json').write_text(json.dumps(dict(passed=True,real_rendering=True,real_ai_inference=False,workspaces=len(destinations),features=['still','gif','branded-video','editing','prompt-assistant','step-navigation','invalid-upload','command-center-export','reload','mobile']),indent=2),encoding='utf-8')
                print('PASS: every workspace, command center context/escaping/export, persistence and mobile',flush=True)
            finally:server.terminate();server.wait(timeout=15)


if __name__=='__main__':main()
