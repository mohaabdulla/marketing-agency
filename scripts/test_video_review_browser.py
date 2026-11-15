"""Inspect a real rendered review in the live studio; no media/model response is mocked."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path)
    args=parser.parse_args()
    evidence=json.loads(args.result.read_text(encoding='utf-8'))
    result,source=evidence['result'],evidence['source_asset']
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_init_script('localStorage.setItem("lexnis.video.quick-result",'+json.dumps(json.dumps({'id':result['id']}))+');')
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('https://**/*',lambda route:route.abort())
        page.goto('http://127.0.0.1:8000/?workspace=video&tab=editor',wait_until='domcontentloaded')
        quick=page.locator('[data-quick-editor]');quick.wait_for(state='visible')
        page.wait_for_function('(id)=>[...document.querySelector("[data-quick-source]").options].some(o=>o.value===id)',arg=source['id'])
        quick.locator('[data-quick-source]').select_option(source['id'])
        quick.locator('[data-quick-download]').wait_for(state='visible')
        assert quick.locator('[data-quick-preview] video').get_attribute('src')==result['url']
        if result.get('parent_asset_id'):
            assert quick.locator('[data-quick-previous]').is_enabled()
            quick.locator('[data-quick-previous]').click()
            assert result['parent_asset_id'] in quick.locator('[data-quick-preview] video').get_attribute('src')
            quick.locator('[data-quick-edited]').click()
            assert quick.locator('[data-quick-preview] video').get_attribute('src')==result['url']
        with page.expect_download() as downloaded:
            quick.locator('[data-quick-download]').click()
        browser_copy=args.result.parent/'browser-edited.mp4'
        downloaded.value.save_as(browser_copy)
        assert hashlib.sha256(browser_copy.read_bytes()).digest()==hashlib.sha256((args.result.parent/'edited.mp4').read_bytes()).digest()
        assert quick.locator('[data-logo-upload]').is_visible()
        assert quick.locator('[data-quick-style]').evaluate('node=>!!node.closest("details:not([open])")')
        requests=quick.locator('[data-quick-requests]').inner_text()
        for word in ('background','lighting','words','effects'):
            assert word in requests.lower(),requests
        assert quick.locator('[data-quick-gates] .ve-gate').count()==5
        review=quick.locator('[data-quick-review-state]')
        page.wait_for_function('()=>document.querySelector("[data-quick-review-state]").textContent.includes("Review status:")')
        assert 'DRAFT' in review.inner_text()
        review.locator('[data-review-note]').fill('Browser regression check; no client approval.')
        review.locator('[data-review-next]').click()
        page.wait_for_function('()=>document.querySelector("[data-quick-review-state] h3")?.textContent==="Review status: INTERNAL REVIEW"')
        if result['editorial_report']['publish_readiness']=='DRAFT':
            review.locator('[data-review-next]').click()
            page.wait_for_function('()=>document.querySelector("[data-quick-review-state] h3")?.textContent==="Review status: CLIENT REVIEW"')
            review.locator('[data-review-next]').click()
            page.wait_for_function('()=>document.querySelector("[data-review-message]")?.textContent.includes("Resolve caption review")')
            assert 'CLIENT REVIEW' in review.inner_text()
        review.locator('[data-review-draft]').click()
        page.wait_for_function('()=>document.querySelector("[data-quick-review-state] h3")?.textContent==="Review status: DRAFT"')
        quick.locator('[data-quick-sync]').click()
        page.wait_for_function('()=>document.querySelector("[data-compare-edit]").readyState>=2&&document.querySelector("[data-compare-source]").readyState>=2')
        page.evaluate('()=>{const v=document.querySelector("[data-compare-edit]");v.currentTime=2;return v.play()}')
        page.wait_for_function('()=>document.querySelector("[data-compare-edit]").currentTime>2.3')
        times=page.evaluate('()=>{const e=document.querySelector("[data-compare-edit]"),s=document.querySelector("[data-compare-source]");e.pause();return {edited:e.currentTime,source:s.currentTime,muted:s.muted}}')
        mapped=times['edited']
        for cut in sorted(result['edit_report']['cuts'],key=lambda c:c['start']):
            if mapped+.001>=cut['start']:mapped+=cut['end']-cut['start']
        assert abs(mapped-times['source'])<.3,times
        assert times['muted']
        quick.locator('section[data-step=preview]').scroll_into_view_if_needed()
        page.screenshot(path=str(args.result.parent/'comparison-browser.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()
    (args.result.parent/'review-browser.json').write_text(json.dumps(dict(passed=True,js_errors=errors,comparison_times=times,
        checks=['actual rendered asset restored','logo upload visible','extra settings collapsed','request fulfillment','separate gates',
                'review transitions and readiness block','previous/current switching','exact downloaded bytes','synchronized playback','mobile width']),indent=2),encoding='utf-8')
    print('PASS: live rendered review, request status, approval gate, synchronized playback and mobile layout')


if __name__=='__main__':main()
