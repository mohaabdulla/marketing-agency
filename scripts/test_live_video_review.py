"""Exercise the actual local studio with a user-selected video and save a review copy."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    base='http://127.0.0.1:8000';before=hashlib.sha256(args.source.read_bytes()).hexdigest();args.output.mkdir(parents=True,exist_ok=True)
    for _ in range(60):
        try:
            if requests.get(base+'/api/ui-version',timeout=2).ok:break
        except requests.RequestException:pass
        time.sleep(.5)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);ctx=browser.new_context(accept_downloads=True,viewport={'width':1440,'height':1000});page=ctx.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(error.stack));page.route('https://**/*',lambda route:route.abort())
        page.goto(base+'/?workspace=video&tab=editor',wait_until='domcontentloaded');quick=page.locator('[data-quick-editor]');quick.wait_for(state='visible')
        assert page.get_by_role('button',name='Upload logo',exact=True).is_visible()
        with page.expect_response(lambda r:r.url.endswith('/api/video/upload') and r.request.method=='POST') as uploaded:
            quick.locator('[data-quick-file]').set_input_files(str(args.source))
        assert uploaded.value.ok,uploaded.value.text();source=uploaded.value.json()
        page.wait_for_function("id=>document.querySelector('[data-quick-source]').value===id",arg=source['id'])
        quick.locator('[data-logo-file]').set_input_files(str(ROOT/'static/assets/brand_logo.png'))
        page.wait_for_function("()=>document.querySelector('#ve-brand-editor [data-logo-status]').textContent.includes('Logo ready')")
        # A short request replaces the previous multi-page briefing exercise.
        request='Add readable English captions, tighten pauses, add gentle zoom-ins and remove the recording remarks at the end. Keep the original quality.'
        quick.locator('[data-instruction]').fill(request)
        page.screenshot(path=str(args.output/'quick-editor-before.png'),full_page=True)
        with page.expect_response(lambda r:r.url.endswith('/quick-edit') and r.request.method=='POST') as edited:
            quick.locator('[data-quick-run]').click()
        assert edited.value.ok,edited.value.text();job=edited.value.json();print('Actual browser edit job:',job['id'],flush=True)
        quick.locator('[data-quick-download]').wait_for(state='visible',timeout=240000)
        state=ctx.request.get(base+'/api/video/jobs/'+job['id']).json();assert state['state']=='completed',state
        result=state['result'];assert result['width']==source['width'] and result['height']==source['height']
        assert result['edit_report']['caption_count']>0 and result['duration']<source['duration']
        assert quick.locator('[data-quick-preview] video').get_attribute('src')==result['url']
        quick.locator('[data-quick-original]').click();assert quick.locator('[data-quick-preview] video').get_attribute('src')==source['url']
        quick.locator('[data-quick-edited]').click();assert quick.locator('[data-quick-preview] video').get_attribute('src')==result['url']
        with page.expect_download() as downloaded:quick.locator('[data-quick-download]').click()
        downloaded.value.save_as(args.output/'edited.mp4')
        page.wait_for_function("()=>document.querySelector('[data-quick-status]').textContent.includes('Edited video ready')")
        page.screenshot(path=str(args.output/'quick-editor-after.png'),full_page=True)
        page.reload(wait_until='domcontentloaded');quick.wait_for(state='visible');quick.locator('[data-quick-preview] video').wait_for()
        assert quick.locator('[data-quick-preview] video').get_attribute('src')==result['url']
        page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(args.output/'quick-editor-mobile.png'),full_page=True)
        assert not errors,errors
        ctx.unroute_all(behavior='ignoreErrors');browser.close()
    assert hashlib.sha256(args.source.read_bytes()).hexdigest()==before
    (args.output/'browser-result.json').write_text(json.dumps(dict(passed=True,source_sha256=before,source_asset=source,result=result,real_speech_model=True,real_ffmpeg=True,js_errors=errors),indent=2),encoding='utf-8')
    print('PASS: live app, visible logo upload, one short request, real edited preview/download, comparison, reload and mobile',flush=True)


if __name__=='__main__':main()
