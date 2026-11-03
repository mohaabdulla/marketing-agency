"""
Lexnis Campaign Studio - FastAPI Backend Server
================================================
Serves the web UI and provides the AI marketing agency endpoints.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
import os
import io
import base64
import concurrent.futures
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from visual_engine import model_setup, preferred_local_model

from campaign_generator import (
    LexnisCampaignStudio, CampaignAsset, IMAGE_MODELS, DEFAULT_IMAGE_MODEL, RENDERS_DIR,
)

app = FastAPI(
    title="Lexnis Campaign Studio API",
    description="AI marketing agency: web research, Instagram copy and watermark-free visuals",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = BASE_DIR / "output" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/renders", StaticFiles(directory=RENDERS_DIR), name="renders")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def render_url(path: str) -> str:
    if not path:
        return ""
    p = Path(path)
    if "uploads" in p.parts:
        return f"/uploads/{p.name}"
    return f"/renders/{p.name}"


def render_path(url: str) -> str:
    """Map a /renders/... or /uploads/... URL from the UI back to the file on disk."""
    path = urlsplit(url).path if url else ""
    if path.startswith("/renders/"):
        p = RENDERS_DIR / Path(path).name
        if p.exists():
            return str(p)
    elif path.startswith("/uploads/"):
        p = UPLOADS_DIR / Path(path).name
        if p.exists():
            return str(p)
    return ""


class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Product, offer or campaign concept")
    brand: Optional[str] = Field("Lexnis Technologies", description="Brand name")
    tone: Optional[str] = Field(None, description="Marketing tone")
    theme: Optional[str] = Field(None, description="Visual direction")
    seed: Optional[int] = Field(None, description="Image seed")
    use_search: Optional[bool] = Field(True, description="Enable web research")
    image_model: Optional[str] = Field(DEFAULT_IMAGE_MODEL, description="Image model id")
    enhance_image: Optional[bool] = Field(True, description="Headline + brand overlay on the image")
    output_format: Literal["portrait", "landscape", "square"] = "portrait"
    guidelines: Optional[str] = Field("", description="Client brand guidelines, style guide, or strategic constraints")
    uploaded_image_url: Optional[str] = Field(None, description="URL of uploaded image asset to composite as ad visual")
    use_uploaded_image: Optional[bool] = Field(None, description="Whether to feature the uploaded image as the ad visual")


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., description="Vague, simple or conversational prompt to elevate")
    brand: Optional[str] = Field("Lexnis Technologies", description="Current brand field (if any)")
    guidelines: Optional[str] = Field("", description="Client brand guidelines or strategic constraints")
    style_preset: Optional[str] = Field("", description="Optional creative style or prompt flavor")


class RenderRequest(BaseModel):
    visual_prompt: str
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
        )
        return {
            "status": "success",
            "original_prompt": req.prompt,
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


@app.post("/api/generate")
def generate_campaign_endpoint(req: GenerateRequest):
    """Research -> brief -> Instagram copy -> watermark-free visual."""
    try:
        studio = LexnisCampaignStudio()
        up_img_path = None
        if req.uploaded_image_url:
            p = render_path(req.uploaded_image_url)
            if p and Path(p).exists():
                up_img_path = p

        asset: CampaignAsset = studio.generate_campaign(
            prompt=req.prompt,
            brand=req.brand or "Lexnis Technologies",
            tone=req.tone,
            theme=req.theme,
            seed=req.seed,
            use_search=req.use_search if req.use_search is not None else True,
            image_model=req.image_model or DEFAULT_IMAGE_MODEL,
            enhance_image=req.enhance_image if req.enhance_image is not None else True,
            output_format=req.output_format,
            guidelines=req.guidelines or "",
            uploaded_image_path=up_img_path,
            use_uploaded_image=req.use_uploaded_image,
        )
        data = asset.to_dict()
        data["image_url"] = render_url(asset.image_path)
        data["clean_image_url"] = render_url(asset.clean_image_path)
        data["arabic_image_url"] = render_url(asset.arabic_image_path)
        data["uploaded_image_url"] = render_url(asset.uploaded_image_url)
        data["uploaded_arabic_url"] = render_url(asset.uploaded_arabic_url)
        data["ai_image_url"] = render_url(asset.ai_image_url)
        data["ai_arabic_url"] = render_url(asset.ai_arabic_url)
        data["has_uploaded_asset"] = bool(asset.uploaded_image_url)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        "preview": distilled_combined[:350] + ("..." if len(distilled_combined) > 350 else "")
    }


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
        return {
            "image_status": "ready",
            "warnings": [],
            "image_url": render_url(str(post_path)),
            "clean_image_url": render_url(str(clean_path)),
            "arabic_image_url": render_url(str(ar_post_path)) if ar_post_path else "",
            "watermark_free": watermark_free,
            "seed": req.seed,
            "visual_analysis": vm.get("visual_analysis", ""),
            "visual_headline": vm.get("visual_headline", req.headline or ""),
            "visual_tagline": vm.get("visual_tagline", req.tagline or ""),
            "visual_ar_headline": vm.get("visual_ar_headline", req.arabic_headline or ""),
            "visual_ar_tagline": vm.get("visual_ar_tagline", req.arabic_tagline or ""),
        }
    except RuntimeError as e:
        # Provider/setup failures are an expected render outcome. Preserve the copy
        # and return a state the dashboard can display without an HTTP 500.
        return {
            "image_status": "unavailable", "image_url": "", "clean_image_url": "", "arabic_image_url": "",
            "watermark_free": False, "warnings": [str(e)], "seed": req.seed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
