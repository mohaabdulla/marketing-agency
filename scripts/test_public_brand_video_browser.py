"""Actual guest browser upload → guideline review → preview/apply → render → undo/redo/export."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-public-browser-') as tmp:
        tmp=Path(tmp)
        os.environ['VIDEO_DATA_DIR']=str(tmp/'video-tools-work')
        sys.path.insert(0,str(ROOT))
        from video_ffmpeg import ffmpeg
        source=tmp/'original.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=0x223344:s=320x240:d=3:r=24','-c:v','libx264','-pix_fmt','yuv420p',str(source)],timeout=30)
        guide=tmp/'brand.md';guide.write_text('Brand: Noor Solar\nPrimary color: #ffffff\nFonts: Arial\nCTA: Book a demo\nRequired disclosure: Sponsored\nAnimation: smooth and subtle\n',encoding='utf-8')
        captions=tmp/'captions.srt';captions.write_text('1\n00:00:00,000 --> 00:00:02,500\nمرحبا بكم\n',encoding='utf-8')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        evidence=ROOT/'output/public-brand-video';evidence.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'PUBLIC_TEST_MODE':'true','PUBLIC_TEST_DATA_DIR':str(tmp/'guests'),
             'VIDEO_DATA_DIR':str(tmp/'video'),'AGENCY_DATA_DIR':str(tmp/'agency'),'LOCAL_TEXT_URL':'','PYTHONIOENCODING':'utf-8'}
        with (evidence/'browser-server.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],
                                    cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(120):
                    try:
                        if requests.get(origin+'/api/session',timeout=1).ok:break
                    except requests.RequestException:time.sleep(.25)
                    if server.poll() is not None:raise RuntimeError('Preview server stopped')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True)
                    a=browser.new_context(accept_downloads=True,viewport={'width':1500,'height':1050})
                    page=a.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)+'\n'+str(e.stack)))
                    page.route('https://**/*',lambda route:route.abort())
                    operator_draft=json.dumps({'id':'operator-project','project':{'name':'Operator work','clips':[]}})
                    seeds={'lexnis.video.draft':operator_draft,'lexnis.workspace':'settings','lexnis.agency.context':json.dumps({'language':'ar'})}
                    page.goto(origin+'/api/session',wait_until='domcontentloaded')
                    page.evaluate('(entries)=>{for(const [k,v] of Object.entries(entries))localStorage.setItem(k,v)}',seeds)
                    page.goto(origin,wait_until='domcontentloaded')
                    page.locator('#public-testing-notice').wait_for()
                    assert page.get_by_role('button',name='System Status',exact=True).count()==0
                    page.get_by_role('button',name='Video Studio',exact=True).click()
                    page.locator('#vs-tab-editor').click()
                    page.get_by_role('button',name='Advanced editor',exact=True).click()
                    assert page.locator('#ve-name').input_value()=='Untitled video'
                    assert page.evaluate('(keys)=>Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)]))',list(seeds))==seeds
                    page.locator('#vs-upload-input').set_input_files(str(source))
                    page.wait_for_function("()=>document.querySelectorAll('#ve-lanes [data-clip]').length===1")
                    panel=page.locator('#ve-brand-editor')
                    panel.locator('[data-file]').set_input_files(str(guide))
                    panel.locator('[data-rule=brand_name]').wait_for()
                    assert panel.locator('[data-rule=brand_name]').input_value()=='Noor Solar'
                    panel.locator('[data-confirm]').click()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-associated]')?.textContent.includes('Applied guideline')")
                    assert panel.locator('[data-ai]').is_disabled()
                    with page.expect_response(lambda r:r.url.endswith('/captions/import') and r.request.method=='POST') as captions_response:
                        panel.locator('[data-srt]').set_input_files(str(captions))
                    assert captions_response.value.ok,captions_response.value.text()
                    page.wait_for_function("()=>document.querySelectorAll('#ve-lanes [data-clip]').length===2")
                    with page.expect_response(lambda r:r.url.endswith('/analyze') and r.request.method=='POST') as analysis_response:
                        panel.locator('[data-analyze]').click()
                    analysis_id=analysis_response.value.json()['id']
                    page.locator('[data-job="'+analysis_id+'"][data-state=completed]').wait_for(timeout=60000)
                    panel.locator('[data-instruction]').fill('Follow our brand, make the video professional and include the approved CTA.')
                    panel.locator('[data-polish]').click()
                    panel.locator('[data-apply-plan]').wait_for()
                    panel.locator('[data-reject-plan]').click()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-plan]').textContent.includes('Proposal rejected')")
                    panel.locator('[data-polish]').click()
                    panel.locator('[data-apply-plan]').wait_for()
                    panel.locator('[data-apply-plan]').click()
                    panel.locator('[data-compliance-result]').get_by_text('Brand compliance',exact=True).wait_for()
                    with page.expect_response(lambda r:r.url.endswith('/api/video/export') and r.request.method=='POST') as preview_response:
                        page.locator('#ve-preview-render').click()
                    preview_id=preview_response.value.json()['id']
                    page.locator('[data-job="'+preview_id+'"][data-state=completed]').wait_for(timeout=60000)
                    preview_job=await_json(a.request.get(origin+'/api/video/jobs/'+preview_id))
                    page.wait_for_function("id=>document.querySelector('#ve-preview video')?.getAttribute('src')?.endsWith(id)",arg=preview_job['result']['id'])
                    page.locator('#ve-save').click()
                    page.wait_for_function("()=>document.querySelector('#ve-save-state').textContent==='Saved'")
                    projects=await_json(a.request.get(origin+'/api/video/projects'))
                    project=projects[0]
                    assert any(c['text']=='Book a demo' for c in project['clips'])
                    assert project['guideline_id']
                    panel.locator('[data-instruction]').fill('Make the captions larger.')
                    panel.locator('[data-polish]').click()
                    panel.locator('[data-apply-plan]').wait_for()
                    panel.locator('[data-apply-plan]').click()
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-plan]').textContent.includes('Edits applied')")
                    panel.locator('[data-undo]').click()
                    panel.locator('[data-redo]').click()
                    panel.locator('[data-history]').click()
                    panel.locator('[data-history-list] h3').wait_for()
                    # Reuse Video-uploaded rules in Image/GIF without another upload.
                    page.get_by_role('button',name='Image & GIF Studio',exact=True).click()
                    page.locator('[data-refresh-guidelines]').click()
                    page.locator('[data-shared-guidelines]').select_option(project['guideline_id'])
                    page.locator('[data-use-guidelines]').click()
                    page.wait_for_function("()=>window.brandProfile?.brand_name==='Noor Solar'")
                    # A separate cookie jar cannot see a saved project, render or original.
                    b=browser.new_context();other=b.new_page();other.goto(origin,wait_until='domcontentloaded')
                    response=b.request.get(origin+'/api/video/projects/'+project['id'])
                    assert response.status==404,response.text()
                    assert await_json(b.request.get(origin+'/api/video/projects'))==[]
                    assert b.request.get(origin+'/api/system/capabilities').status==403
                    page.get_by_role('button',name='Video Studio',exact=True).click()
                    page.locator('#vs-tab-editor').click()
                    with page.expect_response(lambda r:r.url.endswith('/api/video/export') and r.request.method=='POST') as export_response:
                        page.locator('#ve-export').click()
                    export_id=export_response.value.json()['id']
                    page.locator('[data-job="'+export_id+'"][data-state=completed]').wait_for(timeout=60000)
                    media=await_json(a.request.get(origin+'/api/video/assets'))
                    exports=[m for m in media if m['id']!=project['clips'][0]['asset_id'] and m['kind']=='video']
                    assert exports
                    result=a.request.get(origin+'/api/video/download/'+exports[0]['id'])
                    assert result.ok and len(result.body())>1000
                    original=a.request.get(origin+'/api/video/media/'+project['clips'][0]['asset_id'])
                    assert original.body()==source.read_bytes()
                    page.screenshot(path=str(evidence/'desktop.png'))
                    guest_draft=page.evaluate("()=>localStorage.getItem('lexnis.video.draft.guest.'+window.lexnisGuestWorkspace)")
                    assert json.loads(guest_draft)['id']==project['id']
                    assert page.evaluate('(keys)=>Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)]))',list(seeds))==seeds
                    page.reload(wait_until='domcontentloaded')
                    page.get_by_role('button',name='Video Studio',exact=True).click()
                    page.locator('#vs-tab-editor').click()
                    panel=page.locator('#ve-brand-editor')
                    page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-associated]')?.textContent.includes('Applied guideline')")
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(evidence/'mobile.png'),full_page=True)
                    assert not errors,errors
                    browser.close()
                (evidence/'result.json').write_text(json.dumps(dict(passed=True,real_ai_inference=False,real_ffmpeg=True,
                    scenario='guest upload → shared guideline review → actual edits → render → revision → reuse in Image/GIF → isolation → export → reload/mobile'),indent=2))
                print('PASS: real public guest, branded edits, render/export, revisions, shared guidelines, isolation, reload/mobile')
            finally:
                server.terminate();server.wait(timeout=15)


def await_json(response):
    assert response.ok,response.text()
    return response.json()


if __name__=='__main__':
    main()
