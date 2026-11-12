"""Real browser: HTML audit, editable RTL page, ZIP, contacts, consent and email export."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
import wave
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'output/agency-browser'


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lexnis-acquisition-browser-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'AGENCY_DATA_DIR': str(Path(folder) / 'agency'), 'VIDEO_DATA_DIR': str(Path(folder) / 'video'), 'PYTHONIOENCODING': 'utf-8'}
        with (EVIDENCE / 'acquisition-server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(160):
                    try:
                        if requests.get(origin + '/api/agency/health', timeout=1).ok:
                            break
                    except requests.RequestException:
                        time.sleep(.25)
                    if server.poll() is not None:
                        raise RuntimeError('Preview server stopped')
                client_response = requests.post(origin + '/api/agency/clients', json={'name': 'Noor acquisition'}, timeout=10)
                client_response.raise_for_status()
                client = client_response.json()['id']
                response = requests.post(origin + '/api/agency/clients/' + client + '/records/campaigns',
                                         json=dict(name='Launch', data=dict(objective='Introduce solar')), timeout=10)
                response.raise_for_status()
                campaign = response.json()['id']
                audio_file = ROOT / 'output/renders' / ('browser-audio-' + client + '.wav')
                with wave.open(str(audio_file), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(b'\0\0' * 32000)
                response = requests.post(origin + '/api/agency/clients/' + client + '/assets/register',
                                         json=dict(media_url='/renders/' + audio_file.name, origin='owned'), timeout=10)
                response.raise_for_status()
                audio_asset = response.json()['id']
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1500, 'height': 1080}, accept_downloads=True)
                    errors = []
                    page.on('pageerror', lambda err: errors.append(str(err)))
                    page.route('https://**/*', lambda route: route.abort())
                    page.add_init_script("if(window===window.top)localStorage.setItem('lexnis.agency.context',JSON.stringify(" + json.dumps(dict(client_id=client, project_id='', campaign_id=campaign, language='en')) + "))")
                    page.goto(origin, wait_until='domcontentloaded')
                    page.wait_for_selector('.agency-context')
                    def nav(label, key):
                        page.get_by_role('button', name=label, exact=True).click()
                        root = page.locator('#agency-' + key + '-workspace')
                        root.locator('[data-new]').wait_for()
                        return root
                    def tab(root, label):
                        root.get_by_role('tab', name=label, exact=True).click()
                        root.locator('[data-new]').click()
                        root.locator('[data-form]').wait_for()
                    def fill(root, key, value):
                        root.locator('[data-field="' + key + '"]').fill(value)
                    def save(root, name):
                        root.locator('[name=record_name]').fill(name)
                        root.locator('[data-form] button[type=submit]').click()
                        page.wait_for_function("id=>document.querySelector(id+' .ag-status').textContent.includes('Saved ·')",
                                               arg='#' + root.get_attribute('id'))
                    root = nav('SEO & Landing Pages', 'web')
                    tab(root, 'HTML audits')
                    fill(root, 'page_url', 'https://example.com/solar')
                    fill(root, 'html', '<title>Noor Solar</title><h1>Solar systems</h1><img src="panel.jpg">')
                    save(root, 'Solar HTML')
                    root.locator('[data-inspect-html]').click()
                    root.locator('[data-acquisition-result]').get_by_text('Images without alt attributes', exact=False).wait_for()
                    tab(root, 'Landing pages')
                    fill(root, 'title', 'مرحبا بكم')
                    root.locator('[data-field=language]').select_option('ar')
                    fill(root, 'canonical_url', 'https://example.com/solar')
                    root.locator('[data-add-row=blocks]').click()
                    root.locator('[data-sub=kind]').select_option('hero')
                    root.locator('[data-sub=heading]').fill('مرحبا بكم')
                    root.locator('[data-sub=text]').fill('حلول الطاقة الشمسية')
                    save(root, 'Arabic launch page')
                    root.locator('[data-preview-page]').click()
                    frame = root.frame_locator('iframe')
                    frame.get_by_role('heading', name='مرحبا بكم').wait_for()
                    assert frame.locator('html').get_attribute('dir') == 'rtl'
                    with page.expect_download() as download:
                        root.locator('[data-export-page]').click()
                    downloaded = Path(folder) / 'landing.zip'
                    download.value.save_as(downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        assert 'sitemap.xml' in archive.namelist()
                        assert 'dir="rtl"' in archive.read('index.html').decode()
                    root = nav('Email & CRM', 'crm')
                    tab(root, 'Contacts')
                    fill(root, 'email', 'customer@example.com')
                    fill(root, 'source', 'Signed form')
                    root.locator('[data-field=consent_status]').select_option('granted')
                    fill(root, 'consent_purpose', 'News')
                    fill(root, 'consent_evidence', 'Form receipt 123')
                    save(root, 'Customer')
                    assert root.locator('[data-editor]').get_by_text('Consent recorded:', exact=False).count() == 1
                    tab(root, 'Segments')
                    fill(root, 'purpose', 'News')
                    save(root, 'Newsletter')
                    root.locator('[data-preview-segment]').click()
                    page.wait_for_function("()=>document.querySelector('#agency-crm-workspace [data-acquisition-result]')?.textContent.includes('\"eligible\": 1')")
                    tab(root, 'Email templates')
                    fill(root, 'subject', 'Welcome')
                    fill(root, 'body', 'Welcome to Noor Solar.')
                    save(root, 'Welcome email')
                    root.locator('[data-preview-email]').click()
                    root.frame_locator('iframe').get_by_role('heading', name='Welcome').wait_for()
                    with page.expect_download() as download:
                        root.locator('[data-export-email]').click()
                    downloaded = Path(folder) / 'email.zip'
                    download.value.save_as(downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        assert 'email.txt' in archive.namelist()
                        assert 'Missing unsubscribe URL' in archive.read('checks.json').decode()
                    page.screenshot(path=str(EVIDENCE / 'acquisition-desktop.png'))
                    root = nav('Paid Media Planning', 'paid')
                    tab(root, 'Ad plans')
                    fill(root, 'objective', 'Introduce solar')
                    fill(root, 'daily_budget', '10')
                    fill(root, 'days', '30')
                    fill(root, 'assumed_cpc', '2')
                    fill(root, 'assumed_conversion_percent', '10')
                    fill(root, 'destination_url', 'https://example.com/solar')
                    fill(root, 'utm_campaign', 'solar launch')
                    save(root, 'Paid plan')
                    root.locator('[data-paid-scenario]').click()
                    page.wait_for_function("()=>document.querySelector('#agency-paid-workspace [data-acquisition-result]')?.textContent.includes('\"planned_external_ad_spend\": 300')")
                    with page.expect_download() as download:
                        root.locator('[data-export-plan]').click()
                    downloaded = Path(folder) / 'plan.zip'
                    download.value.save_as(downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        assert 'plan.csv' in archive.namelist()
                    root = nav('Creators & UGC', 'creators')
                    tab(root, 'Creators')
                    fill(root, 'handle', '@client-provided')
                    save(root, 'Public creator')
                    tab(root, 'Creator briefs')
                    root.locator('[data-field=creator_id]').select_option(label='Public creator')
                    fill(root, 'disclosure_text', 'Paid partnership')
                    save(root, 'Creator launch brief')
                    root = nav('Content Studio', 'content')
                    tab(root, 'Content pillars')
                    fill(root, 'purpose', 'Answer customer questions')
                    save(root, 'Solar education')
                    tab(root, 'Content series')
                    root.locator('[data-field=pillar_id]').select_option(label='Solar education')
                    fill(root, 'recurring_concept', 'One solar question each week')
                    save(root, 'Weekly solar answers')
                    root = nav('Audio & Subtitles', 'audio')
                    tab(root, 'Audio projects')
                    root.locator('[data-field=asset_id]').select_option(audio_asset)
                    fill(root, 'start_seconds', '0.25')
                    fill(root, 'end_seconds', '1.25')
                    save(root, 'Processed voiceover')
                    root.locator('[data-render-audio]').click()
                    root.get_by_role('link', name='Download processed audio').wait_for(timeout=20000)
                    tab(root, 'Subtitles')
                    root.locator('[data-field=language]').select_option('ar')
                    root.locator('[data-add-row=cues]').click()
                    root.locator('[data-sub=start_seconds]').fill('0')
                    root.locator('[data-sub=end_seconds]').fill('1.25')
                    root.locator('[data-sub=text]').fill('مرحبا بكم')
                    save(root, 'Arabic captions')
                    with page.expect_download() as download:
                        root.locator('[data-subtitle-srt]').click()
                    downloaded = Path(folder) / 'captions.srt'
                    download.value.save_as(downloaded)
                    assert '00:00:01,250' in downloaded.read_text(encoding='utf-8')
                    root = nav('Privacy & Retention', 'privacy')
                    tab(root, 'Retention policy')
                    fill(root, 'review_after_days', '30')
                    save(root, 'Client retention')
                    root.locator('[data-retention-review]').click()
                    root.locator('[data-acquisition-result]').wait_for()
                    with page.expect_download() as download:
                        root.locator('[data-client-export]').click()
                    downloaded = Path(folder) / 'client-data.zip'
                    download.value.save_as(downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        assert 'client-data.json' in archive.namelist()
                    root.locator('[data-erase-preview]').click()
                    root.locator('[data-erasure-phrase]').wait_for()
                    assert root.locator('[data-erase-client]').is_disabled()
                    root.locator('[data-erasure-phrase]').fill('incorrect')
                    assert root.locator('[data-erase-client]').is_disabled()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(EVIDENCE / 'acquisition-mobile.png'), full_page=True)
                    # Exercise actual erasure only against this isolated temporary test client.
                    root.locator('[data-erasure-phrase]').fill('DELETE CLIENT ' + client)
                    root.locator('[data-erase-client]').click()
                    page.locator('[data-privacy-result]').wait_for()
                    page.wait_for_function("()=>document.querySelector('#agency-context-client').value===''");
                    assert 'Prior backups' in page.locator('[data-privacy-result]').inner_text()
                    assert requests.get(origin + '/api/agency/clients/' + client, timeout=10).status_code == 404
                    assert audio_file.is_file(), 'Independent source media must remain outside client erasure'
                    page.screenshot(path=str(EVIDENCE / 'privacy-erased.png'), full_page=True)
                    assert not errors, errors
                    browser.close()
                (EVIDENCE / 'acquisition-result.json').write_text(json.dumps(dict(passed=True, scenario='HTML audit → RTL page/ZIP → consent → email kit → paid/creator/organic plans → audio render → subtitles → privacy export/review → mobile', real_ai_inference=False), ensure_ascii=False, indent=2), encoding='utf-8')
                print('PASS: SEO, RTL page, CRM/email, paid/creator/organic plans, audio, subtitles, privacy and mobile browser')
            finally:
                server.terminate()
                server.wait(timeout=15)
                if 'audio_file' in locals():
                    audio_file.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
