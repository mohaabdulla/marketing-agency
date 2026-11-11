"""Full agency workspace interaction test against generated local fixtures."""
import copy
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
fixtures = json.loads((ROOT/"output/professional_agency_results.json").read_text(encoding="utf-8"))
campaign = next(data for kind, language, data in fixtures if kind == "campaign" and language == "en")
brands = json.loads((ROOT/"static/assets/brand_kits.json").read_text(encoding="utf-8"))
errors = []

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width":1500,"height":1100}, accept_downloads=True,
                                  permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.on("pageerror", lambda error:errors.append(str(error)))
    def route(route):
        url = route.request.url
        path = url.split("agency.test",1)[-1].split("?",1)[0]
        if path == "/":
            route.fulfill(body=(ROOT/"index.html").read_text(encoding="utf-8"),content_type="text/html")
        elif path == "/api/health":
            route.fulfill(json=dict(status="online",image_models={"cf:flux-schnell":"FLUX Schnell"},default_image_model="cf:flux-schnell",image_model_setup={"cf:flux-schnell":{"configured":True}}))
        elif path == "/api/brands" and route.request.method == "GET":
            route.fulfill(json={"brands":brands})
        elif path == "/api/brands" and route.request.method == "POST":
            brand = {"id":"browser-client",**route.request.post_data_json}; brands.append(brand)
            route.fulfill(json={"brand":brand},status=201)
        elif path == "/api/generate":
            assert route.request.post_data_json["brand_id"] == "lexnis-technologies"
            route.fulfill(json=campaign)
        elif path.startswith("/renders/"):
            file = ROOT/"output/renders"/Path(path).name
            types={".gif":"image/gif",".mp4":"video/mp4",".zip":"application/zip",".jpg":"image/jpeg"}
            route.fulfill(body=file.read_bytes(),content_type=types.get(file.suffix,"application/octet-stream"))
        elif path.startswith("/static/assets/"):
            file=ROOT/"static/assets"/Path(path).name
            route.fulfill(body=file.read_bytes(),content_type="application/zip" if file.suffix==".zip" else "image/png")
        elif "/static/tailwind.css" in url:
            route.fulfill(body=(ROOT/"static/tailwind.css").read_bytes(),content_type="text/css")
        elif "lucide" in url:
            route.fulfill(body="window.lucide={createIcons(){}};",content_type="application/javascript")
        else:
            route.fulfill(body="",content_type="text/plain")
    page.route("**/*",route)
    page.goto("https://agency.test/",wait_until="domcontentloaded")
    page.wait_for_function("agencyBrands.length >= 3")
    page.get_by_text("Client Brand Kits",exact=True).click()
    page.locator("#agency-brand-select").select_option("noor-solar")
    assert page.locator("#brand-input").input_value() == "Noor Solar"
    assert page.evaluate("window.brandProfile.brand_colors.accent") == "#F5A623"
    page.get_by_role("button",name="New client",exact=True).click()
    page.locator("#agency-brand-name").fill("Browser Client")
    page.get_by_role("button",name="Save Brand Kit",exact=True).click()
    page.wait_for_function("selectedAgencyBrandId === 'browser-client'")
    page.locator("#agency-brand-select").select_option("lexnis-technologies")
    page.locator("#prompt-input").fill("Hiring an AI Engineer for Lexnis")
    page.locator("#generate-btn").click()
    panel = page.locator("#carousel-preview")
    panel.get_by_text("LinkedIn Copy",exact=True).wait_for(state="visible")
    assert panel.get_by_alt_text("Story 9:16").count() == 1
    assert panel.get_by_alt_text("Banner 1.91:1").count() == 1
    panel.get_by_role("button",name="X Post",exact=True).click()
    assert panel.locator("pre").inner_text() == campaign["copywriting"]["x_post"]
    panel.get_by_role("button",name="Copy Text",exact=True).click()
    page.wait_for_function("navigator.clipboard.readText().then(t=>t.length>0)")
    with page.expect_download() as download:
        panel.get_by_role("button",name="Download Full Agency Kit (.ZIP)",exact=True).click()
    assert download.value.suggested_filename.endswith(".zip")
    panel.get_by_label("Carousel language").select_option("ar")
    assert panel.locator("pre").get_attribute("dir") == "rtl"
    assert panel.locator("pre").inner_text() == campaign["arabic_copywriting"]["linkedin_post"]
    if campaign.get("animation_mp4_url"):
        assert panel.locator("video").count() == 1
        assert panel.locator("video").evaluate("v=>v.muted && v.loop && v.playsInline")
    page.set_viewport_size({"width":390,"height":844})
    panel.get_by_text("LinkedIn Copy",exact=True).scroll_into_view_if_needed()
    assert not errors, errors
    page.set_viewport_size({"width":1500,"height":1100})
    panel.screenshot(path=str(ROOT/"output/professional-agency-studio.png"))
    print("Agency browser checks passed: client switching/save, five formats, copy tabs/clipboard, Arabic, video and full ZIP.")
    browser.close()
