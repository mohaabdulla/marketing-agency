"""Browser interaction smoke test with deterministic API responses, no external AI calls."""
import json
import io
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from PIL import Image

html = (Path(__file__).resolve().parents[1] / 'index.html').read_text(encoding='utf-8')
campaign = dict(hook='Take the scenic route.', caption='Explore the coast.', highlights=[],
    hashtags='#Tesla', visual_prompt='Blue Tesla Model 3 on a coastal road at sunset',
    image_url='', clean_image_url='', image_status='unavailable', warnings=['Configure an image provider.'],
    seed=42, brand='Tesla', image_headline='TESLA MODEL 3', raw_response='{}')
sample = io.BytesIO()
Image.new('RGB', (640, 360), '#526b82').save(sample, format='JPEG')

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
            request.fulfill(json={'status': 'online', 'image_models': {'cf:flux-schnell': 'FLUX Schnell', 'local:realvisxl-v5': 'RealVisXL 5 — photographic detail'}, 'default_image_model': 'cf:flux-schnell',
                'image_model_setup': {'cf:flux-schnell': {'configured': False, 'message': 'Set Cloudflare credentials'},
                                      'local:realvisxl-v5': {'configured': True, 'message': 'Local GPU verified'}}})
        elif url.endswith('/api/generate'):
            assert request.request.post_data_json['output_format'] == 'landscape'
            request.fulfill(json=campaign)
        elif url.endswith('/api/render'):
            assert request.request.post_data_json['output_format'] == 'landscape'
            if request.request.post_data_json['image_model'] == 'local:realvisxl-v5':
                request.fulfill(json={'image_status': 'ready', 'warnings': [], 'image_url': '/renders/test-photo.jpg',
                    'clean_image_url': '/renders/test-photo.jpg', 'watermark_free': True})
            else:
                request.fulfill(json={'image_status': 'unavailable', 'warnings': ['Provider unavailable']})
        elif url.endswith('/renders/test-photo.jpg'):
            request.fulfill(body=sample.getvalue(), content_type='image/jpeg')
        elif url.endswith('/api/export'):
            assert request.request.post_data_json['image_url'] == ''
            request.fulfill(json={'status': 'success', 'files': {'caption': 'output/caption.txt'}})
        elif 'lucide' in url:
            request.fulfill(body='window.lucide={createIcons(){}};', content_type='application/javascript')
        elif urlsplit(url).path.startswith('/static/'):
            # Serve real versioned CSS and isolated workspace modules; keep all assertions below.
            asset = Path(__file__).resolve().parents[1] / urlsplit(url).path.lstrip('/')
            content_type = 'text/css' if asset.suffix == '.css' else 'application/javascript'
            request.fulfill(body=asset.read_bytes(), content_type=content_type)
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
    page.locator('#image-model-select').select_option('local:realvisxl-v5')
    page.wait_for_function('currentImageStatus === "ready" && document.getElementById("result-image").naturalWidth > 0')
    assert not page.locator('#download-image-btn').is_disabled()
    assert not page.locator('#visual-unavailable').is_visible()
    assert page.locator('#current-model-badge').inner_text() == 'RealVisXL 5'
    assert page.locator('#campaign-warnings').inner_text() == ''
    assert not errors, errors
    print('Browser smoke passed: compiled CSS, campaign, setup errors, copy export, photographic model selection, loaded image, no JavaScript errors.')
    browser.close()
