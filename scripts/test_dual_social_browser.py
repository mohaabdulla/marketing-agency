"""Browser verification of carousel previews, language switching and ZIP download."""
import io
import zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "static/assets"
campaign = dict(hook="Build what comes next.", caption="Join the engineering team.", highlights=[],
                hashtags="#LexnisCareers", visual_prompt="Computer vision research lab", seed=7,
                brand="Lexnis", image_headline="BUILD THE FUTURE", raw_response="{}", image_status="ready",
                output_format="portrait", post_type="hiring", watermark_free=True,
                image_url="/renders/lexnis_hiring_en.jpg", arabic_image_url="/renders/lexnis_hiring_ar.jpg",
                companion_image_url="/renders/lexnis_hiring_en_companion.jpg",
                arabic_companion_image_url="/renders/lexnis_hiring_ar_companion.jpg",
                animation_url="/renders/lexnis_hiring_en_anim.gif", arabic_animation_url="/renders/lexnis_hiring_ar_anim.gif")
campaign["carousel_urls"] = [campaign["image_url"], campaign["companion_image_url"], campaign["animation_url"]]
campaign["arabic_carousel_urls"] = [campaign["arabic_image_url"], campaign["arabic_companion_image_url"], campaign["arabic_animation_url"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 1100}, accept_downloads=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(route):
        url = route.request.url
        if url == "http://agency.test/":
            route.fulfill(body=(ROOT / "index.html").read_text(encoding="utf-8"), content_type="text/html")
        elif url.endswith("/api/health"):
            route.fulfill(json={"status": "online", "image_models": {"cf:flux-schnell": "FLUX Schnell"},
                                "default_image_model": "cf:flux-schnell", "image_model_setup": {"cf:flux-schnell": {"configured": True}}})
        elif url.endswith("/api/generate"):
            route.fulfill(json=campaign)
        elif url.endswith("/api/carousel/download"):
            urls = route.request.post_data_json["urls"]
            assert len(urls) == 3 and all("_ar" in u for u in urls)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for i, url in enumerate(urls, 1):
                    z.writestr(f"slide_{i:02}{Path(url).suffix}", (ASSETS / Path(url).name).read_bytes())
            route.fulfill(body=buf.getvalue(), content_type="application/zip")
        elif "/renders/" in url:
            route.fulfill(body=(ASSETS / url.rsplit("/", 1)[1]).read_bytes(), content_type="image/gif" if url.endswith(".gif") else "image/jpeg")
        elif "/static/tailwind.css" in url:
            route.fulfill(body=(ROOT / "static/tailwind.css").read_bytes(), content_type="text/css")
        elif "lucide" in url:
            route.fulfill(body="window.lucide={createIcons(){}};", content_type="application/javascript")
        else:
            route.fulfill(body="", content_type="text/plain")

    page.route("**/*", route)
    page.goto("http://agency.test/", wait_until="domcontentloaded")
    page.wait_for_function("isPythonBackendActive === true")
    page.locator("#prompt-input").fill("Hiring a computer vision engineer for Lexnis")
    page.locator("#generate-btn").click()
    preview = page.locator("#carousel-preview")
    preview.wait_for(state="visible")
    page.wait_for_function("document.querySelectorAll('#carousel-preview img').length === 3 && [...document.querySelectorAll('#carousel-preview img')].every(i => i.naturalWidth === 1080)")
    assert preview.get_by_text("Card 1: Primary Graphic").is_visible()
    assert preview.get_by_text("Card 2: Topic Companion").is_visible()
    assert preview.get_by_text("Card 3: Animated Social Loop (GIF)").is_visible()
    assert page.locator("#dual-visual-container").is_hidden(), page.evaluate("({css:document.getElementById('dual-visual-container').className, mode:currentVisualMode, paired:currentCarouselData?.carousel_urls, errors:[]})")
    boxes = [el.bounding_box() for el in preview.locator("img").all()]
    assert boxes[0]["x"] + boxes[0]["width"] < boxes[1]["x"], boxes
    assert boxes[1]["x"] + boxes[1]["width"] < boxes[2]["x"], boxes
    preview.get_by_label("Carousel language").select_option("ar")
    assert "_ar_companion" in preview.locator("img").nth(1).get_attribute("src")
    with page.expect_download() as info:
        preview.get_by_role("button", name="Download Complete Kit (.zip)", exact=True).click()
    download = info.value
    assert download.suggested_filename == "campaign-social-kit-ar.zip"
    with zipfile.ZipFile(download.path()) as z:
        assert z.namelist() == ["slide_01.jpg", "slide_02.jpg", "slide_03.gif"]
    with page.expect_download() as info:
        preview.get_by_role("button", name="Download GIF", exact=True).click()
    assert info.value.suggested_filename.endswith('.gif')
    assert Path(info.value.path()).read_bytes()[:6] == b'GIF89a'
    with page.expect_download() as info:
        preview.get_by_role("button", name="Download Static Card 2", exact=True).click()
    assert info.value.suggested_filename.endswith('.jpg')
    page.locator("#visual-tab-ar").click()
    assert "_ar_companion" in preview.locator("img").nth(1).get_attribute("src")
    assert "_ar_anim.gif" in preview.locator("img").nth(2).get_attribute("src")
    page.set_viewport_size({"width": 390, "height": 844})
    preview.scroll_into_view_if_needed()
    boxes = [el.bounding_box() for el in preview.locator("img").all()]
    assert boxes[1]["y"] >= boxes[0]["y"] + boxes[0]["height"], boxes
    assert boxes[2]["y"] >= boxes[1]["y"] + boxes[1]["height"], boxes
    assert not errors, errors
    print("Browser social-kit checks passed: three cards, responsive layout, Arabic switch, GIF/static downloads and complete ZIP.")
    browser.close()
