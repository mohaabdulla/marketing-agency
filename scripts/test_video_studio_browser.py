"""Real local browser integration: workspace navigation, import, editing and CPU export."""
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
sys.path.insert(0,str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-video-browser-') as tmp:
        os.environ['VIDEO_DATA_DIR']=str(Path(tmp)/'store')
        os.environ['AGENCY_DATA_DIR']=str(Path(tmp)/'agency')
        from video_ffmpeg import ffmpeg
        source=Path(tmp)/'source.mp4'
        ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
        from PIL import Image
        picture=Path(tmp)/'employee.png';Image.new('RGB',(320,180),'#235487').save(picture)
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        with (Path(tmp)/'server.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],
                cwd=ROOT,env={**os.environ,'PYTHONIOENCODING':'utf-8'},stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(120):
                    try:
                        if requests.get(origin+'/api/video/assets',timeout=1).status_code==200:break
                    except requests.RequestException:time.sleep(.25)
                    if process.poll() is not None:raise RuntimeError((Path(tmp)/'server.log').read_text())
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':1500,'height':1100},accept_downloads=True)
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    def external(route):
                        if 'lucide' in route.request.url:route.fulfill(body='window.lucide={createIcons(){}};',content_type='application/javascript')
                        else:route.abort()
                    page.route('https://**/*',external)
                    page.goto(origin,wait_until='domcontentloaded')
                    page.wait_for_selector('.studio-rail')
                    assert page.locator('#image-workspace').is_visible()
                    page.locator('#prompt-input').fill('Unsaved employee welcome campaign')
                    page.get_by_role('button',name='Video Studio',exact=True).click()
                    page.wait_for_selector('#vg-form')
                    assert not page.locator('#image-workspace').is_visible()
                    assert page.locator('#vg-generate').is_disabled()
                    page.get_by_role('button',name='Image & GIF Studio',exact=True).click()
                    assert page.locator('#prompt-input').input_value()=='Unsaved employee welcome campaign'
                    page.get_by_role('button',name='Video Studio',exact=True).click()
                    page.get_by_role('tab',name='Media Library').click()
                    page.locator('#vs-upload-input').set_input_files(source)
                    page.wait_for_selector('.vs-clip',timeout=20000)
                    assert page.locator('#ve-preview video').is_visible()
                    page.locator('#ve-name').fill('Browser production project');page.locator('#ve-name').press('Tab')
                    page.locator('[data-prop=duration]').fill('1.5');page.locator('[data-prop=duration]').press('Tab')
                    page.locator('#ve-seek').evaluate("e=>{e.value='0.75';e.dispatchEvent(new Event('input',{bubbles:true}));}")
                    page.locator('#ve-split').click()
                    assert page.locator('.vs-lane[data-kind=video] .vs-clip').count()==2
                    clips=page.locator('.vs-lane[data-kind=video] .vs-clip')
                    first_id=clips.first.get_attribute('data-clip')
                    clips.first.drag_to(clips.last)
                    assert clips.last.get_attribute('data-clip')==first_id
                    page.once('dialog',lambda dialog:dialog.accept('Welcome / مرحبا'))
                    page.locator('#ve-title').click()
                    assert page.locator('.vs-lane[data-kind=title] .vs-clip').count()==1
                    page.locator('#ve-save').click();page.wait_for_function("document.querySelector('#ve-save-state').textContent === 'Saved'")
                    with page.expect_response(lambda response: response.url.endswith('/api/video/export') and response.request.method=='POST') as exported:
                        page.locator('#ve-export').click()
                    export_job=exported.value.json()['id']
                    # "completed_clips" appears during encoding; wait for this exact job's terminal state.
                    page.wait_for_selector(f'#vs-jobs [data-job="{export_job}"][data-state="completed"]',timeout=60000)
                    assets=requests.get(origin+'/api/video/assets',timeout=5).json()
                    assert any(a['name']=='export.mp4' and abs(a['duration']-1.5)<.2 for a in assets)
                    page.get_by_role('tab',name='Projects',exact=True).click();page.wait_for_selector('[data-open]')
                    assert page.locator('#vs-project-list').inner_text().find('Browser production project')>=0
                    page.locator('[data-open]').first.click();assert page.locator('#ve-name').input_value()=='Browser production project'
                    page.get_by_role('tab',name='AI Generate').click();page.locator('#vg-mode').select_option('image-animation')
                    assert page.locator('#vg-generate').is_enabled()
                    page.locator('#vg-upload').click()
                    page.locator('#vs-upload-input').set_input_files(picture)
                    page.wait_for_function("document.querySelector('#vg-image').value.length === 32")
                    page.locator('#vg-duration').fill('1')
                    with page.expect_response(lambda response: response.url.endswith('/api/video/generate') and response.request.method=='POST') as started:
                        page.locator('#vg-generate').click()
                    animation_job=started.value.json()['id']
                    page.wait_for_selector(f'#vs-jobs [data-job="{animation_job}"][data-state="completed"]',timeout=60000)
                    page.wait_for_selector('#vg-result a')
                    with page.expect_download() as download:page.locator('#vg-result a').click()
                    assert download.value.suggested_filename.endswith('.mp4')
                    assert not page.locator('#vs-message').is_visible()
                    page.screenshot(path=str(ROOT/'output/video-studio-desktop.png'),full_page=True)
                    page.get_by_role('button',name='System Status',exact=True).click()
                    page.wait_for_function("document.querySelector('#settings-workspace').textContent.includes('Available')")
                    page.reload(wait_until='domcontentloaded');page.wait_for_selector('#settings-workspace h1')
                    assert page.locator('#settings-workspace').is_visible()
                    page.get_by_role('button',name='Image & GIF Studio',exact=True).click()
                    # Generated campaign media enters the video workspace without browser reupload.
                    bridge=ROOT/'output/renders'/('video-browser-source-'+Path(tmp).name+'.png')
                    Image.open(picture).save(bridge)
                    try:
                        page.locator('#carousel-preview').evaluate("(e,url)=>{e.classList.remove('hidden');e.innerHTML='<div><img alt=\"Campaign output\"></div>';e.querySelector('img').src=new URL(url,location.href).href;for(let p=e;p&&p.id!=='image-workspace';p=p.parentElement)p.classList.remove('hidden');}",'/renders/'+bridge.name)
                        page.locator('#carousel-preview').get_by_role('button',name='Send to Video',exact=True).click()
                        page.wait_for_function("document.querySelectorAll('.vs-lane[data-kind=video] .vs-clip').length===3")
                        assert page.locator('#video-workspace').is_visible()
                    finally:
                        bridge.unlink(missing_ok=True)
                    mobile=browser.new_page(viewport={'width':390,'height':844})
                    mobile.route('https://**/*',external)
                    mobile.goto(origin,wait_until='domcontentloaded');mobile.wait_for_selector('.studio-mobile-toggle')
                    mobile.locator('.studio-mobile-toggle').click()
                    assert mobile.locator('.studio-rail').evaluate("e=>e.classList.contains('drawer-open')")
                    mobile.get_by_role('button',name='Video Studio',exact=True).click();mobile.wait_for_selector('#vg-form')
                    assert mobile.locator('.studio-mobile-toggle').get_attribute('aria-expanded')=='false'
                    assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    mobile.locator('.studio-mobile-toggle').click();mobile.keyboard.press('Escape')
                    assert mobile.locator('.studio-mobile-toggle').evaluate('e=>e===document.activeElement')
                    mobile.screenshot(path=str(ROOT/'output/video-studio-mobile.png'),full_page=True)
                    assert not errors,errors
                    browser.close()
                print('PASS: desktop/mobile navigation, preserved image form, video upload, trim, save/reopen, real MP4 export, CPU animation and download')
            finally:
                process.terminate();process.wait(timeout=15)


if __name__=='__main__':main()
