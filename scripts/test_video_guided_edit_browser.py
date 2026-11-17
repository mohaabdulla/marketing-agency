"""Guided video edit in a real browser, without opening Advanced mode:
source → visible brand guidelines → brief → assistant → settings → real export → what changed → QA → download."""
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

ROOT = Path(__file__).resolve().parents[1]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'


def main():
    with tempfile.TemporaryDirectory(prefix='lexnis-guided-edit-') as folder:
        tmp = Path(folder)
        os.environ['VIDEO_DATA_DIR'] = str(tmp / 'tools')
        sys.path.insert(0, str(ROOT))
        from video_ffmpeg import ffmpeg, probe
        source = tmp / 'original.mp4'
        ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=360x640:r=30000/1001', '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=44100',
                '-t', '4', '-af', 'volume=17dB', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], timeout=60)
        logo = tmp / 'company-logo.png'
        Image.new('RGBA', (200, 80), '#e4572e').save(logo)
        with socket.socket() as probe_socket:
            probe_socket.bind(('127.0.0.1', 0))
            port = probe_socket.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        evidence = ROOT / 'output/video-guided-edit'
        evidence.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, 'PUBLIC_TEST_MODE': 'true', 'PUBLIC_TEST_DATA_DIR': str(tmp / 'guests'), 'VIDEO_DATA_DIR': str(tmp / 'video'),
               'AGENCY_DATA_DIR': str(tmp / 'agency'), 'LOCAL_TEXT_URL': '', 'PYTHONIOENCODING': 'utf-8'}
        with (evidence / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin + '/api/session', timeout=1).ok:
                            break
                    except requests.RequestException:
                        time.sleep(.25)
                    if server.poll() is not None:
                        raise RuntimeError('Server stopped; inspect server.log')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    ctx = browser.new_context(accept_downloads=True, viewport={'width': 1440, 'height': 1000})
                    page = ctx.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('https://**/*', lambda route: route.abort())
                    page.goto(origin + '/?workspace=video&tab=editor', wait_until='domcontentloaded')
                    quick = page.locator('[data-quick-editor]')
                    quick.wait_for(state='visible')

                    # Every step is on the page in order, and none of them is inside a collapsed <details>.
                    steps = quick.locator('section[data-step]').evaluate_all('nodes=>nodes.map(n=>n.dataset.step)')
                    assert steps == ['source', 'brand', 'brief', 'assistant', 'settings', 'preview', 'qa', 'export'], steps
                    assert quick.locator('.ve-steps li').count() == 8
                    brand = quick.locator('section[data-step=brand]')
                    controls = brand.locator('[data-guideline-controls]')
                    controls.wait_for(state='visible')
                    assert controls.evaluate('node=>!node.closest("details")'), 'guideline controls must not be hidden in an optional section'
                    assert brand.get_by_text('Upload / Replace Guidelines').first.is_visible()
                    assert brand.locator('[data-logo-upload]').is_visible()
                    assert quick.locator('section[data-step=assistant] [data-quick-assist-slot]').evaluate('node=>node.children.length>0 && !node.closest("details:not([open])")')
                    assert quick.get_by_text('Brand, purpose & name (optional)').count() == 0
                    presets = quick.locator('[data-quick-delivery] option').evaluate_all('nodes=>nodes.map(n=>n.value)')
                    assert presets == ['source-master', 'web-youtube', 'vertical-social', 'square-social', 'portrait-feed', 'broadcast-ebu'], presets
                    assert quick.locator('[data-quick-delivery]').input_value() == 'web-youtube'
                    note = quick.locator('[data-quick-preset-note]').inner_text()
                    assert 'H.264 High' in note and '-14 LUFS' in note and 'BS.1770' in note, note

                    # Brand step: guideline text and logo, both visible controls.
                    guide = tmp / 'brand.md'
                    guide.write_text('Brand: Noor Solar\nPrimary color: #ffffff\nFonts: Arial\nCTA: Book a demo\n', encoding='utf-8')
                    with page.expect_file_chooser() as chooser:
                        brand.get_by_text('Upload / Replace Guidelines').first.click()
                    chooser.value.set_files(str(guide))
                    page.wait_for_timeout(1500)
                    brand.locator('[data-logo-file]').set_input_files(str(logo))
                    page.wait_for_function("()=>/logo/i.test(document.querySelector('[data-logo-status]')?.textContent||'')", timeout=20000)

                    with page.expect_response(lambda r:r.url.endswith('/api/video/upload') and r.request.method=='POST', timeout=60000) as uploaded:
                        quick.locator('[data-quick-file]').set_input_files(str(source))
                    assert uploaded.value.ok,uploaded.value.text()
                    try:
                        page.wait_for_function("()=>document.querySelector('[data-quick-source]').value.length===32", timeout=30000)
                    except Exception:
                        print('Upload status:',quick.locator('[data-quick-status]').inner_text(),'JS errors:',errors,flush=True)
                        page.screenshot(path=str(evidence/'upload-failure.png'))
                        raise
                    info = quick.locator('[data-quick-source-info]').inner_text()
                    assert '360 × 640' in info and '29.97 fps' in info, info
                    quick.locator('[data-quick-delivery]').select_option('vertical-social')

                    # New settings exist, and the plan preview answers the request without rendering anything.
                    for control in ('style', 'platform', 'lighting', 'background', 'canvas'):
                        assert quick.locator(f'[data-quick-{control}]').count() == 1, control
                    assert quick.locator('[data-quick-capabilities]').inner_text().strip()
                    quick.locator('button[data-quick-plan]').click()
                    page.wait_for_function("()=>/PLAN ONLY/.test(document.querySelector('[data-quick-requests]').textContent)", timeout=240000)
                    planned = quick.locator('[data-quick-requests]').inner_text()
                    assert 'No video has been rendered for this plan' in planned and 'Deterministic editing remains available' in planned, planned
                    assert quick.locator('[data-quick-plan-stills] img').count()==2
                    assert quick.locator('[data-quick-download]').is_hidden(), 'a plan preview must not produce a file'

                    quick.locator('[data-quick-run]').click()
                    quick.locator('[data-quick-download]').wait_for(state='visible', timeout=240000)

                    report = quick.locator('[data-quick-report]').inner_text()
                    assert 'What changed' in report and 'Captions were requested but not created' in report, report
                    for decision in ('TRANSITION', 'AUDIO'):
                        assert decision in report.upper(), report
                    # Two separate gates: technical delivery and editorial quality, with an explicit readiness.
                    gates = {g.split('\n')[0].strip().lower(): g.split('\n')[-1].strip() for g in quick.locator('[data-quick-gates] .ve-gate').all_inner_texts()}
                    assert set(gates) == {'technical delivery qa', 'editorial quality', 'brand', 'caption review', 'publish readiness'}, gates
                    assert gates['publish readiness'] in ('READY', 'DRAFT') and gates['editorial quality'] in ('PASS', 'NEEDS REVIEW'), gates
                    label = quick.locator('[data-quick-download]').inner_text()
                    assert ('draft' in label.lower()) == (gates['publish readiness'] == 'DRAFT'), (label, gates)
                    assert 'no combined score' in quick.locator('[data-quick-gates]').inner_text()
                    assert quick.locator('[data-quick-editorial] details.ve-category').count() >= 5
                    assert 'Your request' in quick.locator('[data-quick-requests]').inner_text()
                    qa = quick.locator('[data-quick-qa]')
                    qa.locator('details').first.evaluate('node=>node.open=true')
                    qa.locator('table').wait_for()
                    text = qa.inner_text()
                    assert 'Vertical social' in text and 'not checked' in text.lower(), text
                    statuses = qa.locator('tbody .ve-qa').evaluate_all('nodes=>nodes.map(n=>n.dataset.status)')
                    assert set(statuses) <= {'PASS', 'WARNING', 'FAIL', 'NOT_CHECKED'} and 'PASS' in statuses
                    rows = {row.split('\t')[1].split('\n')[0]: row.split('\t')[0] for row in qa.locator('tbody tr').all_inner_texts()}
                    assert rows['Frame rate is the intended rate'] == 'PASS', rows
                    assert rows['Rec.709 SDR colour tags written'] == 'PASS', rows
                    assert rows['True peak under the preset ceiling'] == 'PASS', rows
                    assert rows['Captions rendered'] == 'FAIL', rows            # requested, no speech model: reported, not hidden
                    with page.expect_download() as downloaded:
                        quick.locator('[data-quick-download]').click()
                    exported = tmp / 'downloaded.mp4'
                    downloaded.value.save_as(exported)
                    meta = probe(exported)
                    assert meta['fps_rational'] == '30000/1001' and meta['video_profile'] == 'High' and meta['audio_sample_rate'] == 48000, meta
                    assert (meta['width'], meta['height']) == (360, 640), meta           # 9:16 already; never upscaled
                    assert meta['color_primaries'] == 'bt709' and meta['color_transfer'] == 'bt709'
                    quick.locator('[data-quick-original]').click()
                    assert 'Original' in quick.locator('[data-quick-preview-label]').inner_text()
                    quick.locator('section[data-step=qa]').scroll_into_view_if_needed()
                    page.screenshot(path=str(evidence / 'guided-edit-qa.png'))
                    quick.locator('section[data-step=brand]').scroll_into_view_if_needed()
                    page.screenshot(path=str(evidence / 'guided-edit-brand-step.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.wait_for_timeout(400)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), 'no horizontal scrolling on a phone'
                    assert not errors, errors
                    browser.close()
                (evidence / 'result.json').write_text(json.dumps(dict(passed=True, real_render=True, speech_model_used=False,
                    scenario='source → visible guidelines + logo → preset → real export → decisions → measured QA → download'), indent=2))
                print('PASS: guided video edit with visible guidelines, real export, decision list and measured QA')
            finally:
                server.terminate()
                server.wait(timeout=15)


if __name__ == '__main__':
    main()
