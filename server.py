"""
Lexnis Campaign Studio - FastAPI Backend Server
================================================
Serves the web UI and provides the AI marketing agency endpoints.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
app.mount("/renders", StaticFiles(directory=RENDERS_DIR), name="renders")


def render_url(path: str) -> str:
    return f"/renders/{Path(path).name}"


def render_path(url: str) -> str:
    """Map a /renders/... URL from the UI back to the file on disk."""
    if url and url.startswith("/renders/"):
        p = RENDERS_DIR / Path(url.split("?")[0]).name
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


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., description="Vague, simple or conversational prompt to elevate")
    brand: Optional[str] = Field("Lexnis Technologies", description="Current brand field (if any)")


class RenderRequest(BaseModel):
    visual_prompt: str
    seed: int
    image_model: Optional[str] = DEFAULT_IMAGE_MODEL
    headline: Optional[str] = ""
    brand: Optional[str] = ""
    overlay: Optional[bool] = True


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
    search_results: Optional[List[Dict[str, Any]]] = None
    agent_dialogue: Optional[List[Dict[str, Any]]] = None
    critique_notes: Optional[List[str]] = None
    enhanced_prompt: Optional[str] = ""


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
    return {
        "status": "online",
        "engine": "Lexnis Campaign Studio (AI Marketing Agency)",
        "text_engine": f"{studio.text_engine}:{studio.model}",
        "search_engine": "Google Search + page scraping (free)",
        "visual_engine": "Pollinations gen API" if studio.pollinations_key else "Pollinations anonymous (watermarked)",
        "watermark_free": bool(studio.pollinations_key),
        "image_models": IMAGE_MODELS,
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
    """Transform simple or conversational requests into Fortune-500 executive briefs."""
    try:
        studio = LexnisCampaignStudio()
        result = studio.enhance_user_prompt(req.prompt, req.brand)
        return {
            "original_prompt": req.prompt,
            "enhanced_prompt": result.get("enhanced_prompt", req.prompt),
            "detected_brand": result.get("detected_brand", req.brand or "Lexnis Technologies"),
            "product_name": result.get("product_name", ""),
            "suggested_tone": result.get("suggested_tone", "confident, visionary and disruptive"),
            "suggested_theme": result.get("suggested_theme", "Apple Minimalist Hero (Luxury Tech)")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate")
def generate_campaign_endpoint(req: GenerateRequest):
    """Research -> brief -> Instagram copy -> watermark-free visual."""
    try:
        studio = LexnisCampaignStudio()
        asset: CampaignAsset = studio.generate_campaign(
            prompt=req.prompt,
            brand=req.brand or "Lexnis Technologies",
            tone=req.tone,
            theme=req.theme,
            seed=req.seed,
            use_search=req.use_search if req.use_search is not None else True,
            image_model=req.image_model or DEFAULT_IMAGE_MODEL,
            enhance_image=req.enhance_image if req.enhance_image is not None else True
        )
        data = asset.to_dict()
        data["image_url"] = render_url(asset.image_path)
        data["clean_image_url"] = render_url(asset.clean_image_path)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/render")
def render_endpoint(req: RenderRequest):
    """Re-render the visual (new seed / model / overlay) without regenerating the copy."""
    try:
        studio = LexnisCampaignStudio()
        post_path, clean_path, watermark_free = studio.render_image(
            req.visual_prompt,
            req.seed,
            model=req.image_model or DEFAULT_IMAGE_MODEL,
            headline=req.headline or "",
            brand=req.brand or "",
            overlay=req.overlay if req.overlay is not None else True,
        )
        return {
            "image_url": render_url(str(post_path)),
            "clean_image_url": render_url(str(clean_path)),
            "watermark_free": watermark_free,
            "seed": req.seed,
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
            agent_dialogue=req.agent_dialogue or [],
            critique_notes=req.critique_notes or [],
            enhanced_prompt=req.enhanced_prompt or "",
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
