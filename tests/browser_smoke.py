"""Browser interaction smoke test with deterministic API responses, no external AI calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

html = (Path(__file__).resolve().parents[1] / 'index.html').read_text(encoding='utf-8')
campaign = dict(hook='Take the scenic route.', caption='Explore the coast.', highlights=[],
    hashtags='#Tesla', visual_prompt='Blue Tesla Model 3 on a coastal road at sunset',
    image_url='', clean_image_url='', image_status='unavailable', warnings=['Configure an image provider.'],
    seed=42, brand='Tesla', image_headline='TESLA MODEL 3', raw_response='{}')

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def route(request):
        url = request.request.url
        if url == 'http://agency.test/':
            request.fulfill(body=html, content_type='text/html')
        elif url.endswith('/api/health'):
            request.fulfill(json={'status': 'online', 'image_models': {'cf:flux-schnell': 'FLUX Schnell'}, 'default_image_model': 'cf:flux-schnell',
                'image_model_setup': {'cf:flux-schnell': {'configured': False, 'message': 'Set Cloudflare credentials'}}})
        elif url.endswith('/api/generate'):
            assert request.request.post_data_json['output_format'] == 'landscape'
            request.fulfill(json=campaign)
        elif url.endswith('/api/render'):
            assert request.request.post_data_json['output_format'] == 'landscape'
            request.fulfill(json={'image_status': 'unavailable', 'warnings': ['Provider unavailable']})
        elif url.endswith('/api/export'):
            assert request.request.post_data_json['image_url'] == ''
            request.fulfill(json={'status': 'success', 'files': {'caption': 'output/caption.txt'}})
        elif 'lucide' in url:
            request.fulfill(body='window.lucide={createIcons(){}};', content_type='application/javascript')
        elif url.endswith('/static/tailwind.css'):
            request.fulfill(body=(Path(__file__).resolve().parents[1] / 'static/tailwind.css').read_text(), content_type='text/css')
        else:
            request.fulfill(body='', content_type='text/plain')

    page.route('**/*', route)
    page.goto('http://agency.test/')
    assert page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(7, 9, 14)'
    page.wait_for_function('isPythonBackendActive === true')
    page.locator('#prompt-input').fill('Blue Tesla Model 3 coastal sunset campaign')
    page.locator('#generate-btn').click()
    page.wait_for_function('document.getElementById("copy-hook").textContent === "Take the scenic route."')
    assert page.locator('#copy-hook').inner_text() == campaign['hook']
    assert page.locator('#campaign-warnings').inner_text() == campaign['warnings'][0]
    assert page.locator('#download-image-btn').is_disabled()
    assert page.locator('#visual-unavailable').is_visible()
    assert page.locator('#reroll-image-btn').is_disabled()
    assert page.locator('#watermark-warning').inner_text() == 'Set Cloudflare credentials'
    assert page.locator('#current-model-badge').inner_text() == 'FLUX Schnell'
    # A configured provider may still exhaust its quota. It should show the
    # expected unavailable state without a JavaScript exception or stuck loader.
    page.evaluate("imageModelSetup['cf:flux-schnell'].configured = true; updateModelSetup()")
    page.locator('#reroll-image-btn').click()
    page.wait_for_function('document.getElementById("campaign-warnings").textContent === "Provider unavailable"')
    assert 'opacity-0' in page.locator('#image-loader').get_attribute('class')
    page.locator('#export-disk-btn').click()
    page.wait_for_function('document.getElementById("export-disk-btn").disabled === false')
    assert not errors, errors
    print('Browser smoke passed: compiled CSS, campaign, missing setup, unavailable render, copy-only export, no JavaScript errors.')
    browser.close()
