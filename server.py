"""
Lexnis Campaign Studio - FastAPI Backend Server
================================================
Serves the web UI and provides the AI marketing agency endpoints.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Literal, Tuple
import os
import io
import re
import json
import hashlib
import base64
import concurrent.futures
from urllib.parse import urlsplit
import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from visual_engine import (
    model_setup, preferred_local_model, composite_template_swap, sanitize_brand_tag, resolve_brand_theme,
    is_unsafe_welcome_headline,
    save_welcome_animation_layers,
)

from campaign_generator import (
    LexnisCampaignStudio, CampaignAsset, IMAGE_MODELS, DEFAULT_IMAGE_MODEL, RENDERS_DIR,
    GENERIC_BRAND_NAMES, extract_brand_name_from_prompt, resolve_featured_person, team_welcome_headline,
    is_generic_filename_name as _is_generic_filename_name,
    generate_companion_image, generate_campaign_post,
    generate_campaign_copy, render_omnichannel_variants,
)

app = FastAPI(
    title="Lexnis Campaign Studio API",
    description="AI marketing agency: web research, Instagram copy and watermark-free visuals",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from video_api import router as video_router
from video_security import VideoRequestLimits
app.include_router(video_router)
app.add_middleware(VideoRequestLimits)

from agency.api import router as agency_router
from agency.security import AgencyRequestLimits
app.include_router(agency_router)
app.add_middleware(AgencyRequestLimits)

BASE_DIR = Path(__file__).resolve().parent
# Per-campaign bundles are generated output: they live with the other renders (git-ignored),
# not in the tracked static assets folder, which every generated campaign used to add a ZIP to.
AGENCY_BUNDLES_DIR = RENDERS_DIR
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = BASE_DIR / "output" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEST_ASSETS_DIR = BASE_DIR / "test_assets"
TEST_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/renders", StaticFiles(directory=RENDERS_DIR), name="renders")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/test_assets", StaticFiles(directory=TEST_ASSETS_DIR), name="test_assets")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def render_url(path: str) -> str:
    if not path:
        return ""
    p = Path(path)
    if "uploads" in p.parts:
        return f"/uploads/{p.name}"
    if "test_assets" in p.parts:
        return f"/test_assets/{p.name}"
    if "static" in p.parts and "assets" in p.parts:
        return f"/static/assets/{p.name}"
    return f"/renders/{p.name}"


def render_path(url: str) -> str:
    """Map a /renders/..., /uploads/..., or /test_assets/... URL from the UI back to the file on disk."""
    path = urlsplit(url).path if url else ""
    if path.startswith("/renders/"):
        p = RENDERS_DIR / Path(path).name
        if p.exists():
            return str(p)
    elif path.startswith("/uploads/"):
        p = UPLOADS_DIR / Path(path).name
        if p.exists():
            return str(p)
    elif path.startswith("/test_assets/"):
        p = TEST_ASSETS_DIR / Path(path).name
        if p.exists():
            return str(p)
    elif path.startswith("/static/assets/"):
        p = BASE_DIR / "static/assets" / Path(path).name
        if p.is_file():
            return str(p)
    elif url and _inside_project(url):
        return str(Path(url))
    return ""


def _inside_project(path: str) -> bool:
    """True for an existing file inside this project. The server listens on the network, so a
    client-supplied path must never reach files elsewhere on the machine."""
    try:
        resolved = Path(path).resolve()
        return resolved.is_file() and resolved.is_relative_to(BASE_DIR)
    except (OSError, ValueError):
        return False


def _is_generic_brand(name: Optional[str]) -> bool:
    return (name or "").strip().lower() in GENERIC_BRAND_NAMES


def resolve_request_brand(
    req_brand: Optional[str],
    brand_profile: Optional[Dict[str, Any]],
    guidelines: Optional[str],
    prompt: Optional[str],
    company_url: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """
    Decide which brand a request is for, returning (brand_name, brand_profile).
    - An uploaded guideline's profile (or guideline text, parsed here) is the source of truth.
    - "Lexnis Technologies" / "Lexnis" in brand_name is treated as a stale UI default whenever a
      guideline is present, unless the website explicitly is lexnis.com.
    - Falls back to the prompt; never guesses Lexnis unless the prompt mentions it. May return "".
    - A Lexnis-named profile is dropped when the resolved brand is not Lexnis.
    """
    bp: Dict[str, Any] = dict(brand_profile or {})
    prompt = prompt or ""
    if not bp and guidelines and guidelines.strip():
        try:
            bp = LexnisCampaignStudio().extract_brand_profile_from_guideline(guideline_raw_text=guidelines)
        except Exception:
            bp = {}

    req = (req_brand or "").strip()
    profile_brand = str(bp.get("brand_name") or bp.get("company_name") or "").strip()
    profile_is_lexnis = "lexnis" in profile_brand.lower()
    guideline_present = bool(bp.get("locked_by_guidelines") or bp.get("source") == "uploaded_guidelines" or (guidelines and guidelines.strip()))
    req_is_stale_lexnis = "lexnis" in req.lower() and guideline_present and "lexnis.com" not in (company_url or "").lower()

    if profile_brand and not _is_generic_brand(profile_brand) and (_is_generic_brand(req) or (req_is_stale_lexnis and not profile_is_lexnis)):
        brand = profile_brand
    elif not _is_generic_brand(req) and not (req_is_stale_lexnis and not profile_is_lexnis):
        brand = req
    else:
        brand = extract_brand_name_from_prompt(prompt, fallback_name="")
        if _is_generic_brand(brand):
            brand = "Lexnis Technologies" if "lexnis" in prompt.lower() else ""

    if bp and profile_is_lexnis and "lexnis" not in brand.lower():
        bp = {}  # a Lexnis profile must never style another brand's card
    return brand, bp


def enrich_agency_kit(data, request, theme):
    """Add formats, localized copy and a complete bundle without changing old URLs."""
    from agency_suite import bundle_campaign
    request = {"brand_name_ar": (data.get("brand_dna") or {}).get("brand_name_ar", ""),
               "tagline": (data.get("brand_dna") or {}).get("tagline", ""), **request}
    # The channel copy is adapted from the campaign that was actually written, in each language.
    # Placeholder copy produced when the text model was unreachable is not treated as written copy.
    copy_was_written = not any("unavailable" in str(note).lower() for note in data.get("critique_notes") or [])
    if copy_was_written and data.get("hook") and data.get("caption"):
        request.setdefault("copy_pack", {key: data.get(key) for key in ("hook", "caption", "highlights", "cta", "hashtags")})
    arabic = data.get("arabic")
    if copy_was_written and isinstance(arabic, dict) and arabic.get("hook") and not str(arabic["hook"]).startswith("ارتقِ بمعايير الريادة"):
        request.setdefault("copy_pack_ar", arabic)
    requested_language = request.get("language", "en")
    if requested_language == "ar" and data.get("arabic_image_url"):
        for field in ("image_url", "companion_image_url", "animation_url", "carousel_urls"):
            data[field] = data.get("arabic_" + field) or data.get(field)
    data["language"] = requested_language
    data["copywriting"] = generate_campaign_copy({**request, "language": "ar" if requested_language == "ar" else "en"}, theme)
    if not data.get("companion_image_url") or not data.get("animation_url"):
        return data
    kits = {}
    for lang in ("en", "ar"):
        if lang == "en" and requested_language == "ar":
            continue
        prefix = "arabic_" if lang == "ar" else ""
        primary_url = data.get(prefix + "image_url")
        if not primary_url:
            continue
        paths = {key: render_path(data.get(prefix+key, "")) for key in ("image_url", "companion_image_url", "animation_url")}
        if not all(paths.values()):
            continue
        localized = {**request, "language": lang, "companion_image_path": paths["companion_image_url"]}
        copywriting = generate_campaign_copy(localized, theme)
        variants = render_omnichannel_variants(paths["image_url"], localized, theme)
        video = Path(paths["animation_url"]).with_suffix(".mp4")
        paths.update(story_url=variants["story_path"], landscape_url=variants["landscape_path"],
                     animation_mp4_url=str(video) if video.is_file() else "")
        bundle = AGENCY_BUNDLES_DIR / (Path(paths["image_url"]).stem + "_agency_kit.zip")
        bundle_campaign(paths, copywriting, bundle)
        kits[lang] = dict(story_url=render_url(paths["story_url"]), landscape_url=render_url(paths["landscape_url"]),
                          animation_mp4_url=render_url(paths["animation_mp4_url"]), bundle_zip_url=render_url(str(bundle)),
                          copywriting=copywriting)
        if lang == "ar":
            data.update({"arabic_"+key: value for key, value in kits[lang].items()})
    selected = "ar" if requested_language == "ar" else "en"
    data.update(kits.get(selected, {}))
    data["agency_kits"] = kits
    return data


class BrandKitRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=100)
    brand_name_ar: str = Field("", max_length=100)
    primary_hex: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_hex: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_path: str = Field("", max_length=500)
    tagline: str = Field("", max_length=200)
    hashtag: str = Field("", max_length=100, pattern=r"^(?:#[\w\u0600-\u06ff]+)?$")


@app.get("/api/system/capabilities")
def system_capabilities():
    from agency.model_registry import registry
    return registry.probe_system_capabilities()


@app.get("/api/brands")
def brand_kits_list():
    from brand_kits import list_brands
    return {"brands": list_brands()}


@app.post("/api/brands", status_code=201)
def brand_kit_create(req: BrandKitRequest):
    from brand_kits import LOCK, list_brands, write_brands
    import uuid
    with LOCK:
        brands = list_brands()
        if any(item["brand_name"].casefold() == req.brand_name.strip().casefold() for item in brands):
            raise HTTPException(409, "A brand kit with this name already exists")
        brand = {"id": uuid.uuid4().hex[:12], **req.model_dump()}
        brand["brand_name"] = brand["brand_name"].strip()
        if not brand["brand_name"]:
            raise HTTPException(422, "Brand name is required")
        write_brands([*brands, brand])
    return {"brand": brand}


@app.get("/api/brands/{brand_id}")
def brand_kit_read(brand_id: str):
    from brand_kits import get_brand
    brand = get_brand(brand_id)
    if not brand:
        raise HTTPException(404, "Brand kit not found")
    return {"brand": brand}


@app.put("/api/brands/{brand_id}")
def brand_kit_update(brand_id: str, req: BrandKitRequest):
    from brand_kits import LOCK, list_brands, write_brands
    with LOCK:
        brands = list_brands()
        if not any(b["id"] == brand_id for b in brands):
            raise HTTPException(404, "Brand kit not found")
        if any(b["id"] != brand_id and b["brand_name"].casefold() == req.brand_name.strip().casefold() for b in brands):
            raise HTTPException(409, "A brand kit with this name already exists")
        brand = {"id": brand_id, **req.model_dump()}
        brand["brand_name"] = brand["brand_name"].strip()
        if not brand["brand_name"].strip():
            raise HTTPException(422, "Brand name is required")
        write_brands([brand if b["id"] == brand_id else b for b in brands])
    return {"brand": brand}


@app.delete("/api/brands/{brand_id}")
def brand_kit_delete(brand_id: str):
    from brand_kits import LOCK, list_brands, write_brands
    with LOCK:
        brands = list_brands()
        if not any(b["id"] == brand_id for b in brands):
            raise HTTPException(404, "Brand kit not found")
        write_brands([b for b in brands if b["id"] != brand_id])
    return {"deleted": brand_id}


class CampaignBundleRequest(BaseModel):
    deliverables: Dict[str, str]
    copywriting: Dict[str, Any]


@app.post("/api/campaign/bundle")
def campaign_bundle(req: CampaignBundleRequest):
    from agency_suite import bundle_campaign
    import uuid
    paths = {}
    for key in ("image_url", "companion_image_url", "animation_url", "animation_mp4_url", "story_url", "landscape_url"):
        url = req.deliverables.get(key, "")
        if not url and key == "animation_mp4_url":
            continue
        if not re.fullmatch(r"/(?:renders|static/assets)/[^/\\]+\.(?:jpg|gif|mp4)", url, re.I):
            raise HTTPException(400, "Expected a generated deliverable URL")
        expected = ".gif" if key == "animation_url" else ".mp4" if key == "animation_mp4_url" else ".jpg"
        if Path(url).suffix.lower() != expected:
            raise HTTPException(400, f"Incorrect format for {key}")
        paths[key] = render_path(url)
        if paths[key] and Path(paths[key]).resolve().parent not in (RENDERS_DIR.resolve(), (BASE_DIR/"static/assets").resolve()):
            raise HTTPException(400, "Deliverables must be public generated media")
    output = AGENCY_BUNDLES_DIR / f"campaign_{uuid.uuid4().hex[:12]}_agency_kit.zip"
    try:
        bundle_campaign(paths, req.copywriting, output)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"bundle_zip_url": render_url(str(output))}


class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Product, offer or campaign concept")
    generate_companion: bool = True
    use_local_sdxl: Optional[bool] = None
    language: Literal["en", "ar", "both"] = "en"
    brand_id: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)
    key_points_ar: List[str] = Field(default_factory=list)
    brand: Optional[str] = Field("", description="Brand name (empty = resolve from guideline profile or prompt)")
    tone: Optional[str] = Field(None, description="Marketing tone")
    theme: Optional[str] = Field(None, description="Visual direction")
    seed: Optional[int] = Field(None, description="Image seed")
    use_search: Optional[bool] = Field(True, description="Enable web research")
    image_model: Optional[str] = Field(DEFAULT_IMAGE_MODEL, description="Image model id")
    enhance_image: Optional[bool] = Field(True, description="Headline + brand overlay on the image")
    output_format: Literal["portrait", "landscape", "square"] = "portrait"
    guidelines: Optional[str] = Field("", description="Client brand guidelines, style guide, or strategic constraints")
    uploaded_image_url: Optional[str] = Field(None, description="URL of uploaded image asset to composite as ad visual")
    uploaded_image_urls: Optional[List[str]] = Field(default_factory=list, description="URLs of multiple uploaded images")
    use_uploaded_image: Optional[bool] = Field(None, description="Whether to feature the uploaded image as the ad visual")
    company_url: Optional[str] = Field(None, description="Company website URL for real-time Brand DNA extraction")
    recolor_to_brand: Optional[bool] = Field(True, description="Whether template visual should adapt colors to brand flow")
    post_type: Optional[str] = Field("general", description="Campaign post type, e.g. team_welcome, product_launch, event_announcement, milestone_achievement, thought_leadership, case_study, hiring, brand_awareness")
    person_name: Optional[str] = Field(None, description="Featured person name (for team_welcome or spotlight)")
    person_title: Optional[str] = Field(None, description="Featured person job title / department")
    logo_url: Optional[str] = Field(None, description="URL of uploaded custom corporate logo")
    logo_path: Optional[str] = Field(None, description="Local file path of uploaded custom corporate logo")
    brand_profile_json: Optional[str] = Field(None, description="Serialized JSON of Brand Profile from Stage 1/2")
    brand_profile: Optional[Dict[str, Any]] = Field(None, description="Structured brand profile dict")


class SuggestPromptRequest(BaseModel):
    brand_profile: Optional[Dict[str, Any]] = Field(None, description="Brand profile dict")
    brand_name: Optional[str] = Field(None, description="Brand name")
    post_type: Optional[str] = Field("hiring", description="Post type")
    lang: Optional[str] = Field("en", description="Language code")
    quick_fields: Optional[Dict[str, Any]] = Field(None, description="Quick fill fields from UI")


class AnalyzeWebsiteRequest(BaseModel):
    url: str = Field(..., description="Company website URL to extract brand DNA from")
    brand: Optional[str] = Field("", description="Brand name (empty = derive from the website)")


class GenerateGuidelinesRequest(BaseModel):
    brand: Optional[str] = Field("Lexnis Technologies", description="Brand name to research")
    prompt: Optional[str] = Field("", description="Optional campaign or product concept")
    use_search: Optional[bool] = Field(True, description="Enable real-time market research via Google/web")


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., description="Vague, simple or conversational prompt to elevate")
    brand: Optional[str] = Field("Lexnis Technologies", description="Current brand field (if any)")
    guidelines: Optional[str] = Field("", description="Client brand guidelines or strategic constraints")
    style_preset: Optional[str] = Field("", description="Optional creative style or prompt flavor")
    post_type: Optional[str] = Field("general", description="Campaign post type")
    person_name: Optional[str] = Field(None, description="Featured person name")
    person_title: Optional[str] = Field(None, description="Featured person title")


class RenderRequest(BaseModel):
    visual_prompt: str
    generate_companion: bool = True
    use_local_sdxl: Optional[bool] = None
    post_type: str = "general"
    seed: int
    image_model: Optional[str] = DEFAULT_IMAGE_MODEL
    headline: Optional[str] = ""
    brand: Optional[str] = ""
    overlay: Optional[bool] = True
    output_format: Literal["portrait", "landscape", "square"] = "portrait"
    tagline: str = ""
    campaign_context: Optional[str] = ""
    arabic_headline: Optional[str] = ""
    arabic_tagline: Optional[str] = ""
    uploaded_image_url: Optional[str] = Field(None, description="URL of uploaded image to composite")
    use_uploaded_image: Optional[bool] = Field(False, description="Whether to re-render using uploaded photo")


class ExportRequest(BaseModel):
    prompt: str
    hook: str
    caption: str
    highlights: List[str]
    hashtags: str
    visual_prompt: str
    image_url: str
    seed: int
    brand: Optional[str] = "Lexnis Technologies"
    cta: Optional[str] = ""
    image_headline: Optional[str] = ""
    alt_text: Optional[str] = ""
    instagram_caption: Optional[str] = ""
    image_model: Optional[str] = DEFAULT_IMAGE_MODEL
    clean_image_url: Optional[str] = ""
    arabic_image_url: Optional[str] = ""
    companion_image_url: str = ""
    arabic_companion_image_url: str = ""
    animation_url: str = ""
    arabic_animation_url: str = ""
    search_results: Optional[List[Dict[str, Any]]] = None
    agent_dialogue: Optional[List[Dict[str, Any]]] = None
    critique_notes: Optional[List[str]] = None
    enhanced_prompt: Optional[str] = ""
    output_format: Literal["portrait", "landscape", "square"] = "portrait"
    image_status: str = "ready"
    warnings: List[str] = Field(default_factory=list)
    rivals: Optional[List[Dict[str, Any]]] = None
    competitive_strategy: Optional[Dict[str, Any]] = None
    visual_analysis: Optional[str] = ""
    visual_headline: Optional[str] = ""
    visual_tagline: Optional[str] = ""
    arabic: Optional[Dict[str, Any]] = None
    guidelines: Optional[str] = ""


@app.get("/")
def serve_index():
    """Serve the primary single-file dashboard."""
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path)


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def favicon():
    """Handle browser favicon request without 404."""
    from fastapi.responses import Response
    return Response(
        content=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">\xf0\x9f\x9a\x80</text></svg>',
        media_type="image/svg+xml"
    )


@app.get("/api/health")
def health_check():
    """Engine telemetry and health check."""
    studio = LexnisCampaignStudio()
    default_model = os.getenv('IMAGE_MODEL') or preferred_local_model() or DEFAULT_IMAGE_MODEL
    return {
        "status": "online",
        "engine": "Lexnis Campaign Studio (AI Marketing Agency)",
        "text_engine": f"{studio.text_engine}:{studio.model}",
        "search_engine": "Google Search + page scraping (free)",
        "visual_engine": "Explicit provider selection; see model settings",
        "has_gemini_key": bool(getattr(studio, "gemini_key", None)),
        "watermark_free": True,
        "image_models": IMAGE_MODELS,
        "default_image_model": default_model,
        "image_model_setup": {model: model_setup(model) for model in IMAGE_MODELS},
        "image_provider_configured": model_setup(default_model)["configured"],
    }


@app.get("/api/search")
def search_endpoint(q: str):
    """Free web research endpoint (zero API key)."""
    try:
        results = LexnisCampaignStudio.search_google(q, max_results=5)
        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/enhance-prompt")
def enhance_prompt_endpoint(req: EnhancePromptRequest):
    """AI Prompt Architect: transform requests into Fortune-500 executive briefs with strategic review breakdown."""
    try:
        studio = LexnisCampaignStudio()
        result = studio.enhance_user_prompt(
            req.prompt,
            req.brand,
            guidelines=req.guidelines or "",
            style_preset=req.style_preset or "",
            post_type=req.post_type,
            person_name=req.person_name,
            person_title=req.person_title,
        )
        return {
            "status": "success",
            "original_prompt": req.prompt,
            "post_type": req.post_type or "general",
            "enhanced_prompt": result.get("enhanced_prompt", req.prompt),
            "detected_brand": result.get("detected_brand", req.brand or "Lexnis Technologies"),
            "product_name": result.get("product_name", ""),
            "target_audience": result.get("target_audience", "Discerning customers & decision-makers"),
            "core_hook_angle": result.get("core_hook_angle", "Category leadership through tangible performance"),
            "visual_art_direction": result.get("visual_art_direction", "Photographic commercial setting with clean typography negative space"),
            "improvements": result.get("improvements", [
                "Clarified core target audience and value proposition",
                "Constructed photographic lighting and visual composition directives",
                "Anchored in verified brand tone"
            ]),
            "suggested_tone": result.get("suggested_tone", "confident, premium and benefit-driven"),
            "suggested_theme": result.get("suggested_theme", "Cinematic lifestyle photography")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/campaign/generate")
@app.post("/api/generate")
def generate_campaign_endpoint(req: GenerateRequest):
    """Research -> brief -> Instagram copy -> watermark-free visual."""
    try:
        if req.brand_id:
            from brand_kits import get_brand, profile_for
            kit = get_brand(req.brand_id)
            if not kit:
                raise HTTPException(404, "Brand kit not found")
            req.brand = kit["brand_name"]
            req.brand_profile = {**profile_for(kit), **(req.brand_profile or {})}
            req.logo_url = req.logo_url or kit.get("logo_path")
        studio = LexnisCampaignStudio()
        all_up_paths = []
        uploaded_logo_path = None
        if req.uploaded_image_urls:
            for u in req.uploaded_image_urls:
                p = render_path(u)
                if p and Path(p).exists():
                    p_name = Path(p).name.lower()
                    if p_name.startswith("logo_") or "logo" in Path(p).stem.lower():
                        if not uploaded_logo_path:
                            uploaded_logo_path = str(p)
                    elif str(p) not in all_up_paths:
                        all_up_paths.append(str(p))
        if req.uploaded_image_url:
            p = render_path(req.uploaded_image_url)
            if p and Path(p).exists():
                p_name = Path(p).name.lower()
                if p_name.startswith("logo_") or "logo" in Path(p).stem.lower():
                    if not uploaded_logo_path:
                        uploaded_logo_path = str(p)
                elif str(p) not in all_up_paths:
                    all_up_paths.append(str(p))

        # Only the photos sent with THIS request can be the person on the card. Older files in
        # output/uploads are never added (that put a previously uploaded person on the card), and
        # generate_campaign pairs a single portrait with the bundled template frame itself.
        up_img_path = all_up_paths[0] if all_up_paths else None

        # Resolve custom logo if provided
        logo_to_use = None
        if req.logo_path and _inside_project(req.logo_path):
            logo_to_use = req.logo_path
        elif req.logo_url:
            p = render_path(req.logo_url)
            if p and Path(p).exists():
                logo_to_use = str(p)
            elif _inside_project(str(BASE_DIR / req.logo_url.lstrip("/\\"))):
                logo_to_use = str(BASE_DIR / req.logo_url.lstrip("/\\"))
            else:
                logo_to_use = req.logo_url
        elif uploaded_logo_path:
            logo_to_use = uploaded_logo_path

        bp = dict(req.brand_profile) if req.brand_profile else {}
        if req.brand_profile_json:
            try:
                parsed_bp = json.loads(req.brand_profile_json)
                if isinstance(parsed_bp, dict):
                    bp.update(parsed_bp)
            except Exception:
                pass

        # Brand: uploaded guideline profile > typed brand (a leftover "Lexnis Technologies" is a stale
        # default when a guideline is loaded) > prompt. Market-research text in req.guidelines is not an
        # uploaded guideline, so it is left to generate_campaign rather than used to override the brand.
        effective_brand, bp = resolve_request_brand(req.brand, bp, None, req.prompt, req.company_url)
        if not effective_brand:
            effective_brand = "Brand"  # generate_campaign would otherwise default to Lexnis
        req.brand = effective_brand
        if not _is_generic_brand(effective_brand) and effective_brand != "Lexnis Technologies" and not bp.get("brand_name"):
            bp["brand_name"] = effective_brand

        asset: CampaignAsset = studio.generate_campaign(
            prompt=req.prompt,
            brand=effective_brand,
            tone=req.tone,
            theme=req.theme,
            seed=req.seed,
            use_search=req.use_search if req.use_search is not None else True,
            image_model=req.image_model or DEFAULT_IMAGE_MODEL,
            enhance_image=req.enhance_image if req.enhance_image is not None else True,
            output_format=req.output_format,
            guidelines=req.guidelines or "",
            uploaded_image_path=up_img_path,
            uploaded_image_paths=all_up_paths,
            use_uploaded_image=req.use_uploaded_image if req.use_uploaded_image is not None else (len(all_up_paths) > 0),
            company_url=req.company_url,
            recolor_to_brand=req.recolor_to_brand if req.recolor_to_brand is not None else True,
            post_type=req.post_type,
            person_name=req.person_name,
            person_title=req.person_title,
            logo_path=logo_to_use,
            logo_url=req.logo_url,
            brand_profile=bp or None,
            generate_companion=req.generate_companion,
            use_local_sdxl=req.use_local_sdxl,
        )
        data = asset.to_dict()
        data["image_url"] = render_url(asset.image_path)
        data["clean_image_url"] = render_url(asset.clean_image_path)
        data["arabic_image_url"] = render_url(asset.arabic_image_path)
        data["companion_image_url"] = render_url(asset.companion_image_path)
        data["arabic_companion_image_url"] = render_url(asset.arabic_companion_image_path)
        data["animation_url"] = render_url(asset.animation_path)
        data["arabic_animation_url"] = render_url(asset.arabic_animation_path)
        data["carousel_urls"] = [url for url in (data["image_url"], data["companion_image_url"], data["animation_url"]) if url]
        data["arabic_carousel_urls"] = [url for url in (data["arabic_image_url"], data["arabic_companion_image_url"], data["arabic_animation_url"]) if url]
        data["uploaded_image_url"] = render_url(asset.uploaded_image_url)
        data["uploaded_arabic_url"] = render_url(asset.uploaded_arabic_url)
        data["ai_image_url"] = render_url(asset.ai_image_url)
        data["ai_arabic_url"] = render_url(asset.ai_arabic_url)
        data["has_uploaded_asset"] = bool(asset.uploaded_image_url)
        data["guidelines"] = asset.guidelines
        data["guidelines_source"] = getattr(asset, "guidelines_source", "none")
        data["company_url"] = getattr(asset, "company_url", req.company_url or "")
        data["brand_dna"] = getattr(asset, "brand_dna", {})
        data["post_type"] = getattr(asset, "post_type", req.post_type or "general")
        data["person_name"] = getattr(asset, "person_name", req.person_name or "")
        data["person_title"] = getattr(asset, "person_title", req.person_title or "")
        agency_theme = resolve_brand_theme(brand_profile=asset.brand_dna or bp or None, uploaded_logo_path=logo_to_use,
                                           brand_name=asset.brand, post_type=asset.post_type)
        card_en, card_ar = (asset.card_copy or {}).get("en") or {}, (asset.card_copy or {}).get("ar") or {}
        card_fields = {key: value for key, value in dict(
            cta_button=str(card_en.get("cta_text") or "").split("•")[0].strip(),
            cta_button_ar=str(card_ar.get("cta_text") or "").split("•")[0].strip(),
            headline_ar=str(card_ar.get("card_title") or "").replace("\n", " ").strip()).items() if value}
        return enrich_agency_kit(data, dict(**card_fields, topic=req.prompt, post_type=asset.post_type, person_name=asset.person_name,
                                          role_title=asset.person_title if "welcome" in asset.post_type else asset.person_name or asset.brief.get("product_name", ""),
                                          language=req.language, headline=asset.image_headline, key_points=req.key_points,
                                          key_points_ar=req.key_points_ar), agency_theme)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze-website")
def analyze_website_endpoint(req: AnalyzeWebsiteRequest):
    """Extract brand DNA (colors, typography, hashtag, aesthetic) from company website."""
    try:
        studio = LexnisCampaignStudio()
        dna = studio.analyze_company_website(req.url, brand=req.brand)
        return dna
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def extract_logo_from_pdf_stream(pdf_bytes: bytes, uploads_dir: Path) -> Optional[Tuple[str, str]]:
    """
    Extracts clean logo graphic embedded on Page 1 of a guideline PDF.
    Filters for typical logo dimensions (60-800px width/height, 0.5-5.0 aspect ratio).
    """
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            return None
        page = doc[0]
        image_list = page.get_images(full=True)
        for img_info in image_list:
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image.get("image")
            if not image_bytes:
                continue
            w = base_image.get("width", 0)
            h = base_image.get("height", 0)
            ext = base_image.get("ext", "png")
            aspect = w / float(h) if h > 0 else 1.0
            if 60 <= w <= 800 and 60 <= h <= 800 and 0.5 <= aspect <= 5.0:
                f_hash = hashlib.sha1(image_bytes).hexdigest()[:12]
                saved_name = f"extracted_guideline_logo_{f_hash}.{ext}"
                disk_path = uploads_dir / saved_name
                disk_path.write_bytes(image_bytes)
                return f"/uploads/{saved_name}", str(disk_path)
    except Exception:
        pass
    return None


@app.post("/api/analyze-brand")
async def analyze_brand_endpoint(
    pdf_file: Optional[UploadFile] = File(None),
    logo_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    website: Optional[str] = Form(""),
    brand_name_input: Optional[str] = Form(""),
    guidelines: Optional[str] = Form(""),
    guideline_text: Optional[str] = Form(""),
):
    """
    Guideline-Driven Brand Analysis:
    Extracts structured company intelligence, full text, and explicit brand hex codes
    from uploaded guidelines (PDF or image) even when website is empty.
    Guideline text may also be posted directly as `guidelines` or `guideline_text`; it is
    combined with the text of any uploaded PDF (first 15 pages / 25,000 characters).
    """
    try:
        studio = LexnisCampaignStudio()
        all_files: List[UploadFile] = []
        if files:
            all_files.extend(files)
        if file and file not in all_files:
            all_files.append(file)
        if pdf_file and pdf_file not in all_files:
            all_files.append(pdf_file)
        if logo_file and logo_file not in all_files:
            all_files.append(logo_file)
        if image_file and image_file not in all_files:
            all_files.append(image_file)

        pdf_bytes = None
        image_bytes = None
        guideline_raw_text = (guidelines or guideline_text or "").strip()
        filename = ""
        saved_logo_url = None
        saved_logo_path = None

        IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".svg"}

        for f in all_files:
            fname = f.filename or "brand_asset"
            ext = Path(fname).suffix.lower()
            content_bytes = await f.read()
            if not content_bytes:
                continue

            if ext == ".pdf":
                pdf_bytes = content_bytes
                filename = fname
            elif ext in IMAGE_EXTENSIONS or (f.content_type and f.content_type.startswith("image/")):
                image_bytes = content_bytes
                if not filename:
                    filename = fname
                f_hash = hashlib.sha1(content_bytes).hexdigest()[:12]
                clean_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(fname).stem)[:24]
                safe_ext = ext if ext in IMAGE_EXTENSIONS else '.jpg'
                saved_name = f"logo_{clean_stem}_{f_hash}{safe_ext}"
                disk_path = UPLOADS_DIR / saved_name
                disk_path.write_bytes(content_bytes)
                saved_logo_url = f"/uploads/{saved_name}"
                saved_logo_path = str(disk_path)
            elif ext in [".txt", ".md", ".json", ".csv"]:
                try:
                    guideline_raw_text += "\n\n" + content_bytes.decode("utf-8")
                except Exception:
                    guideline_raw_text += "\n\n" + content_bytes.decode("latin-1", errors="ignore")
                if not filename:
                    filename = fname

        profile = studio.extract_brand_profile_from_guideline(
            guideline_raw_text=guideline_raw_text,
            pdf_bytes=pdf_bytes,
            image_bytes=image_bytes,
            filename=filename,
            website=website or "",
            user_brand_name_input=brand_name_input or ""
        )

        if pdf_bytes and not saved_logo_url:
            pdf_logo = extract_logo_from_pdf_stream(pdf_bytes, UPLOADS_DIR)
            if pdf_logo:
                saved_logo_url, saved_logo_path = pdf_logo

        if saved_logo_url:
            profile["logo_url"] = saved_logo_url
            profile["logo_path"] = saved_logo_path

        return {
            "status": "success",
            "profile": profile,
            "brand_dna": profile,
            "guidelines": profile.get("guideline_summary", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/suggest-prompt")
def suggest_prompt_endpoint(req: SuggestPromptRequest):
    """Synthesizes a tailored, guideline-aware campaign prompt for Stage 4."""
    try:
        studio = LexnisCampaignStudio()
        bp = dict(req.brand_profile or {})
        if req.brand_name and not bp.get("brand_name"):
            bp["brand_name"] = req.brand_name
        res = studio.suggest_post_prompt(
            brand_profile=bp,
            post_type=req.post_type or "hiring",
            lang=req.lang or "en",
            quick_fields=req.quick_fields or {}
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-guidelines")
def generate_guidelines_endpoint(req: GenerateGuidelinesRequest):
    """Synthesize market-researched brand guidelines & competitive directives on demand."""
    try:
        studio = LexnisCampaignStudio()
        brand = req.brand or "Lexnis Technologies"
        guidelines = studio.generate_market_research_guidelines(
            brand=brand,
            prompt=req.prompt or "",
            use_search=req.use_search if req.use_search is not None else True
        )
        words = len(guidelines.split()) if guidelines else 0
        return {
            "status": "success",
            "brand": brand,
            "guidelines": guidelines,
            "word_count": words,
            "char_count": len(guidelines),
            "source": "market_research",
            "preview": guidelines[:350] + ("..." if len(guidelines) > 350 else "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-visual")
async def upload_visual_endpoint(
    file: UploadFile = File(...),
    slot: Optional[str] = Form("subject")
):
    """
    Dedicated endpoint for visual assets:
    - Target Subject / Product portrait to feature
    - Template graphic / Reference layout to populate
    - Corporate logo (PNG, WebP, SVG, JPG)
    Saves the file to disk, calculates dimensions, and generates an optimized thumbnail.
    """
    try:
        content_bytes = await file.read()
        if not content_bytes:
            raise HTTPException(status_code=400, detail="Empty visual file uploaded.")

        fname = file.filename or "visual_asset.jpg"
        ext = Path(fname).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".svg"}:
            ext = ".png" if slot == "logo" else ".jpg"

        f_hash = hashlib.sha1(content_bytes).hexdigest()[:12]
        clean_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(fname).stem)[:24]
        saved_name = f"{slot}_{clean_stem}_{f_hash}{ext}"
        disk_path = UPLOADS_DIR / saved_name
        disk_path.write_bytes(content_bytes)

        width, height = 0, 0
        thumb_b64 = ""
        try:
            if ext == ".svg":
                # For SVG, parse dimensions or set defaults and provide SVG data URI
                svg_str = content_bytes.decode("utf-8", errors="ignore")
                wm = re.search(r'width=["\']?(\d+)', svg_str)
                hm = re.search(r'height=["\']?(\d+)', svg_str)
                width = int(wm.group(1)) if wm else 300
                height = int(hm.group(1)) if hm else 100
                thumb_b64 = "data:image/svg+xml;base64," + base64.b64encode(content_bytes).decode("utf-8")
            else:
                from PIL import Image
                im = Image.open(io.BytesIO(content_bytes))
                width, height = im.size
                if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info) or slot == "logo":
                    im_thumb = im.convert("RGBA")
                    im_thumb.thumbnail((400, 400))
                    buf = io.BytesIO()
                    im_thumb.save(buf, format="PNG")
                    thumb_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
                else:
                    im_rgb = im.convert("RGB")
                    im_rgb.thumbnail((400, 400))
                    buf = io.BytesIO()
                    im_rgb.save(buf, format="JPEG", quality=85)
                    thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            pass

        return {
            "status": "success",
            "filename": fname,
            "file_url": f"/uploads/{saved_name}",
            "file_path": str(disk_path),
            "thumbnail": thumb_b64,
            "width": width,
            "height": height,
            "slot": slot
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-logo")
async def upload_logo_endpoint(file: UploadFile = File(...)):
    """Dedicated endpoint for uploading official corporate logo."""
    return await upload_visual_endpoint(file=file, slot="logo")


@app.get("/api/sample-visuals")
def sample_visuals_endpoint():
    """List pre-packaged high-fidelity sample visual assets & templates for 1-click loading."""
    samples = [
        {
            "id": "sekawan-popout",
            "title": "Sekawan Media 2.5D Pop-Out",
            "subtitle": "Blue Polaroid Template + Studio Portrait",
            "description": "Composites raw studio portrait into Sekawan Media template in monochrome B&W with head popping out over WELCOME typography.",
            "template_url": "/test_assets/template_reference.jpg",
            "subject_url": "/test_assets/raw_subject.jpg",
            "preview_url": "/test_assets/target_ground_truth.jpg",
            "mode": "template_swap",
            "suggested_prompt": "Template swap: Replace original subject with new subject in monochrome B&W with 2.5D head pop-out over WELCOME typography"
        },
        {
            "id": "raw-portrait-only",
            "title": "Studio Portrait (Woman in Abaya)",
            "subtitle": "Raw High-Res Subject Photo",
            "description": "Clean studio portrait on plain background, ready for subject feature or template compositing.",
            "template_url": "",
            "subject_url": "/test_assets/raw_subject.jpg",
            "preview_url": "/test_assets/raw_subject.jpg",
            "mode": "feature_subject",
            "suggested_prompt": "A high-end commercial campaign portrait featuring a professional leader with studio lighting and ample negative space"
        },
        {
            "id": "template-only",
            "title": "Sekawan Media Template Graphic",
            "subtitle": "Blue Gradient Polaroid Frame",
            "description": "Official Sekawan Media graphic template with logo, header tags, WELCOME title, and nameplate box.",
            "template_url": "/test_assets/template_reference.jpg",
            "subject_url": "",
            "preview_url": "/test_assets/template_reference.jpg",
            "mode": "template_only",
            "suggested_prompt": "Official Sekawan Media team announcement graphic with clean typography and brand gradient"
        }
    ]
    return {"status": "success", "samples": samples}


@app.post("/api/upload-guidelines")
async def upload_guidelines_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None)
):
    """Extract and validate text and visual brand rules from one or multiple uploaded files concurrently (PNG, JPG, WebP, SVG, PDF, DOCX, TXT, MD, JSON)."""
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file and file not in upload_list:
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".svg"}
    studio = LexnisCampaignStudio()

    file_payloads = []
    for f in upload_list:
        fname = f.filename or "brand_asset"
        content_bytes = await f.read()
        if content_bytes:
            file_payloads.append((fname, f.content_type or "", content_bytes))

    if not file_payloads:
        raise HTTPException(status_code=400, detail="None of the uploaded files contained readable content.")

    def _process_file(payload):
        fname, content_type, content_bytes = payload
        ext = Path(fname).suffix.lower()
        is_image = ext in IMAGE_EXTENSIONS or (content_type and content_type.startswith("image/"))
        extracted_text = ""
        thumb_b64 = ""

        saved_file_url = ""
        saved_file_path = ""
        if is_image:
            f_hash = hashlib.sha1(content_bytes).hexdigest()[:12]
            clean_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(fname).stem)[:24]
            safe_ext = ext if ext in IMAGE_EXTENSIONS else '.jpg'
            saved_name = f"{clean_stem}_{f_hash}{safe_ext}"
            disk_path = UPLOADS_DIR / saved_name
            disk_path.write_bytes(content_bytes)
            saved_file_url = f"/uploads/{saved_name}"
            saved_file_path = str(disk_path)

            extracted_text = studio.extract_guidelines_from_image(content_bytes, fname, content_type)
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(content_bytes)).convert("RGB")
                im.thumbnail((360, 360))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception:
                thumb_b64 = ""
        elif ext in [".txt", ".md", ".markdown", ".json", ".csv", ".yaml", ".yml"]:
            try:
                extracted_text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                extracted_text = content_bytes.decode("latin-1", errors="ignore")
        elif ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                pages_text = [page.extract_text() or "" for page in reader.pages]
                extracted_text = "\n\n".join(pages_text).strip()
            except Exception as e:
                extracted_text = f"PDF extraction note ({fname}): {str(e)}"
        elif ext in [".docx", ".doc"]:
            try:
                import docx
                doc = docx.Document(io.BytesIO(content_bytes))
                extracted_text = "\n".join([p.text for p in doc.paragraphs if p.text]).strip()
            except Exception as e:
                extracted_text = f"Word extraction note ({fname}): {str(e)}"
        else:
            extracted_text = content_bytes.decode("utf-8", errors="ignore")

        extracted_text = extracted_text.strip()
        words = len(extracted_text.split()) if extracted_text else 0
        return {
            "filename": fname,
            "is_image": is_image,
            "image_thumbnail": thumb_b64,
            "file_url": saved_file_url,
            "file_path": saved_file_path,
            "word_count": words,
            "char_count": len(extracted_text),
            "guidelines": extracted_text
        }

    # Parallelize file extraction across multiple threads for instant uploads
    processed_files = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(file_payloads), 4)) as ex:
        futures = [ex.submit(_process_file, p) for p in file_payloads]
        for fut in futures:
            try:
                res = fut.result()
                if res.get("guidelines"):
                    processed_files.append(res)
            except Exception:
                pass

    if not processed_files:
        raise HTTPException(status_code=400, detail="None of the uploaded files contained readable content.")

    if len(processed_files) == 1:
        distilled_combined = studio.distill_guidelines(processed_files[0]["guidelines"], max_chars=1800)
    else:
        # Apportion budget across uploaded files so every file (PDFs, images) contributes its core directives
        budget_per_file = max(500, 2000 // len(processed_files))
        distilled_parts = []
        for pf in processed_files:
            file_dist = studio.distill_guidelines(pf["guidelines"], max_chars=budget_per_file)
            tag = "[IMAGE VISUAL DIRECTIVES]" if pf["is_image"] else "[BRAND DOCUMENT DIRECTIVES]"
            distilled_parts.append(f"=== {tag}: {pf['filename']} ===\n{file_dist}")
        distilled_combined = "\n\n".join(distilled_parts)

    total_words = sum(pf["word_count"] for pf in processed_files)
    primary_name = processed_files[0]["filename"] if len(processed_files) == 1 else f"{len(processed_files)} Brand Files"
    primary_img = next((pf for pf in processed_files if pf["is_image"]), None)

    # Find pdf_bytes and img_bytes from file_payloads
    first_pdf_bytes = next((b for (fn, ct, b) in file_payloads if Path(fn).suffix.lower() == ".pdf"), None)
    first_img_bytes = next((b for (fn, ct, b) in file_payloads if Path(fn).suffix.lower() in IMAGE_EXTENSIONS), None)

    # Extract structured Brand DNA directly from uploaded guidelines (highest-priority source of truth)
    brand_profile = studio.extract_brand_profile_from_guideline(
        guideline_raw_text=distilled_combined,
        pdf_bytes=first_pdf_bytes,
        image_bytes=first_img_bytes,
        filename=primary_name
    )
    if primary_img and primary_img.get("file_url"):
        brand_profile["logo_url"] = primary_img["file_url"]
        brand_profile["logo_path"] = primary_img["file_path"]
    else:
        for fname_p, ctype_p, b_payload in file_payloads:
            if Path(fname_p).suffix.lower() == ".pdf":
                extracted_logo = extract_logo_from_pdf_stream(b_payload, UPLOADS_DIR)
                if extracted_logo:
                    brand_profile["logo_url"] = extracted_logo[0]
                    brand_profile["logo_path"] = extracted_logo[1]
                    break

    return {
        "status": "success",
        "files": processed_files,
        "file_count": len(processed_files),
        "filename": primary_name,
        "is_image": any(pf["is_image"] for pf in processed_files),
        "image_thumbnail": primary_img["image_thumbnail"] if primary_img else "",
        "image_url": primary_img["file_url"] if primary_img else "",
        "image_path": primary_img["file_path"] if primary_img else "",
        "image_thumbnails": [pf["image_thumbnail"] for pf in processed_files if pf.get("image_thumbnail")],
        "word_count": total_words,
        "char_count": len(distilled_combined),
        "guidelines": distilled_combined,
        "preview": distilled_combined[:350] + ("..." if len(distilled_combined) > 350 else ""),
        "brand_dna": brand_profile,
        "profile": brand_profile
    }


@app.post("/api/analyze-layout")
async def analyze_layout_endpoint(
    image_file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None)
):
    """
    Automated Layout Decomposition & Proportional Design-Token Endpoint.
    Ingests any reference marketing graphic, reverse-engineers its structural
    hierarchy and design tokens without hardcoded magic numbers, and returns
    the TemplateBlueprint JSON and diagnostic visual overlay URL.
    """
    import time
    from layout_analyzer import TemplateLayoutAnalyzer, draw_layout_diagnostic_overlay
    try:
        img_bytes = None
        if image_file:
            img_bytes = await image_file.read()
        elif image_url:
            p = render_path(image_url)
            if p and Path(p).exists():
                img_bytes = Path(p).read_bytes()
            elif (BASE_DIR / "test_assets" / "template_reference.jpg").exists() and "template" in image_url.lower():
                img_bytes = (BASE_DIR / "test_assets" / "template_reference.jpg").read_bytes()

        if not img_bytes:
            default_tpl = BASE_DIR / "test_assets" / "template_reference.jpg"
            if default_tpl.exists():
                img_bytes = default_tpl.read_bytes()
            else:
                raise HTTPException(status_code=400, detail="An image file or valid image_url is required.")

        nparr = np.frombuffer(img_bytes, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Could not decode the provided image.")

        analyzer = TemplateLayoutAnalyzer(target_resolution=(808, 1024))
        blueprint = analyzer.analyze(img_bgr, use_vlm=False)

        diag_pil = draw_layout_diagnostic_overlay(img_bgr, blueprint)
        token = hashlib.sha1(f"layout_{time.time()}".encode()).hexdigest()[:10]
        diag_filename = f"layout_overlay_{token}.jpg"
        diag_path = RENDERS_DIR / diag_filename
        diag_pil.save(diag_path, format="JPEG", quality=95)

        latest_bp_path = RENDERS_DIR / "latest_blueprint.json"
        blueprint.save(latest_bp_path)
        static_bp = BASE_DIR / "static" / "assets" / "learned_blueprint.json"
        blueprint.save(static_bp)

        return {
            "status": "success",
            "message": "Layout successfully reverse-engineered into proportional design tokens",
            "blueprint": blueprint.to_dict(),
            "diagnostic_overlay_url": render_url(str(diag_path)),
            "elements_count": len(blueprint.elements),
            "canvas": blueprint.canvas
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/template/swap")
@app.post("/api/template-swap")
async def template_swap_endpoint(
    template_file: Optional[UploadFile] = File(None),
    subject_file: Optional[UploadFile] = File(None),
    logo_file: Optional[UploadFile] = File(None),
    template_url: Optional[str] = Form(None),
    subject_url: Optional[str] = Form(None),
    logo_url: Optional[str] = Form(None),
    person_name: Optional[str] = Form(None),
    person_title: Optional[str] = Form(None),
    brand_name: Optional[str] = Form(""),
    brand_tag: Optional[str] = Form(None),
    company_url: Optional[str] = Form(None),
    recolor_gradient: Optional[bool] = Form(False),
    language: Optional[str] = Form("en"),
    headline_text: Optional[str] = Form(None),
    footer_text: Optional[str] = Form(None),
    post_type: Optional[str] = Form("team_welcome"),
    prompt: Optional[str] = Form(""),
    brand_profile_json: Optional[str] = Form(""),
    guidelines: Optional[str] = Form(""),
    generate_companion: bool = Form(True),
    use_local_sdxl: Optional[bool] = Form(None),
):
    """
    Autonomous Template Subject-Replacement & 2.5D Pop-Out Compositing Endpoint.
    Accepts template and raw subject via file uploads or URLs.
    Executes sub-pixel hair matting, studio background decontamination,
    calibrated monochrome grading, and 2.5D pop-out layering.
    Dynamically personalizes the nameplate (person_name, person_title) and brand header.
    Adapts colors, fonts and hashtags to follow company brand guidelines and website style.
    Supports English ('en'), Arabic ('ar'), or Dual-Bilingual generation ('both').
    """
    import hashlib
    import time
    try:
        if post_type == "welcome":
            post_type = "team_welcome"
        t_bytes = None
        s_bytes = None

        if template_file:
            t_bytes = await template_file.read()
        elif template_url:
            p = render_path(template_url)
            if p and Path(p).exists():
                t_bytes = Path(p).read_bytes()
            elif (BASE_DIR / "test_assets" / "template_reference.jpg").exists() and "template" in template_url.lower():
                t_bytes = (BASE_DIR / "test_assets" / "template_reference.jpg").read_bytes()

        if subject_file:
            s_bytes = await subject_file.read()
        elif subject_url:
            p = render_path(subject_url)
            if p and Path(p).exists():
                s_bytes = Path(p).read_bytes()
            elif (BASE_DIR / "test_assets" / "raw_subject.jpg").exists() and "subject" in subject_url.lower():
                s_bytes = (BASE_DIR / "test_assets" / "raw_subject.jpg").read_bytes()

        # Fallback to test_assets if none provided
        if not t_bytes and (BASE_DIR / "test_assets" / "template_reference.jpg").exists():
            t_bytes = (BASE_DIR / "test_assets" / "template_reference.jpg").read_bytes()
        if not s_bytes and (BASE_DIR / "test_assets" / "raw_subject.jpg").exists():
            s_bytes = (BASE_DIR / "test_assets" / "raw_subject.jpg").read_bytes()

        if not t_bytes or not s_bytes:
            raise HTTPException(status_code=400, detail="Both template and subject images are required.")

        logo_image_param = None
        if logo_file:
            logo_image_param = await logo_file.read()
        elif logo_url:
            p = render_path(logo_url)
            if p and Path(p).exists():
                logo_image_param = str(p)
            elif Path(logo_url.lstrip("/\\")).exists():
                logo_image_param = str(Path(logo_url.lstrip("/\\")))
            else:
                logo_image_param = logo_url

        post_type = post_type or "team_welcome"
        prompt = prompt or ""

        # Active brand profile: Stage 1 guideline profile JSON, else parsed guideline text.
        bp: Dict[str, Any] = {}
        if brand_profile_json:
            try:
                parsed_bp = json.loads(brand_profile_json)
                if isinstance(parsed_bp, dict):
                    bp = parsed_bp
            except Exception:
                bp = {}
        # Brand resolution: guideline (profile JSON or text) > typed brand (a leftover "Lexnis Technologies"
        # is a stale default while a guideline is loaded, unless the website is lexnis.com) > prompt.
        brand_name, bp = resolve_request_brand(brand_name, bp, guidelines, prompt, company_url)
        is_lexnis_brand = "lexnis" in brand_name.lower()

        # Person: never a camera/messenger filename; fall back to the name written in the prompt.
        if post_type in ("team_welcome", "general"):
            person_name, person_title = resolve_featured_person(person_name, person_title, prompt, post_type=post_type)
        person_name = person_name or "New Team Member"
        person_title = person_title or "Team Member"

        if is_lexnis_brand or (company_url and "lexnis" in company_url.lower() and not bp.get("locked_by_guidelines")):
            recolor_gradient = True

        brand_colors = bp.get("brand_colors") if isinstance(bp.get("brand_colors"), dict) else None
        final_tag = sanitize_brand_tag(brand_tag or "", brand_name) if is_lexnis_brand else (brand_tag or None)
        target_c_url = company_url or ("https://lexnis.com" if is_lexnis_brand else "")
        if target_c_url and "lexnis" in target_c_url.lower() and not is_lexnis_brand:
            target_c_url = ""  # never pull Lexnis DNA into another brand's card
        if target_c_url and not bp.get("locked_by_guidelines"):
            try:
                studio = LexnisCampaignStudio()
                dna = studio.analyze_company_website(target_c_url, brand=brand_name or "Brand")
                if dna:
                    brand_colors = brand_colors or dna.get("brand_colors")
                    if not brand_tag and is_lexnis_brand:
                        final_tag = sanitize_brand_tag(dna.get("brand_tag") or "", brand_name)
            except Exception:
                pass

        logo_path_for_theme = logo_image_param if isinstance(logo_image_param, str) and Path(logo_image_param).exists() else None
        theme_profile = dict(bp) if bp else {}
        if brand_colors and not theme_profile.get("brand_colors"):
            theme_profile["brand_colors"] = brand_colors
        brand_theme = resolve_brand_theme(
            theme_profile or None,
            uploaded_logo_path=logo_path_for_theme,
            brand_name=brand_name,
            post_type=post_type,
        )

        primary_lang = language if language and language != "both" else "en"
        if post_type == "team_welcome" and is_unsafe_welcome_headline(headline_text):
            # Drop missing / long / LLM-sentence headlines ("LEXNIS TECHNOLOGIES WELCOMING NEW ...").
            headline_text = team_welcome_headline(brand_name, primary_lang)

        bp_path = BASE_DIR / "static" / "assets" / "learned_blueprint.json"
        bp_param = str(bp_path) if bp_path.exists() else None

        # Render primary image (1080x1350 Instagram / LinkedIn Feed master)
        result_pil = composite_template_swap(
            t_bytes,
            s_bytes,
            target_size=(1080, 1350),
            person_name=person_name,
            person_title=person_title,
            brand_name=brand_name,
            brand_tag=final_tag,
            brand_colors=brand_colors,
            recolor_gradient=bool(recolor_gradient),
            blueprint=bp_param,
            language=primary_lang,
            headline_text=headline_text,
            footer_text=footer_text,
            logo_image=logo_image_param,
            post_type=post_type,
            brand_theme=brand_theme,
            brand_profile=bp or None,
        )
        token = hashlib.sha1(f"swap_{time.time()}".encode()).hexdigest()[:12]
        out_filename = f"template_swap_{token}.jpg"
        out_path = RENDERS_DIR / out_filename
        save_welcome_animation_layers(result_pil, out_path)
        result_pil.save(out_path, format="JPEG", quality=95)

        arabic_url = None
        if language in ("ar", "both"):
            has_ar_tag = bool(brand_tag and re.search(r"[\u0600-\u06FF]", brand_tag))
            if has_ar_tag:
                ar_tag = brand_tag
            elif is_lexnis_brand:
                ar_tag = "#فريق_لكسنس"
            else:
                ar_tag = None  # compositor derives #فريق_<Brand> from the active theme
            ar_headline = headline_text if (language == "ar" and headline_text) else team_welcome_headline(brand_name, "ar")
            ar_pil = composite_template_swap(
                t_bytes,
                s_bytes,
                target_size=(1080, 1350),
                person_name=person_name,
                person_title=person_title,
                brand_name=brand_name,
                brand_tag=ar_tag,
                brand_colors=brand_colors,
                recolor_gradient=bool(recolor_gradient),
                blueprint=bp_param,
                language="ar",
                headline_text=ar_headline,
                footer_text=footer_text if (language == "ar" and footer_text) else "نحن سعداء جداً بانضمامك إلى فريقنا!",
                logo_image=logo_image_param,
                post_type=post_type,
                brand_theme=brand_theme,
                brand_profile=bp or None,
            )
            ar_filename = f"template_swap_{token}_ar.jpg"
            ar_path = RENDERS_DIR / ar_filename
            save_welcome_animation_layers(ar_pil, ar_path)
            ar_pil.save(ar_path, format="JPEG", quality=95)
            arabic_url = render_url(str(ar_path))

        companion_url = arabic_companion_url = animation_url = arabic_animation_url = ""
        if generate_companion:
            pair_req = dict(topic=prompt or f"Welcoming {person_name} to {brand_name}", post_type=post_type,
                            person_name=person_name or "", role_title=person_title or "", brand_name=brand_name,
                            use_local_sdxl=use_local_sdxl, logo_image=logo_image_param)
            if "welcome" in str(post_type) and not is_lexnis_brand:
                brand_theme.hashtag_en = f"#{brand_theme.clean_slug}Team"
                brand_theme.hashtag_ar = f"#فريق_{brand_theme.clean_slug}"
            # Match the exact tags already used by the welcome compositor.
            usable_tag = brand_tag and (is_lexnis_brand or not re.search(r"lexnis|sekawan|لكسنس", brand_tag, re.I))
            if usable_tag and not re.search(r"[\u0600-\u06FF]", brand_tag):
                brand_theme.hashtag_en = sanitize_brand_tag(brand_tag, brand_name)
            if is_lexnis_brand:
                brand_theme.hashtag_ar = ar_tag if language in ("ar", "both") else "#فريق_لكسنس"
            en_pair = generate_campaign_post(out_path, {**pair_req, "language": "en"}, brand_theme, output_path=out_path)
            companion_url = render_url(en_pair["companion_image"])
            animation_url = render_url(en_pair["animation"])
            if arabic_url:
                ar_pair = generate_campaign_post(ar_path, {**pair_req, "language": "ar"}, brand_theme, output_path=ar_path)
                arabic_companion_url = render_url(ar_pair["companion_image"])
                arabic_animation_url = render_url(ar_pair["animation"])
        primary_url = render_url(str(out_path)) if language != "ar" else arabic_url
        selected_companion_url = arabic_companion_url if language == "ar" else companion_url
        selected_animation_url = arabic_animation_url if language == "ar" else animation_url
        result = {
            "status": "ready",
            "image_url": primary_url,
            "arabic_image_url": arabic_url,
            "companion_image_url": selected_companion_url,
            "arabic_companion_image_url": arabic_companion_url,
            "animation_url": selected_animation_url,
            "arabic_animation_url": arabic_animation_url,
            "carousel_urls": [u for u in (primary_url, selected_companion_url, selected_animation_url) if u],
            "arabic_carousel_urls": [u for u in (arabic_url, arabic_companion_url, arabic_animation_url) if u],
            "message": "Template swap with 2.5D pop-out layering successfully generated",
            "dimensions": {"width": 1080, "height": 1350},
            "person_name": person_name,
            "person_title": person_title,
            "brand_name": brand_name,
            "is_lexnis": bool(brand_theme.is_lexnis),
            "brand_primary": brand_theme.primary_hex,
            "headline_text": headline_text,
            "language": language
        }
        return enrich_agency_kit(result, dict(topic=prompt or person_title or "Team welcome", post_type=post_type,
                                             person_name=person_name, role_title=person_title, language=language,
                                             headline=headline_text, logo_image=logo_image_param,
                                             tagline=bp.get("tagline", ""), brand_name_ar=bp.get("brand_name_ar", "")), brand_theme)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/render")
def render_endpoint(req: RenderRequest):
    """Re-render the visual (new seed / model / overlay) without regenerating the copy."""
    try:
        studio = LexnisCampaignStudio()
        base_img_path = None
        if req.uploaded_image_url:
            p = render_path(req.uploaded_image_url)
            if p and Path(p).exists():
                base_img_path = Path(p)

        render_res = studio.render_image(
            req.visual_prompt,
            req.seed,
            model=req.image_model or DEFAULT_IMAGE_MODEL,
            headline=req.headline or "",
            brand=req.brand or "",
            overlay=req.overlay if req.overlay is not None else True,
            output_format=req.output_format,
            tagline=req.tagline,
            arabic_headline=req.arabic_headline or "",
            arabic_tagline=req.arabic_tagline or "",
            base_image_path=base_img_path,
        )
        post_path, clean_path, watermark_free = render_res[0], render_res[1], render_res[2]
        ar_post_path = getattr(render_res, "arabic_post_path", None) or (render_res[3] if len(render_res) > 3 else getattr(studio, "last_arabic_post_path", None))
        vm = getattr(studio, "last_vision_meta", {})
        companion_url = ar_companion_url = animation_url = ar_animation_url = ""
        if req.generate_companion:
            theme = resolve_brand_theme(brand_name=req.brand or "", post_type=req.post_type)
            pair_req = dict(topic=req.campaign_context or req.visual_prompt, post_type=req.post_type,
                            role_title=req.headline or "", seed=req.seed, use_local_sdxl=req.use_local_sdxl)
            pair = generate_campaign_post(post_path, {**pair_req, "language": "en"}, theme)
            post_path, companion_url = pair["primary_card"], render_url(pair["companion_image"])
            animation_url = render_url(pair["animation"])
            if ar_post_path:
                ar_pair = generate_campaign_post(ar_post_path, {**pair_req, "language": "ar"}, theme)
                ar_post_path, ar_companion_url = ar_pair["primary_card"], render_url(ar_pair["companion_image"])
                ar_animation_url = render_url(ar_pair["animation"])
        result = {
            "image_status": "ready",
            "warnings": [],
            "image_url": render_url(str(post_path)),
            "clean_image_url": render_url(str(clean_path)),
            "arabic_image_url": render_url(str(ar_post_path)) if ar_post_path else "",
            "companion_image_url": companion_url,
            "arabic_companion_image_url": ar_companion_url,
            "animation_url": animation_url,
            "arabic_animation_url": ar_animation_url,
            "carousel_urls": [u for u in (render_url(str(post_path)), companion_url, animation_url) if u],
            "arabic_carousel_urls": [u for u in (render_url(str(ar_post_path)) if ar_post_path else "", ar_companion_url, ar_animation_url) if u],
            "post_type": req.post_type,
            "watermark_free": watermark_free,
            "seed": req.seed,
            "visual_analysis": vm.get("visual_analysis", ""),
            "visual_headline": vm.get("visual_headline", req.headline or ""),
            "visual_tagline": vm.get("visual_tagline", req.tagline or ""),
            "visual_ar_headline": vm.get("visual_ar_headline", req.arabic_headline or ""),
            "visual_ar_tagline": vm.get("visual_ar_tagline", req.arabic_tagline or ""),
        }
        if req.generate_companion:
            return enrich_agency_kit(result, dict(topic=req.campaign_context or req.visual_prompt, post_type=req.post_type,
                                                 role_title=req.headline or "", headline=req.headline or "", language="both"), theme)
        return result
    except RuntimeError as e:
        # Provider/setup failures are an expected render outcome. Preserve the copy
        # and return a state the dashboard can display without an HTTP 500.
        return {
            "image_status": "unavailable", "image_url": "", "clean_image_url": "", "arabic_image_url": "",
            "watermark_free": False, "warnings": [str(e)], "seed": req.seed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CarouselDownloadRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=3)


@app.post("/api/carousel/download")
def download_carousel(req: CarouselDownloadRequest):
    import zipfile
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
        for index, url in enumerate(req.urls, 1):
            if not re.fullmatch(r"/renders/[^/\\]+\.(?:jpg|png|webp|gif)", url, re.I):
                raise HTTPException(400, "Expected a generated image URL")
            path = RENDERS_DIR / Path(url).name
            if not path.is_file() or path.resolve().parent != RENDERS_DIR.resolve():
                raise HTTPException(404, "Carousel image not found")
            zipped.write(path, f"slide_{index:02}{path.suffix}")
    archive.seek(0)
    return StreamingResponse(archive, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="campaign-carousel.zip"'})


@app.post("/api/export")
def export_campaign_endpoint(req: ExportRequest):
    """Save the post image, clean image, caption and metadata to output/."""
    try:
        studio = LexnisCampaignStudio()
        asset = CampaignAsset(
            prompt=req.prompt,
            hook=req.hook,
            caption=req.caption,
            highlights=req.highlights,
            hashtags=req.hashtags,
            visual_prompt=req.visual_prompt,
            image_url=req.image_url,
            raw_response="",
            seed=req.seed,
            search_results=req.search_results or [],
            brand=req.brand or "",
            cta=req.cta or "",
            image_headline=req.image_headline or "",
            alt_text=req.alt_text or "",
            instagram_caption=req.instagram_caption or "",
            image_model=req.image_model or DEFAULT_IMAGE_MODEL,
            image_path=render_path(req.image_url),
            clean_image_path=render_path(req.clean_image_url or ""),
            arabic_image_path=render_path(req.arabic_image_url or "") if req.arabic_image_url else "",
            companion_image_path=render_path(req.companion_image_url),
            arabic_companion_image_path=render_path(req.arabic_companion_image_url),
            animation_path=render_path(req.animation_url),
            arabic_animation_path=render_path(req.arabic_animation_url),
            agent_dialogue=req.agent_dialogue or [],
            critique_notes=req.critique_notes or [],
            enhanced_prompt=req.enhanced_prompt or "",
            output_format=req.output_format, image_status=req.image_status, warnings=req.warnings,
            rivals=req.rivals or [],
            competitive_strategy=req.competitive_strategy or {},
            visual_analysis=req.visual_analysis or "",
            visual_headline=req.visual_headline or "",
            visual_tagline=req.visual_tagline or "",
            arabic=req.arabic or {},
            guidelines=req.guidelines or "",
        )
        saved_files = studio.export_campaign(asset, output_dir=str(BASE_DIR / "output"))
        return {
            "status": "success",
            "message": "Campaign assets successfully exported to disk",
            "files": saved_files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  LEXNIS CAMPAIGN STUDIO - AI MARKETING AGENCY SERVER")
    print("  Serving Dashboard at: http://localhost:8000")
    print("  API Documentation at: http://localhost:8000/docs")
    print("=" * 60 + "\n")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
