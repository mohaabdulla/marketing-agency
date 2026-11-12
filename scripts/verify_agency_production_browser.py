"""Real-server browser scenario for the production workspaces: concept matrix, copy checks,
script → storyboard → Video Studio project, asset registration, version approval, publication
package, CSV metrics, experiment statistics, report and pricing. No AI/provider calls."""
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
import requests
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    picture = ROOT / 'output/renders' / f'agency-browser-{uuid.uuid4().hex}.png'
    picture.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (540, 675), (18, 110, 120)).save(picture)
    with tempfile.TemporaryDirectory(prefix='lexnis-agency-production-browser-') as tmp:
        tmp = Path(tmp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'AGENCY_DATA_DIR': str(tmp / 'agency'), 'VIDEO_DATA_DIR': str(tmp / 'video'), 'PYTHONIOENCODING': 'utf-8'}
        evidence = ROOT / 'output/agency-browser'
        evidence.mkdir(parents=True, exist_ok=True)
        with (evidence / 'production-server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin + '/api/agency/health', timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        time.sleep(.25)
                    if server.poll() is not None:
                        raise RuntimeError('Agency server failed; inspect its log')
                api = origin + '/api/agency'

                def call(method, path, body=None, status=None):
                    response = requests.request(method, api + path, json=body, timeout=20)
                    assert response.status_code == (status or (201 if method == 'POST' else 200)), response.text
                    return response.json()

                client = call('POST', '/clients', dict(name='Noor Solar'))['id']
                prefix = f'/clients/{client}'
                campaign = call('POST', prefix + '/records/campaigns', dict(name='HomeCell launch', data=dict(objective='Introduce HomeCell')))
                call('POST', prefix + '/records/deliverables', dict(name='LinkedIn feed post', campaign_id=campaign['id'], data=dict(platform='LinkedIn')))
                records = lambda kind: call('GET', prefix + f'/records?kind={kind}&limit=100')['items']

                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1500, 'height': 1100}, accept_downloads=True)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))

                    def external(route):
                        if 'lucide' in route.request.url:
                            route.fulfill(body='window.lucide={createIcons(){}};', content_type='application/javascript')
                        else:
                            route.abort()
                    page.route('https://**/*', external)
                    page.add_init_script(f"localStorage.setItem('lexnis.agency.context', JSON.stringify({{client_id:'{client}',project_id:'',campaign_id:'{campaign['id']}',language:'en'}}))")
                    page.goto(origin, wait_until='domcontentloaded')
                    page.wait_for_selector('.agency-context')

                    def nav(label):
                        page.get_by_role('button', name=label, exact=True).click()

                    def area(key):
                        return page.locator(f'#agency-{key}-workspace')

                    def tab(root, label):
                        root.get_by_role('tab', name=label, exact=True).click()
                        page.wait_for_timeout(250)

                    def new(root, name):
                        root.locator('[data-new]').click()
                        root.locator('[data-form]').wait_for()
                        root.locator('[name=record_name]').fill(name)

                    def status(root, text, timeout=20000):
                        page.wait_for_function("([id,text])=>document.querySelector(id+' .ag-status').textContent.includes(text)",
                                               arg=['#' + root.get_attribute('id'), text], timeout=timeout)

                    def save(root):
                        root.locator('[data-form] button[type=submit]').click()
                        status(root, 'Saved ·')

                    # ---- Content Studio: concept matrix
                    nav('Content Studio')
                    root = area('content')
                    root.locator('[data-matrix]').click()
                    root.locator('[data-axis=hook_type]').fill('authority\ncuriosity')
                    root.locator('[data-axis=cta]').fill('Book a consultation')
                    root.locator('[data-matrix-form] button[type=submit]').click()
                    root.get_by_text('2 proposed concepts created').wait_for()
                    assert len(records('concepts')) == 2

                    # ---- copy variant with the channel registry and deterministic checks
                    tab(root, 'Copy variants')
                    new(root, 'LinkedIn A')
                    assert root.locator('[data-field=format] option').count() >= 20
                    root.locator('[data-field=format]').select_option('x_post')
                    root.locator('[data-field=text]').fill('Save 45% with [PRODUCT] today. ' + 'More words here. ' * 20)
                    save(root)
                    root.locator('[data-copy-checks]').click()
                    result = root.locator('[data-result]')
                    result.get_by_text('Must fix').first.wait_for()
                    text = result.inner_text()
                    assert 'Placeholder text' in text and '280' in text and 'unsubstantiated number: 45%' in text, text
                    root.locator('[data-field=format]').select_option('linkedin_post')
                    root.locator('[data-field=text]').fill('Keep your villa powered through every summer peak.')
                    root.locator('[data-field=cta]').fill('Book a consultation')
                    save(root)
                    root.locator('[data-copy-checks]').click()
                    root.locator('[data-result]').get_by_text('Checks Passed').wait_for()
                    copy = records('copy')[0]

                    # ---- script with nested scenes → estimate → storyboard → Video Studio project
                    tab(root, 'Scripts')
                    new(root, 'Launch film')
                    for index, (narration, on_screen) in enumerate([('word ' * 50, 'Meet HomeCell'), ('word ' * 25, '')]):
                        root.locator('[data-add-row=scenes]').click()
                        scene = root.locator('[data-nested=scenes] [data-row]').nth(index)
                        scene.locator('[data-sub=narration]').fill(narration)
                        scene.locator('[data-sub=on_screen_text]').fill(on_screen)
                        scene.locator('[data-sub=visual]').fill(f'Scene {index + 1} picture')
                    save(root)
                    computed = root.locator('.ag-computed').inner_text()
                    assert '75' in computed and 'Estimate: 150 spoken words per minute' in computed, computed
                    script = call('GET', prefix + '/record/' + records('scripts')[0]['id'])
                    assert len(script['data']['scenes']) == 2 and script['computed']['estimated_seconds'] == 30.0
                    root.locator('[data-add-row=scenes]').click()
                    assert root.locator('[data-nested=scenes] [data-row]').count() == 3
                    root.locator('[data-nested=scenes] [data-row]').nth(2).locator('[data-remove-row]').click()
                    assert root.locator('[data-nested=scenes] [data-row]').count() == 2
                    root.locator('[data-make-board]').click()
                    status(root, 'Storyboard created with 2 shot')
                    root.locator('[data-shot-list]').click()
                    root.locator('[data-result] table').wait_for()
                    assert root.locator('[data-result] .ag-strip span').count() == 2
                    root.locator('[data-video-project]').click()
                    root.locator('[data-result]').get_by_text('Video project created').wait_for(timeout=30000)
                    projects = list((tmp / 'video/projects').glob('*.json'))
                    assert len(projects) == 1
                    clips = json.loads(projects[0].read_text(encoding='utf-8'))['clips']
                    assert [c['kind'] for c in clips].count('video') == 2 and any(c['kind'] == 'title' and c['text'] == 'Meet HomeCell' for c in clips)
                    with page.expect_download() as exported:
                        root.locator('[data-board-export]').click()
                    with zipfile.ZipFile(exported.value.path()) as bundle:
                        assert 'storyboard.html' in bundle.namelist()

                    # ---- asset registration (as if sent from Image Studio) and version-specific approval
                    page.evaluate("(url)=>{window.dispatchEvent(new CustomEvent('lexnis:agency-asset',{detail:{media_url:url,origin:'generated'}}));window.dispatchEvent(new CustomEvent('lexnis:workspace',{detail:{name:'agency-assets'}}));}", '/renders/' + picture.name)
                    root = area('assets')
                    form = root.locator('[data-register]')
                    form.wait_for()
                    assert form.locator('[name=media_url]').input_value() == '/renders/' + picture.name
                    form.locator('[name=name]').fill('Launch hero')
                    form.locator('button[type=submit]').click()
                    status(root, 'Registered · checksum')
                    preview = root.locator('.ag-preview')
                    preview.wait_for()
                    page.wait_for_function("()=>document.querySelector('#agency-assets-workspace .ag-preview').naturalWidth===540")
                    assert root.locator('[data-field=sha256]').count() == 0          # file facts are not editable
                    asset = call('GET', prefix + '/record/' + records('assets')[0]['id'])
                    assert asset['data']['origin'] == 'generated' and asset['campaign_id'] == campaign['id']
                    root.locator('[data-reviewer]').fill('Sara')
                    root.locator('[data-request-approval]').click()
                    status(root, 'Review requested for v1')
                    tab(root, 'Approvals')
                    assert root.locator('[data-new]').is_disabled()
                    root.locator('[data-open]').first.click()
                    review = root.locator('[data-review]')
                    review.wait_for()
                    review.locator('[name=text]').fill('Logo placement is fine.')
                    review.locator('[data-act=approved]').click()
                    root.locator('.ag-state[data-state=approved]').wait_for()
                    assert call('GET', prefix + f'/record/{asset["id"]}/approval-state')['state'] == 'approved'

                    # ---- calendar entry: final package is refused until rights and copy approval exist
                    nav('Calendar & Publishing')
                    root = area('publishing')
                    new(root, 'Launch post')
                    root.locator('[data-field=channel]').fill('LinkedIn')
                    root.locator('[data-field=scheduled_date]').fill('2030-02-01')
                    root.locator('[data-field=copy_id]').select_option(copy['id'])
                    root.locator('[data-field=asset_ids]').select_option(asset['id'])
                    root.locator('[data-field=alt_text]').fill('A villa at dusk')
                    save(root)
                    root.locator('[data-package-final]').click()
                    status(root, 'Not ready for a final package')
                    assert root.locator('.ag-status').get_attribute('data-error') == 'true'
                    with page.expect_download() as draft:
                        root.locator('[data-package-draft]').click()
                    with zipfile.ZipFile(draft.value.path()) as bundle:
                        assert json.loads(bundle.read('metadata.json'))['cleared'] is False
                    licence = call('POST', prefix + '/records/licenses', dict(name='Generated in-house', data=dict(license_type='generated')))
                    asset = call('PUT', prefix + f'/records/assets/{asset["id"]}', dict(name=asset['name'], campaign_id=campaign['id'], expected_version=asset['version'],
                                                                                       data=dict(asset['data'], license_id=licence['id'])))
                    for target in (asset, call('GET', prefix + '/record/' + copy['id'])):
                        request = call('POST', prefix + '/approvals', dict(target_id=target['id'], reviewer='Sara'))
                        call('POST', prefix + f'/approvals/{request["id"]}/decision', dict(expected_version=request['version'], decision='approved', reviewer='Sara'), 200)
                    with page.expect_download() as final:
                        root.locator('[data-package-final]').click()
                    assert 'DRAFT' not in final.value.suggested_filename
                    with zipfile.ZipFile(final.value.path()) as bundle:
                        meta = json.loads(bundle.read('metadata.json'))
                        assert meta['cleared'] and not meta['publishes_externally']
                        assert bundle.read(meta['media'][0]['file']) == picture.read_bytes()
                        assert bundle.read('caption.txt').decode('utf-8').startswith('Keep your villa powered')
                    root.locator('[data-schedule]').click()
                    root.get_by_text('Week of 2030-01-28').wait_for()

                    # ---- analytics: definition, CSV import, KPI summary, experiment statistics
                    nav('Analytics & Experiments')
                    root = area('analytics')
                    new(root, 'Clicks')
                    root.locator('[data-field=unit]').fill('clicks')
                    save(root)
                    tab(root, 'Metric values')
                    root.locator('[data-metrics-csv]').set_input_files({'name': 'clicks.csv', 'mimeType': 'text/csv',
                        'buffer': b'date,metric,value,channel\n2030-03-01,Clicks,120,LinkedIn\n2030-03-15,Clicks,180,LinkedIn\n'})
                    status(root, 'Imported 2 values')
                    tab(root, 'Metric definitions')
                    root.locator('[data-kpi]').click()
                    row = root.locator('[data-editor] table tbody tr').first
                    row.wait_for()
                    summary = row.inner_text()
                    assert '120' in summary and '180' in summary and '+60 (50.0%)' in summary and '300' in summary, summary
                    assert root.locator('.ag-spark polyline').count() == 1
                    tab(root, 'Experiments')
                    new(root, 'Hook test')
                    root.locator('[data-field=hypothesis]').fill('A curiosity hook lifts clicks')
                    for index, (label, control, conversions) in enumerate([('Control', True, '100'), ('Curiosity', False, '130')]):
                        root.locator('[data-add-row=variants]').click()
                        variant = root.locator('[data-nested=variants] [data-row]').nth(index)
                        variant.locator('[data-sub=label]').fill(label)
                        if control:
                            variant.locator('[data-sub=is_control]').check()
                        variant.locator('[data-sub=sample_size]').fill('1000')
                        variant.locator('[data-sub=conversions]').fill(conversions)
                    save(root)
                    computed = root.locator('.ag-computed').inner_text()
                    assert 'P Value' in computed and '0.0355' in computed and 'Two-sided two-proportion z-test' in computed, computed
                    experiment = records('experiments')[0]
                    metric = records('metrics')[0]

                    # ---- report rendered from stored values
                    nav('Reports & Learnings')
                    root = area('reports')
                    new(root, 'March report')
                    root.locator('[data-field=period_start]').fill('2030-03-01')
                    root.locator('[data-field=period_end]').fill('2030-03-31')
                    root.locator('[data-field=metric_ids]').select_option(metric['id'])
                    root.locator('[data-field=experiment_ids]').select_option(experiment['id'])
                    root.locator('[data-field=executive_summary]').fill('A steady first month.')
                    save(root)
                    with page.expect_download() as rendered:
                        root.locator('[data-render-report]').click()
                    with zipfile.ZipFile(rendered.value.path()) as bundle:
                        report_page = bundle.read('report.html').decode('utf-8')
                    assert 'Clicks increased from 120 clicks on 2030-03-01 to 180 clicks on 2030-03-15 (+50.0%).' in report_page
                    (evidence / 'production-report.html').write_text(report_page, encoding='utf-8')

                    # ---- operations: pricing arithmetic shown read-only
                    nav('Operations')
                    root = area('operations')
                    tab(root, 'Pricing scenarios')
                    new(root, 'Retainer')
                    for field, value in (('internal_hourly_cost', '20'), ('expected_hours', '100'), ('monthly_retainer', '1500'), ('retainer_months', '3'), ('target_margin_percent', '50')):
                        root.locator(f'[data-field={field}]').fill(value)
                    save(root)
                    computed = root.locator('.ag-computed').inner_text()
                    assert '4,500' in computed and '2,000' in computed and '55.56' in computed, computed
                    tab(root, 'Tasks')
                    root.get_by_text('No records yet').wait_for()

                    # ---- dashboard overview, RTL and mobile
                    nav('Dashboard')
                    overview = area('dashboard').locator('[data-overview]')
                    overview.get_by_text('Upcoming content').wait_for()
                    assert 'work in progress' in overview.inner_text()
                    page.locator('#agency-context-language').select_option('ar')
                    nav('Content Studio')
                    page.wait_for_function("()=>document.querySelector('#agency-content-workspace .ag').dir==='rtl'")
                    page.screenshot(path=str(evidence / 'production-desktop.png'), full_page=False)
                    mobile = browser.new_page(viewport={'width': 390, 'height': 844})
                    mobile.on('pageerror', lambda error: errors.append(str(error)))
                    mobile.route('https://**/*', external)
                    mobile.add_init_script(f"localStorage.setItem('lexnis.agency.context', JSON.stringify({{client_id:'{client}',project_id:'',campaign_id:'{campaign['id']}',language:'en'}}))")
                    mobile.goto(origin, wait_until='domcontentloaded')
                    for label, key in (('Content Studio', 'content'), ('Assets & Approvals', 'assets'), ('Analytics & Experiments', 'analytics')):
                        mobile.locator('.studio-mobile-toggle').click()
                        mobile.get_by_role('button', name=label, exact=True).click()
                        mobile.wait_for_selector(f'#agency-{key}-workspace h1')
                        mobile.wait_for_timeout(400)
                        assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth'), label
                    mobile.screenshot(path=str(evidence / 'production-mobile.png'), full_page=True)
                    assert not errors, errors
                    browser.close()
                (evidence / 'production-result.json').write_text(json.dumps(dict(
                    passed=True, real_ai_inference=False,
                    scenario='concept matrix → copy checks → script → storyboard → Video Studio project → asset registration → version approval '
                             '→ publication package → CSV metrics → experiment statistics → report → pricing → dashboard'), indent=2))
                print('PASS: production workspaces in a real browser (content, assets, approvals, publication package, analytics, report, pricing, RTL, mobile)')
            finally:
                server.terminate()
                server.wait(timeout=15)
                picture.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
