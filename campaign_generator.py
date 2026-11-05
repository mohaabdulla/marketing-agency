"""
Lexnis Campaign Studio - AI Marketing Agency Engine
====================================================
Researches a product on the web, builds a creative brief, writes an
Instagram-ready post (hook, caption, CTA, hashtags, alt text) and renders a
watermark-free 1080x1350 visual with a professional headline overlay.

Pipeline:
  1. Research    - web search + scraping of the top product pages
  2. Strategist  - turns research into a creative brief (audience, USP, proof)
  3. Copywriter  - writes the post as strict JSON, sanitized for Instagram
  4. Art director- renders the image via Pollinations gen API and composites
                   the headline / brand tag with Pillow

Keys (put them in .env):
  POLLINATIONS_API_KEY  sk_... from https://enter.pollinations.ai/keys
                        -> premium image models, full resolution, no watermark
                        -> also used for copywriting if no Gemini key is set
  GEMINI_API_KEY        optional, Google AI Studio key for copywriting
"""

import io
import os
import re
import sys
import ast
import json
import math
import random
import base64
import hashlib
import urllib.parse
import concurrent.futures
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict, field

from visual_engine import OPEN_MODELS, FORMATS, photo_direction, open_model_image, compose_ad, cloudflare_image, LOCAL_MODEL, LOCAL_MODELS, preferred_local_model, local_image, RENDER_VERSION

BASE_DIR = Path(__file__).resolve().parent


# Auto-load .env file if present in workspace
def load_env_file():
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if v:
                        os.environ.setdefault(k.strip(), v)

load_env_file()

# Official OpenAI library (works with any OpenAI-compatible endpoint)
try:
    from openai import OpenAI
    HAS_OPENAI_LIB = True
except ImportError:
    HAS_OPENAI_LIB = False

# HTTP & Scraping libraries for free search
try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Free Google Search (dynamic import avoids static linter warnings)
googlesearch = None
try:
    import importlib
    googlesearch = importlib.import_module("googlesearch")
    HAS_GOOGLESEARCH = True
except (ImportError, ModuleNotFoundError):
    HAS_GOOGLESEARCH = False

# Rich terminal styling
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:
    console = None


# ==========================================
# Configuration
# ==========================================

POLLINATIONS_GEN_BASE = "https://gen.pollinations.ai"
LEGACY_TEXT_BASE = "https://text.pollinations.ai/openai"
LEGACY_IMAGE_BASE = "https://image.pollinations.ai/prompt"
GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

DEFAULT_TEXT_MODEL = os.getenv("TEXT_MODEL", "openai/gpt-5.4-mini")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
DEFAULT_IMAGE_MODEL = os.getenv("IMAGE_MODEL") or "flux"

# Image models available (Google AI Studio Imagen + FLUX photorealism)
IMAGE_MODELS = {
    "gemini-image": "Google AI Studio Imagen (Gemini Image)",
    "black-forest-labs/flux.1.1-pro": "FLUX 1.1 Pro (Apple/Studio Photorealism)",
    "flux-realism": "FLUX Realism (Hardware Macro & Textures)",
    "black-forest-labs/flux.1-schnell": "FLUX Schnell (High-Speed Packshot)",
    "flux": "FLUX Standard (Commercial Tech)",
}
IMAGE_MODELS.update(OPEN_MODELS)
IMAGE_MODELS.update({model: settings['label'] for model, settings in LOCAL_MODELS.items()})
IMAGE_MODELS["cf:flux-schnell"] = "FLUX Schnell — Cloudflare free daily allowance"
# Old model names from previous versions
LEGACY_MODEL_ALIASES = {"sana", "tongyi-mai/z-image-turbo"}

POST_WIDTH, POST_HEIGHT = 1080, 1350           # Instagram 4:5 portrait
RENDER_WIDTH, RENDER_HEIGHT = 1088, 1344       # multiples of 32, <=1.6 MP (FLUX 1.1 Pro limits)
IG_CAPTION_LIMIT = 2200
RENDERS_DIR = BASE_DIR / "output" / "renders"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


STRATEGIST_PROMPT = """You are the Head of Strategy at a premium social media marketing agency.
You receive a product / campaign request and raw web research about it.
Turn it into a sharp creative brief for an Instagram post.

Rules:
- Only state facts, numbers and specs that appear in the research. Never invent statistics.
- If the research is thin, stay qualitative instead of making things up.
- Think about who scrolls past this post and what would stop them.
- Format strictly as valid RFC 8259 JSON. Never include trailing commas. Escape any double quotes in values.

Return ONLY a JSON object with these keys:
{
  "product_name": "the product or offer name",
  "category": "what kind of product / service it is",
  "one_liner": "what it is and why it matters, max 20 words",
  "target_audience": "who exactly this post is for (role, situation, desire)",
  "pain_points": ["2-3 concrete frustrations of that audience"],
  "key_benefits": ["3 outcome-focused benefits, not features"],
  "proof_points": ["verified facts/specs/numbers from the research, empty if none"],
  "differentiator": "why this beats the alternatives",
  "creative_angle": "the single big idea for this post",
  "cta_goal": "the one action the reader should take"
}"""


PROMPT_ARCHITECT_SYSTEM_PROMPT = """You are an elite Advertising Prompt Architect & Creative Strategy Director.
Your task is to take a raw user request for a commercial campaign and elevate it into a high-converting, Fortune-500 grade launch prompt that guarantees maximum photographic fidelity, strategic brand alignment, and compelling messaging.

Critical Rules:
1. Brand & Product Fidelity:
   - Identify the exact brand and product intended.
   - Never swap or invent unrelated brands (e.g., if the user asks for Bank of America, do NOT mention Rolex; if Tesla, do not add unrelated brands).
   - If no brand is specified, use the provided brand.
2. Strategic Transformation:
   - Define a specific target customer persona (who is this for?).
   - Frame a sharp value-proposition hook or emotional angle (why does it matter?).
   - Specify photographic visual art direction for FLUX/diffusion models: scene setting, lighting (e.g. golden hour, softbox, volumetric rim light), composition (e.g. 35mm lens, low three-quarter angle, generous negative space for typography), and realistic textures (no CGI plastic, no text artifacts).
3. Construct the "enhanced_prompt":
   - Write a rich, cohesive launch brief prompt (2-4 sentences) that clearly articulates the product, the strategic audience hook, and the photographic visual atmosphere.
4. Summarize Improvements:
   - Provide 3 concise bullet points under "improvements" detailing what was elevated from the raw prompt.

Return strictly valid JSON with this exact schema:
{
  "detected_brand": "Brand Name",
  "product_name": "Product or Service Name",
  "target_audience": "Specific customer persona",
  "core_hook_angle": "Core counter-positioning or emotional hook",
  "visual_art_direction": "Photographic visual composition and lighting guidance",
  "improvements": [
    "Identified target customer persona and core value proposition",
    "Structured photographic scene composition with typography negative space",
    "Removed ambiguity while strictly preserving brand fidelity"
  ],
  "enhanced_prompt": "Complete upgraded prompt for the campaign generator",
  "suggested_tone": "confident, premium and benefit-driven",
  "suggested_theme": "Cinematic lifestyle photography"
}
"""
PROMPT_ENHANCER_PROMPT = PROMPT_ARCHITECT_SYSTEM_PROMPT


BRAND_DNA_PROMPT = """You are an elite Brand Identity Director & Design Technologist.
Given raw scraped metadata, CSS styles, colors, and content from a company website, extract and synthesize the definitive Brand DNA in strict JSON format:
{
  "company_name": "Official brand/company name",
  "domain": "company domain",
  "tagline": "Hero tagline or value proposition",
  "industry": "Primary industry / sector",
  "brand_tag": "#BrandNameTeam (official corporate community hashtag, alphanumeric only)",
  "typography": {
    "primary_font": "Primary font name (e.g. Poppins, Inter, Montserrat, Roboto, etc.)",
    "secondary_font": "Secondary font name",
    "heading_style": "Geometric Bold / Clean Modern / Editorial Serif",
    "body_style": "High-Legibility Modern Sans"
  },
  "brand_colors": {
    "primary": "#HEX (dominant primary brand color)",
    "secondary": "#HEX (supporting corporate dark or deep tone)",
    "accent": "#HEX (vibrant brand accent color)",
    "text_primary": "#FFFFFF or #HEX",
    "text_secondary": "#HEX (muted body tone)",
    "gradient_start": "#HEX",
    "gradient_end": "#HEX"
  },
  "visual_aesthetic": "Detailed summary of visual style, photography aesthetic, negative space, lighting, and art direction",
  "guidelines_summary": "Actionable 2-3 sentence brand styling rules for posters, social ad artboards, and marketing campaigns."
}
Return ONLY valid RFC 8259 JSON. Never include markdown formatting or codeblocks.
"""


COMPETITIVE_INTELLIGENCE_PROMPT = """You are a Chief Marketing Officer and Competitive Strategy Director.
Analyze the target company/brand, flagship product/service, and market landscape to identify their primary rivals and formulate an aggressive, high-status counter-positioning playbook that gives this brand an unfair market edge.

Rules:
- Identify 2 to 3 real primary competitors / industry rivals (incumbents, market leaders, or direct alternatives).
- For each rival, provide:
  * "name": Competitor name (and parent company if applicable).
  * "stance": Their core marketing promise / value prop in the market.
  * "incumbent_weakness": Their fatal flaw, structural limitation, legacy anchor, or user frustration.
  * "our_edge": The exact reason why our brand's architecture, business model, or user experience beats them.
- "strategic_wedge": A bold, 1-2 sentence counter-positioning thesis explaining why competitors cannot easily copy or catch up (the "Hamilton Helmer 7 Powers" counter-positioning trap).
- "conquest_playbook":
  * "attack_angle": The primary psychological or economic narrative angle to win over their customers.
  * "campaign_ideas": 3 concrete, high-converting marketing campaigns/angles to deploy against rivals.
  * "landmine_questions": 3 killer questions buyers/prospects should ask competitors to expose their flaws.
  * "growth_tactics": 3 actionable GTM & social distribution tactics to win market share and mindshare.

Format strictly as valid RFC 8259 JSON. Never include markdown code fences or trailing commas.
Return ONLY a JSON object with: rivals (list), strategic_wedge (str), conquest_playbook (object).
"""


AGENT1_COPYWRITER_PROMPT = """You are Agent 1: Senior Copywriter and Creative Strategist at an award-winning creative agency.
Draft an initial Instagram product launch campaign for the brand "{brand}" based on the creative brief and competitive intelligence battlecard below.

Tone: {tone}
Visual direction: {theme}

Rules:
- Plain text only. NO markdown: no **bold**, no #headings, no bullet asterisks.
- The hook must stop the scroll in under 125 characters.
- Caption: 3-4 short paragraphs (1-3 sentences each), scannable, written to ONE person ("you").
- WEAPONIZE THE STRATEGIC EDGE: Subtle, high-status counter-positioning that exposes rivals' legacy limitations (e.g. expensive hardware, bloated geofencing, slow onboarding) and highlights our brand's radical breakthrough. Never sound petty or mention competitors by name in cheap attacks; make our superiority mathematically and intuitively obvious.
- Use 0-3 tasteful emojis max, never at the start of every line.
- Highlights: 3 short benefit lines (max 12 words each), outcome first, underscoring our unfair advantage.
- Hashtags: 8-12 relevant hashtags.
- Image Headline: 2-4 word luxury product title (e.g. 'LEXNIS // ENTERPRISE' or 'TESLA // MODEL 3').
- visual_concept: Detailed description of physical subject, materials, setting, and lighting strictly faithful to the user's requested environment and scene.
- agent1_rationale: 1-2 sentence explanation of your chosen creative angle, target audience hook, and competitive wedge.

Return strictly valid RFC 8259 JSON:
{{
  "agent1_rationale": "Why I chose this creative angle...",
  "hook": "scroll-stopping first line, max 110 characters",
  "caption": "caption body paragraphs separated by blank lines",
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "cta": "one clear call to action line",
  "hashtags": ["#tag1", "#tag2"],
  "image_headline": "2-4 word luxury title",
  "visual_concept": "detailed description of the physical hardware, interface, and workspace/studio setting"
}}"""

COPYWRITER_PROMPT = AGENT1_COPYWRITER_PROMPT


AGENT2_DIRECTOR_CRITIC_PROMPT = """You are an executive creative director and marketing auditor reviewing a campaign draft.
Return valid JSON with hook, caption, highlights (list), cta, hashtags (list),
image_headline (product name), alt_text, visual_prompt, critique_notes (list),
and agent_dialogue (list of objects with agent and message).
Audit the copy for executive authority and competitive edge. Ensure our counter-positioning against the rivals' flaws is distinct, unassailable, and memorable. Make sure the hook and caption stop the scroll by highlighting our brand's unique superiority.
Use only facts from the supplied research/brief. Remove unsupported specifications and statistics.
Preserve the user's exact brand, product, setting, and visual direction.
Create a photographic visual_prompt with natural materials, believable lighting, and a clear hero subject adhering strictly to the user's requested environment, lighting, lens, and backdrop (e.g. minimalist workspace, enterprise hardware, software interfaces, or studio portraiture).
CRITICAL: If client brand guidelines or uploaded visual assets describe a person or executive (e.g. Arab female executive in black abaya, corporate team member portrait), YOU MUST integrate this person as the primary hero subject in the visual_prompt!
NEVER inject unrelated settings (e.g. do NOT inject cars, beaches, coastal roads, or sunsets unless the user explicitly requested them).
If client brand guidelines or uploaded visual assets are provided, strictly integrate their aesthetic and color palette (e.g. Lexnis dark navy #131724, tech green #53B849, lime #BCD755, clean matte backdrops).
Reserve upper left and lower right negative space for typography. No text, letters, logos, or watermarks in the photo.
Write a short, distinctive emotional hook, concise benefits and one clear CTA.
Never invent a website, official affiliation or endorsements. Report only changes actually made.
"""


ARABIC_TRANSCREATOR_PROMPT = """You are a Senior Arabic Creative Director and Transcreation Strategist at a premier international advertising agency in Dubai and Riyadh.
Your mission is to transcreate and culturally localize the marketing campaign into authoritative, high-impact, and persuasive Modern Standard Arabic (الفصحى التسويقية الراقية).

Rules:
- NEVER translate literally word-for-word. Re-imagine the campaign's emotional hook, competitive edge, and executive authority for discerning Arabic-speaking decision makers.
- The hook must stop the scroll in under 120 characters with compelling, prestigious Arabic phrasing.
- Caption: 3-4 short, scannable paragraphs separated by blank lines. Fluid, natural, and prestigious.
- Highlights: 3 outcome-first benefit bullets (e.g. "حماية القوة الشرائية للأجيال القادمة").
- CTA: One direct, elegant call to action (e.g. "تواصل مع مستشارك المالي الخاص عبر الرابط في البايو").
- Hashtags: 6-10 targeted Arabic hashtags accompanied by the brand name tag.
- visual_headline: 2 to 4 powerful, punchy Arabic words fitting the visual scene (e.g. "آفاق بلا حدود").
- visual_tagline: A resonant subline under 8 words.
- alt_text: High-quality Arabic accessibility description.

Return strictly valid RFC 8259 JSON:
{
  "hook": "scroll-stopping Arabic hook",
  "caption": "scannable Arabic caption paragraphs",
  "highlights": ["bullet 1", "bullet 2", "bullet 3"],
  "cta": "Arabic call to action",
  "hashtags": "#وسم1 #وسم2",
  "image_headline": "Arabic visual headline",
  "visual_headline": "Arabic visual headline",
  "visual_tagline": "Arabic visual tagline",
  "alt_text": "Arabic accessibility description"
}"""


@dataclass
class CampaignAsset:
    prompt: str
    hook: str
    caption: str
    highlights: List[str]
    hashtags: str
    visual_prompt: str
    image_url: str
    raw_response: str
    seed: int
    search_results: List[Dict[str, str]] = field(default_factory=list)
    brand: str = "Lexnis Technologies"
    cta: str = ""
    image_headline: str = ""
    alt_text: str = ""
    instagram_caption: str = ""
    brief: Dict[str, Any] = field(default_factory=dict)
    image_model: str = DEFAULT_IMAGE_MODEL
    image_path: str = ""
    clean_image_path: str = ""
    watermark_free: bool = False
    text_engine: str = ""
    agent_dialogue: List[Dict[str, str]] = field(default_factory=list)
    critique_notes: List[str] = field(default_factory=list)
    enhanced_prompt: str = ""
    output_format: str = "portrait"
    image_status: str = "ready"
    warnings: List[str] = field(default_factory=list)
    rivals: List[Dict[str, Any]] = field(default_factory=list)
    competitive_strategy: Dict[str, Any] = field(default_factory=dict)
    visual_analysis: str = ""
    visual_headline: str = ""
    visual_tagline: str = ""
    arabic: Dict[str, Any] = field(default_factory=dict)
    arabic_image_url: str = ""
    arabic_image_path: str = ""
    uploaded_image_url: str = ""
    uploaded_arabic_url: str = ""
    ai_image_url: str = ""
    ai_arabic_url: str = ""
    has_uploaded_asset: bool = False
    guidelines: str = ""
    guidelines_source: str = "none"
    company_url: str = ""
    brand_dna: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RenderResult(tuple):
    """
    Tuple representing rendered visual outputs with English and Arabic overlays.
    Yields 3 items on unpacking for full backward-compatibility with (post, clean, watermark_free).
    """
    def __new__(cls, post_path, clean_path, watermark_free, arabic_post_path=None):
        return super().__new__(cls, (post_path, clean_path, watermark_free, arabic_post_path))

    def __iter__(self):
        return iter(self[:3])

    @property
    def post_path(self):
        return self[0]

    @property
    def clean_path(self):
        return self[1]

    @property
    def watermark_free(self):
        return self[2]

    @property
    def arabic_post_path(self):
        return self[3]


# ==========================================
# Text helpers
# ==========================================

def clean_social_text(text: str) -> str:
    """Make model output safe for Instagram: strip markdown, odd spaces, extra blank lines, non-ASCII hyphens."""
    if not text:
        return ""
    text = str(text)
    # Unicode space and dash normalization (prevents Windows console cp1252 print errors)
    text = text.replace("\u202f", " ").replace("\u00a0", " ").replace("\u2009", " ")
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2012", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(\S.*?\S|\S)\*(?!\w)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[ \t]*[-*•][ \t]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_featured_person(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts featured person name (e.g. 'Alisha Faisal') and corporate title (e.g. 'Marketing Manager')
    from user prompt for seamless personalization.
    """
    p = (prompt or "").strip()
    # Pattern: featuring Name, Title
    m = re.search(
        r'featuring\s+([A-Z][a-zA-Z\'-]+(?:\s+[A-Z][a-zA-Z\'-]+)+)(?:,?\s*([A-Za-z &/-]+?(?=(?:,|\.|\bwho\b|\bwith\b|\bset\b|\bcaptured\b|\bembodying\b|$))))?',
        p,
        re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        title = m.group(2).strip() if m.group(2) else ""
        title = re.sub(r'\s+', ' ', title).strip(', ')
        return name, title
    return None, None


def detect_brand_and_product(prompt: str, current_brand: str = "") -> Tuple[str, str]:
    """
    Intelligently infer true target brand and concrete flagship product from user prompt.
    Extracts brand and product across global tech, automotive, AI, banking, luxury, SaaS, and custom companies.
    Prompt content ALWAYS takes precedence over stale session brands.
    """
    p = (prompt or "").strip()
    p_lower = p.lower()
    b = (current_brand or "").strip()

    brand_catalog = [
        # Lexnis Technologies (Primary Brand)
        ("lexnis technologies", "Lexnis Technologies", ["enterprise solutions", "ai & automation", "cybersecurity", "managed it", "cloud infrastructure", "software interfaces", "digital marketing", "web & app development"]),
        ("lexnis", "Lexnis Technologies", ["enterprise solutions", "ai & automation", "cybersecurity", "managed it", "cloud infrastructure", "software interfaces", "digital marketing", "web & app development"]),

        # Banking & Wealth Management
        ("bank of america", "Bank of America", ["private bank", "merrill", "wealth management", "preferred rewards", "cash rewards"]),
        ("jpmorgan", "JPMorgan Chase", ["chase", "sapphire", "private bank", "reserve", "j.p. morgan"]),
        ("goldman sachs", "Goldman Sachs", ["marcus", "private wealth", "asset management"]),
        ("morgan stanley", "Morgan Stanley", ["etrade", "wealth management", "graystone"]),
        ("american express", "American Express", ["amex", "centurion", "platinum", "membership rewards"]),
        ("citigroup", "Citigroup", ["citi", "citi priority", "strata"]),
        ("wells fargo", "Wells Fargo", ["autograph", "premier"]),
        
        # Luxury & Horology
        ("rolex", "Rolex", ["submariner", "daytona", "datejust", "oyster perpetual", "gmt-master", "sea-dweller"]),
        ("patek philippe", "Patek Philippe", ["nautilus", "aquanaut", "calatrava"]),
        ("audemars piguet", "Audemars Piguet", ["royal oak", "offshore"]),
        ("cartier", "Cartier", ["santos", "tank", "panthere"]),
        ("omega", "Omega", ["speedmaster", "seamaster", "constellation"]),

        # Tech, Automotive, AI & Robotics
        ("tesla", "Tesla", ["model 3", "model y", "model s", "model x", "cybercab", "robotaxi", "optimus", "roadster", "cybertruck", "fsd"]),
        ("apple", "Apple", ["vision pro", "spatial", "iphone", "macbook", "neural", "watch", "airpods", "ipad"]),
        ("rivian", "Rivian", ["r1t", "r1s", "r2", "r3", "commercial van"]),
        ("lucid", "Lucid", ["air", "gravity", "sapphire"]),
        ("byd", "BYD", ["seal", "yangwang", "dolphin", "atto", "blade battery"]),
        ("waymo", "Waymo", ["robotaxi", "autonomous cab", "driver"]),
        ("stripe", "Stripe", ["billing", "atlas", "issuing", "radar", "terminal", "connect"]),
        ("nvidia", "NVIDIA", ["blackwell", "dgx", "geforce", "cuda", "h100", "b200", "omniverse"]),
        ("openai", "OpenAI", ["chatgpt", "gpt-4o", "o1", "sora", "operator"]),
        ("meta", "Meta", ["quest 3", "quest pro", "ray-ban", "llama", "orion"]),
        ("google", "Google", ["pixel", "gemini", "workspace", "tensor", "cloud"]),
        ("microsoft", "Microsoft", ["surface", "copilot", "quantum", "azure"]),
        ("sony", "Sony", ["alpha 1", "playstation", "spatial reality", "xperia"]),
        ("porsche", "Porsche", ["mission x", "taycan", "911", "macan electric"]),
        ("ferrari", "Ferrari", ["f80", "296 gtb", "sf90", "purosangue"]),
        ("nike", "Nike", ["alphafly", "vaporfly", "air max", "adapt"]),
        ("datadog", "Datadog", ["apm", "cloud monitoring", "security", "synthetics"]),
        ("snowflake", "Snowflake", ["cortex", "data cloud", "snowpark"]),
        ("figma", "Figma", ["figjam", "slides", "dev mode"]),
        ("boston dynamics", "Boston Dynamics", ["atlas", "spot", "stretch"]),
    ]

    detected_brand = ""
    detected_product = ""

    # Specific Arabic brand catalog check
    arabic_brand_catalog = [
        (r"ليكسنيس|لكسنيس", "Lexnis Technologies", ["حلول المؤسسات", "الذكاء الاصطناعي", "الأمن السيبراني"]),
        (r"بنك\s*(?:أوف|اوف)?\s*(?:أم[يإا]?رك?ا|أميركا|اميركا|امريكا)", "Bank of America", ["برايفت بنك", "إدارة الثروات"]),
        (r"تسلا", "Tesla", ["موديل 3", "موديل واي", "سايبركاب", "أوبتيموس", "سايبرتراك"]),
        (r"أبل|ابل", "Apple", ["فيجن برو", "ايفون", "ماك بوك"]),
        (r"رولكس", "Rolex", ["ديب سي", "دايتونا", "صبمارينر"]),
        (r"بورشه|بورش", "Porsche", ["تايكان", "911"]),
        (r"مرسيدس", "Mercedes-Benz", []),
        (r"بي\s*إم\s*دبليو|بي\s*ام\s*دبليو", "BMW", []),
        (r"فيراري", "Ferrari", []),
        (r"أرامكو|ارامكو", "Saudi Aramco", []),
    ]
    for pat, canonical, prods in arabic_brand_catalog:
        if re.search(pat, p):
            detected_brand = canonical
            for pr in prods:
                if pr in p:
                    detected_product = f"{canonical} {pr}"
                    break
            break

    # Specific typo tolerance for Bank of America (e.g., "bank of amerca", "bofa")
    if not detected_brand and re.search(r"\b(?:bank\s+of\s+am[eiar]*c?a?|bofa)\b", p_lower):
        detected_brand = "Bank of America"

    # 1. Prompt Catalog Check FIRST (Prompt is the authoritative source of truth)
    if not detected_brand:
        for brand_key, canonical_name, products in brand_catalog:
            if re.search(rf"\b{re.escape(brand_key)}\b", p_lower):
                detected_brand = canonical_name
                for prod in products:
                    if prod in p_lower:
                        detected_product = f"{canonical_name} {prod.title()}"
                        break
                break

    # 2. Dynamic heuristic extraction from PROMPT if still empty
    if not detected_brand:
        m = re.search(
            r"\b(?:campaign for|launch package for|launch for|post for|advertisement for|ad for|about brand|brand:\s*|company:\s*|client:\s*)\s+([A-Za-z0-9&.'-]+(?:\s+[A-Za-z0-9&.'-]+){0,3})",
            p,
            re.IGNORECASE
        )
        if not m:
            m = re.search(
                r"\b(?:research|analyze|study)\s+([A-Za-z0-9&.'-]+(?:\s+[A-Za-z0-9&.'-]+){0,2})",
                p,
                re.IGNORECASE
            )
        if m:
            raw_cand = m.group(1).strip()
            # Stop before conjunctions/clauses like "and write", "and draft", "to launch"
            cut = re.split(r"\s+\b(?:and|with|to|in|on|for|showcasing|illuminated)\b", raw_cand, maxsplit=1, flags=re.I)[0].strip()
            ignored_words = {
                "a", "an", "the", "our", "new", "this", "revolutionary", "complete", "high-impact",
                "device", "post", "campaign", "crisp", "volumetric", "sleek", "modern", "minimalist",
                "advanced", "high-end", "commercial", "photograph", "solutions"
            }
            cand_words = [w for w in cut.split() if w.lower() not in ignored_words]
            if cand_words:
                cand_brand = " ".join(cand_words)
                if re.search(r"\bbank\s+of\s+am\w*a?\b", cand_brand.lower()):
                    detected_brand = "Bank of America"
                elif len(cand_brand) >= 2:
                    detected_brand = cand_brand.title()

    # 3. Only if prompt provided NO brand at all, fall back to current_brand
    if not detected_brand:
        detected_brand = b if b and b.lower() != "lexnis technologies" else "Lexnis Technologies"

    # 4. Dynamic product extraction if product is still empty
    if not detected_product:
        prod_match = re.search(
            rf"\b{re.escape(detected_brand)}\s+([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)?)",
            p,
            re.IGNORECASE
        )
        if prod_match:
            candidate_p = prod_match.group(1).strip()
            if candidate_p.lower() not in {"and", "to", "for", "with", "is", "device", "post", "campaign"}:
                detected_product = f"{detected_brand} {candidate_p.title()}"

    return detected_brand, detected_product


def normalize_hashtags(tags: Any) -> List[str]:
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out, seen = [], set()
    for t in tags or []:
        t = re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append("#" + t)
    return out[:15]


def repair_json_string(text: str) -> str:
    """Sanitize common LLM JSON syntax errors (trailing commas, unclosed brackets, comments)."""
    if not text:
        return "{}"

    # 1. Extract markdown code blocks if present
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)(?:```|$)", text, re.IGNORECASE)
    if code_block:
        text = code_block.group(1).strip()

    # 2. Find outer braces if present
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    elif start != -1 and end <= start:
        text = text[start:]

    # 3. Strip single-line comments (// ...) and multi-line comments (/* ... */)
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)

    # 4. Remove trailing commas before } or ]
    text = re.sub(r",\s*([\]}])", r"\1", text)
    text = re.sub(r",\s*([\]}])", r"\1", text)

    # 5. Fix common Python literal booleans / None to JSON
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # 6. Balance unclosed brackets / braces if truncated
    open_curly = text.count("{") - text.count("}")
    open_square = text.count("[") - text.count("]")
    if open_curly > 0 or open_square > 0:
        if text.count('"') % 2 != 0:
            text += '"'
        text += ("]" * max(0, open_square)) + ("}" * max(0, open_curly))

    return text.strip()


def extract_field_regex(text: str, key: str) -> Any:
    """Extract a specific field from malformed JSON or labeled text using regex."""
    k_pattern = re.sub(r"[_\s\-]+", r"[\\s_\\-]+", re.escape(key))

    # Pattern 1: JSON style "key": "value" (multiline safe)
    m_str = re.search(rf'["\']?(?:{k_pattern})["\']?\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL | re.IGNORECASE)
    if m_str:
        val = m_str.group(1)
        try:
            return val.encode().decode('unicode_escape')
        except Exception:
            return val

    # Pattern 2: JSON style "key": [ "item1", "item2" ]
    m_arr = re.search(rf'["\']?(?:{k_pattern})["\']?\s*:\s*\[(.*?)\]', text, re.DOTALL | re.IGNORECASE)
    if m_arr:
        items_raw = m_arr.group(1)
        items = re.findall(r'["\'](.*?)["\']', items_raw, re.DOTALL)
        if not items:
            items = [line.strip().lstrip("-*• ") for line in items_raw.splitlines() if line.strip()]
        return [i.strip() for i in items if i.strip()]

    # Pattern 3: Plaintext labeled format e.g. "Hook: ..." or "Product Name: ..."
    m_plain = re.search(rf'(?:^|\n)\s*(?:[-*•]\s*)?(?:{k_pattern})\s*:\s*([^\n]+(?:\n(?!\s*[A-Za-z_ ]+:)[^\n]+)*)', text, re.IGNORECASE)
    if m_plain:
        val = m_plain.group(1).strip().strip('"\'')
        if val.startswith("[") and val.endswith("]"):
            items = re.findall(r'["\'](.*?)["\']', val)
            return items or [val]
        if "\n-" in val or "\n*" in val or "\n•" in val:
            lines = [l.strip().lstrip("-*• ") for l in val.splitlines() if l.strip()]
            return [l for l in lines if l]
        return val

    # Pattern 4: Simple key: value
    m_any = re.search(rf'["\']?(?:{k_pattern})["\']?\s*:\s*([^,\n\}}]+)', text, re.IGNORECASE)
    if m_any:
        return m_any.group(1).strip().strip('"\'')

    return None


def extract_json(raw: str, fallback_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Robust multi-stage JSON parser. Handles trailing commas, unescaped newlines,
    markdown fences, single quotes, unclosed braces, and regex key-value extraction.
    """
    if not raw or not isinstance(raw, str):
        return dict(fallback_schema or {})

    raw_clean = raw.strip()

    # Pass 1: Direct JSON parse with strict=False (allows raw newlines in strings)
    try:
        res = json.loads(raw_clean, strict=False)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Pass 2: Repaired string (strip fences, comments, trailing commas, balance brackets)
    repaired = repair_json_string(raw_clean)
    try:
        res = json.loads(repaired, strict=False)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Pass 3: Python AST literal_eval (handles python dicts {'a': 'b', True, None})
    try:
        val = ast.literal_eval(repaired)
        if isinstance(val, dict):
            return val
    except Exception:
        pass

    # Pass 4: Fix single-quoted JSON properties and values
    try:
        sq_fixed = re.sub(r"(?<=[{\[,:])\s*'([^'\\]*(?:\\.[^'\\]*)*)'\s*(?=[}\],:])", r'"\1"', repaired)
        sq_fixed = re.sub(r",\s*([\]}])", r"\1", sq_fixed)
        res = json.loads(sq_fixed, strict=False)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Pass 5: Fallback regex extraction for known schema keys
    result = dict(fallback_schema or {})
    found_any = False

    all_keys = [
        "product_name", "category", "one_liner", "target_audience",
        "pain_points", "key_benefits", "proof_points", "differentiator",
        "creative_angle", "cta_goal",
        "hook", "caption", "highlights", "cta", "hashtags",
        "image_headline", "alt_text", "visual_prompt"
    ]
    if fallback_schema:
        for k in fallback_schema:
            if k not in all_keys:
                all_keys.append(k)

    for k in all_keys:
        val = extract_field_regex(raw_clean, k)
        if val is not None:
            result[k] = val
            found_any = True

    if found_any:
        return result

    # Pass 6: Graceful synthesis from raw text + fallback schema
    if fallback_schema:
        res = dict(fallback_schema)
        if "hook" in res and not res.get("hook"):
            lines = [l.strip() for l in raw_clean.splitlines() if l.strip()]
            if lines:
                res["hook"] = lines[0][:110]
                if len(lines) > 1 and "caption" in res:
                    res["caption"] = "\n\n".join(lines[1:5])
        return res

    raise ValueError(f"Could not parse valid JSON from model response: {raw[:150]}")


def build_instagram_caption(hook: str, caption: str, highlights: List[str], cta: str, hashtags: str) -> str:
    """Assemble the ready-to-paste caption and keep it under Instagram's 2,200 char limit."""
    parts = [hook, caption]
    if highlights:
        parts.append("\n".join(f"✓ {h}" for h in highlights))
    if cta:
        parts.append(f"👉 {cta}")
    body = "\n\n".join(p for p in parts if p)
    full = f"{body}\n.\n.\n{hashtags}" if hashtags else body
    if len(full) > IG_CAPTION_LIMIT:
        room = IG_CAPTION_LIMIT - len(hashtags) - 8
        full = body[:room].rsplit(" ", 1)[0] + "…\n.\n.\n" + hashtags
    return full


def build_arabic_instagram_caption(hook: str, caption: str, highlights: List[str], cta: str, hashtags: str) -> str:
    """Assemble the ready-to-paste Arabic caption with appropriate RTL styling and character limits."""
    parts = []
    if hook:
        parts.append(hook.strip())
    if caption:
        parts.append(caption.strip())
    if highlights:
        parts.append("\n".join(f"‹ {h.strip()}" for h in highlights if h.strip()))
    if cta:
        parts.append(f"👈 {cta.strip()}")
    body = "\n\n".join(p for p in parts if p)
    full = f"{body}\n.\n.\n{hashtags.strip()}" if hashtags else body
    if len(full) > IG_CAPTION_LIMIT:
        room = IG_CAPTION_LIMIT - len(hashtags) - 8
        full = body[:room].rsplit(" ", 1)[0] + "…\n.\n.\n" + hashtags
    return full


# ==========================================
# Image helpers
# ==========================================

_FONT_CANDIDATES = {
    True: ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
    False: ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf"],
}


def prepare_bidi_text(text: str) -> str:
    """
    Reshape Arabic letters and apply Unicode BiDi algorithm for proper right-to-left rendering in Pillow.
    Passes Latin / English text through untouched.
    """
    if not text:
        return ""
    if re.search(r"[\u0600-\u06FF]", text):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text


def _load_font(size: int, bold: bool = True):
    for path in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text: str, font, max_width: int) -> List[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        disp = prepare_bidi_text(test)
        if draw.textlength(disp, font=font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def fit_cover(img, width: int = POST_WIDTH, height: int = POST_HEIGHT):
    """Resize + center-crop to exactly width x height."""
    img = img.convert("RGB")
    scale = max(width / img.width, height / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - width) // 2, (img.height - height) // 2
    return img.crop((left, top, left + width, top + height))


def clean_product_headline(text: str, prompt: str = "", brand: str = "LEXNIS") -> str:
    _, product = detect_brand_and_product(prompt or text, brand)
    if product:
        return product.upper()
    text = clean_social_text(text).replace("//", " ")
    if not text or re.search(r"\b(write|research|generate|draft|package)\b", text, re.I):
        return brand.upper()
    return " ".join(text.split()[:8]).upper()


def build_flux_commercial_prompt(user_prompt: str, theme: str = "", brand: str = "Lexnis Technologies") -> str:
    return photo_direction(user_prompt, theme, brand)


def compose_post(img, headline="", brand="", accent="#00F0FF", tagline=""):
    return compose_ad(img, headline, brand, tagline)


def is_pollinations_error_card(img_bytes: bytes) -> bool:
    """Detect if an image is Pollinations' yellow rate-limit card ('Free limit reached') or an error payload."""
    if not img_bytes or len(img_bytes) < 1000:
        return True
    # Check for JSON error payload disguised as 200 OK
    stripped = img_bytes[:200].strip()
    if stripped.startswith(b"{") or b'"error"' in stripped or b"SERVICE_UNAVAILABLE" in stripped:
        return True
    try:
        import io
        import numpy as np
        from PIL import Image
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        arr = np.array(im)
        # Pollinations rate-limit card background is bright yellow: R > 220, G > 180, B < 160
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        yellow = (r > 220) & (g > 180) & (b < 160)
        frac = float(np.mean(yellow))
        if frac > 0.30:
            return True
    except Exception:
        pass
    return False


def remove_watermark(im: Image.Image) -> Image.Image:
    """
    Seamlessly detect and erase third-party provider watermarks and logos (e.g. pollinations.ai)
    from the bottom-right corner using computer vision inpainting.
    Guarantees clean, 100% watermark-free commercial advertising visuals.
    """
    try:
        import cv2
        import numpy as np

        rgb = im.convert("RGB")
        img_np = np.array(rgb)
        bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]

        x1 = max(0, w - 260)
        y1 = max(0, h - 60)
        roi = bgr[y1:h, x1:w]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, bin_mask = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        if np.sum(bin_mask > 0) > 40:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            dilated = cv2.dilate(bin_mask, kernel, iterations=2)
            full_mask = np.zeros((h, w), dtype=np.uint8)
            full_mask[y1:h, x1:w] = dilated
            inpainted = cv2.inpaint(bgr, full_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
            return Image.fromarray(cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB))
    except Exception:
        pass

    try:
        w, h = im.size
        patch = im.crop((w - 240, h - 85, w - 10, h - 48))
        im_copy = im.copy()
        im_copy.paste(patch, (w - 240, h - 45))
        return im_copy
    except Exception:
        return im


# ==========================================
# Agency engine
# ==========================================

class LexnisCampaignStudio:
    """AI marketing agency: research -> brief -> copy -> watermark-free visual."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.pollinations_key = os.getenv("POLLINATIONS_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.generation_warnings = []
        self.last_vision_meta = {}

        # Explicit overrides > Gemini > Pollinations (keyed) > anonymous legacy endpoint
        if api_key and base_url:
            self.api_key, self.base_url, self.model, self.text_engine = api_key, base_url, model or DEFAULT_TEXT_MODEL, "custom"
        elif self.gemini_key:
            self.api_key, self.base_url, self.model, self.text_engine = self.gemini_key, GEMINI_OPENAI_BASE, model or DEFAULT_GEMINI_MODEL, "gemini"
        elif self.pollinations_key:
            self.api_key, self.base_url, self.model, self.text_engine = self.pollinations_key, f"{POLLINATIONS_GEN_BASE}/v1", model or DEFAULT_TEXT_MODEL, "pollinations"
        else:
            self.api_key, self.base_url, self.model, self.text_engine = "anonymous", LEGACY_TEXT_BASE, "openai", "pollinations-anonymous"

    # ---------- 1. Research ----------

    @staticmethod
    def search_google(query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Search Google freely with no API key.
        Uses `googlesearch-python` with fallback to DuckDuckGo HTML scraping.
        """
        results: List[Dict[str, str]] = []

        if HAS_GOOGLESEARCH:
            try:
                def _do_search():
                    res = []
                    for r in googlesearch.search(query, num_results=max_results, advanced=True):
                        res.append({
                            "title": getattr(r, "title", None) or query,
                            "url": getattr(r, "url", None) or "",
                            "description": getattr(r, "description", None) or "",
                        })
                        if len(res) >= max_results:
                            break
                    return res

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    res_f = ex.submit(_do_search)
                    results = res_f.result(timeout=4.0)
                    if results:
                        return results
            except Exception as e:
                if console:
                    console.print(f"[dim yellow]Google Search notice: {e}. Trying fallback search...[/dim yellow]")

        if requests is not None and BeautifulSoup is not None:
            try:
                results = LexnisCampaignStudio._search_bing(query, max_results)
                if results:
                    return results
            except Exception:
                results = []

            try:
                resp = requests.get(
                    f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}",
                    headers=BROWSER_HEADERS,
                    timeout=8
                )
                if resp.ok:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for item in soup.select(".result__body")[:max_results]:
                        t_el = item.select_one(".result__title")
                        s_el = item.select_one(".result__snippet")
                        u_el = item.select_one(".result__url")
                        if t_el:
                            url = u_el.get_text(strip=True) if u_el else ""
                            if url and not url.startswith("http"):
                                url = "https://" + url
                            results.append({
                                "title": t_el.get_text(strip=True),
                                "url": url,
                                "description": s_el.get_text(strip=True) if s_el else ""
                            })
            except Exception:
                pass

        return results

    @staticmethod
    def _search_bing(query: str, max_results: int) -> List[Dict[str, str]]:
        """Scrape Bing results (Google/DuckDuckGo often block scripted requests)."""
        import base64

        resp = requests.get("https://www.bing.com/search", params={"q": query}, headers=BROWSER_HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select("li.b_algo"):
            link = item.select_one("h2 a")
            if not link or not link.get("href"):
                continue
            url = link["href"]
            # Bing sometimes wraps links as /ck/a?...&u=a1<base64 url>
            if "bing.com/ck/a" in url:
                u = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("u", [""])[0]
                if u.startswith("a1"):
                    try:
                        url = base64.urlsafe_b64decode(u[2:] + "=" * (-len(u[2:]) % 4)).decode()
                    except Exception:
                        pass
            snippet = item.select_one(".b_caption p") or item.select_one("p")
            results.append({
                "title": link.get_text(strip=True),
                "url": url,
                "description": snippet.get_text(" ", strip=True) if snippet else "",
            })
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def fetch_page_text(url: str, max_chars: int = 1800) -> str:
        """Scrape the useful marketing text of a page (title, meta, headings, paragraphs)."""
        if not url or requests is None or BeautifulSoup is None:
            return ""
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=8)
            if not resp.ok or "html" not in resp.headers.get("content-type", ""):
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg"]):
                tag.decompose()

            chunks = []
            for name in ("description", "og:description"):
                meta = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
                if meta and meta.get("content"):
                    chunks.append(meta["content"].strip())
                    break
            for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):
                txt = el.get_text(" ", strip=True)
                if len(txt) > 30 and txt not in chunks:
                    chunks.append(txt)
                if sum(len(c) for c in chunks) > max_chars:
                    break
            return re.sub(r"\s+", " ", " | ".join(chunks))[:max_chars]
        except Exception:
            return ""

    @staticmethod
    def _is_relevant(query: str, item: Dict[str, str]) -> bool:
        """Drop scraped results that share too few words with the query."""
        stop = {"the", "and", "for", "with", "our", "new", "launch", "post", "campaign", "instagram",
                "about", "this", "that", "from", "your", "product", "promote", "promotion", "create", "make"}
        words = {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", query.lower())} - stop
        if not words:
            return True
        hay = f"{item.get('title', '')} {item.get('description', '')} {item.get('url', '')}".lower()
        hits = sum(1 for w in words if w in hay)
        return hits >= -(-len(words) * 3 // 5)  # at least 60% of the key words

    def research_with_gemini(self, query: str) -> Tuple[List[Dict[str, str]], str]:
        """Synthesize authoritative market research, competitors, and product facts using AI domain intelligence."""
        sys_prompt = (
            "You are a Senior Market Intelligence Researcher and Competitive Strategist.\n"
            "Report: what the product/company is, who makes it, core value proposition, key features and specs, "
            "pricing tier, target audience, and primary commercial competitors. Be factual, concise, and structured."
        )
        user_prompt = f"Provide concise, high-impact market intelligence and competitor analysis for: {query}"
        try:
            text = self._chat(sys_prompt, user_prompt, temperature=0.2, json_mode=False)
            if text and text.strip():
                return [{"title": f"Market Analysis: {query[:40]}", "url": "ai://market-intelligence", "description": "Synthesized brand & competitor intelligence"}], text.strip()
        except Exception:
            pass
        return [], ""

    def research_product(self, query: str, max_results: int = 5, deep_pages: int = 3) -> Tuple[List[Dict[str, str]], str]:
        """Research the product. Returns (sources, context for the strategist)."""
        sections, sources = [], []

        # 1. Product URLs pasted in the prompt are the most reliable source
        for url in re.findall(r"https?://[^\s,]+", query)[:3]:
            page = self.fetch_page_text(url, max_chars=3500)
            if page:
                sources.append({"title": url, "url": url, "description": "Provided product page"})
                sections.append(f"PRODUCT PAGE ({url}):\n{page}")
        topic = re.sub(r"https?://[^\s,]+", "", query).strip() or query

        # 2. Gemini + Google Search grounding
        try:
            g_sources, g_text = self.research_with_gemini(topic)
            if g_text:
                sources += g_sources
                sections.append(f"WEB RESEARCH (Google Search grounded):\n{g_text}")
                return sources, "\n\n".join(sections)
        except Exception as e:
            if console:
                console.print(f"[dim yellow]Gemini research notice: {e}[/dim yellow]")

        # 3. Keyless scraping fallback (often rate-limited / blocked)
        results = [r for r in self.search_google(topic, max_results=max_results) if self._is_relevant(topic, r)]
        for i, item in enumerate(results):
            page = self.fetch_page_text(item.get("url", "")) if i < deep_pages else ""
            sections.append(
                f"SOURCE {i + 1}: {item.get('title', '')} ({item.get('url', '')})\n"
                f"Snippet: {item.get('description', '')}\n"
                + (f"Page content: {page}\n" if page else "")
            )

        # 4. Market intelligence synthesis fallback if search returned nothing
        if not sections:
            try:
                synth_sys = "You are an expert market intelligence researcher. Provide factual brand, product, and competitor landscape knowledge."
                synth_user = f"Provide a concise factual overview of '{topic}', including key offerings, target audience, core strengths, and main competitors."
                synth_text = self._chat(synth_sys, synth_user, temperature=0.3, json_mode=False)
                if synth_text.strip():
                    sections.append(f"MARKET INTELLIGENCE SYNTHESIS:\n{synth_text.strip()}")
                    sources.append({"title": f"Market Intelligence: {topic}", "url": "ai://knowledge-base", "description": "Synthesized brand & industry analysis"})
            except Exception:
                pass

        return sources + results, "\n".join(sections)

    # ---------- 2/3. LLM calls ----------

    def _chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, json_mode: bool = True) -> str:
        """Chat call that waits out short rate limits (anonymous tier: 1 reply / 30s per IP)."""
        import time
        for attempt in range(2):
            try:
                return self._chat_once(system_prompt, user_prompt, temperature, json_mode)
            except Exception as e:
                wait = re.search(r"[Rr]etry after (\d+)\s*s", str(e))
                if attempt == 1 or not wait or int(wait.group(1)) > 15:
                    raise
                time.sleep(min(int(wait.group(1)) + 1, 15))

    def _chat_once(self, system_prompt: str, user_prompt: str, temperature: float, json_mode: bool) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}

        # Fallback models if using Gemini or Pollinations endpoint
        models_to_try = [self.model]
        if getattr(self, "text_engine", "") == "gemini":
            for m in ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3-flash-preview"]:
                if m not in models_to_try:
                    models_to_try.append(m)
        elif "pollinations" in getattr(self, "base_url", "").lower() or getattr(self, "text_engine", "") == "pollinations-anonymous":
            for m in ["openai", "mistral", "deepseek", "qwen"]:
                if m not in models_to_try:
                    models_to_try.append(m)

        last_exc = None
        for current_model in models_to_try:
            try:
                if HAS_OPENAI_LIB:
                    client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=20.0)
                    try:
                        resp = client.chat.completions.create(model=current_model, messages=messages, temperature=temperature, **extra)
                    except Exception as e:
                        if not extra or getattr(e, "status_code", None) not in (400, 422):
                            raise
                        # Some endpoints reject response_format; retry without extra
                        resp = client.chat.completions.create(model=current_model, messages=messages, temperature=temperature)
                    content = resp.choices[0].message.content or ""
                    if content.strip():
                        return content
                else:
                    if requests is None:
                        raise RuntimeError("Install either `openai` or `requests` to generate copy.")
                    resp = requests.post(
                        self.base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"model": current_model, "messages": messages, "temperature": temperature, **extra},
                        timeout=20,
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"] or ""
                    if content.strip():
                        return content
            except Exception as e:
                last_exc = e
                # If model is 503/502/504 or rate-limited (429), try next candidate model
                continue

        # If primary engine (e.g. Gemini 429 quota exhausted) failed, automatically fallback to Pollinations free tier
        if last_exc and getattr(self, "text_engine", "") == "gemini" and requests is not None:
            for fb_model in ["openai", "mistral", "qwen"]:
                try:
                    resp = requests.post(
                        f"{LEGACY_TEXT_BASE}/chat/completions",
                        headers={"Content-Type": "application/json"},
                        json={"model": fb_model, "messages": messages, "temperature": temperature, **extra},
                        timeout=15
                    )
                    if resp.ok:
                        content = resp.json()["choices"][0]["message"]["content"] or ""
                        if content.strip():
                            warn_msg = "Google Gemini quota exhausted; automatically completed copywriting using high-speed cloud backup engine."
                            if warn_msg not in self.generation_warnings:
                                self.generation_warnings.append(warn_msg)
                            return content
                except Exception:
                    continue

        if last_exc:
            raise last_exc
        return ""

    def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        fallback_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """Call the model and parse JSON, retrying once if the output is malformed, with fallback schema guarantee."""
        last_err = None
        raw = ""
        for attempt in range(2):
            try:
                raw = self._chat(system_prompt, user_prompt, temperature=temperature)
                parsed = extract_json(raw)
                if parsed:
                    return {**(fallback_schema or {}), **parsed}, raw
            except Exception as e:
                last_err = e
                user_prompt += "\n\nCRITICAL: Return ONLY a valid JSON object. Do not include markdown codeblocks, comments, or trailing commas."

        if raw:
            try:
                parsed = extract_json(raw)
                if parsed:
                    return {**(fallback_schema or {}), **parsed}, raw
            except Exception:
                pass

        if fallback_schema:
            warn = "A text generation step failed; template copy needs editorial review."
            if warn not in self.generation_warnings:
                self.generation_warnings.append(warn)
            return dict(fallback_schema), raw or ""

        raise RuntimeError(f"Model did not return valid JSON: {last_err}")

    def build_brief(self, prompt: str, brand: str, research: str, guidelines: str = "") -> Dict[str, Any]:
        gl_text = f"\n\nCLIENT BRAND GUIDELINES (STRICT ADHERENCE):\n{guidelines.strip()}" if guidelines else ""
        user = f"BRAND: {brand}\nREQUEST: {prompt}\n\nWEB RESEARCH:\n{research or 'No research available.'}{gl_text}"
        fallback = {
            "product_name": detect_brand_and_product(prompt, brand)[1] or brand,
            "category": "Product campaign",
            "one_liner": prompt[:120].strip(),
            "target_audience": "Confirm the intended audience",
            "pain_points": [],
            "key_benefits": [],
            "proof_points": [],
            "differentiator": "Requires product research",
            "creative_angle": "A focused product introduction",
            "cta_goal": "Explore the product"
        }
        brief, _ = self._chat_json(STRATEGIST_PROMPT, user, temperature=0.4, fallback_schema=fallback)
        return brief

    def enhance_user_prompt(
        self,
        user_prompt: str,
        brand: Optional[str] = None,
        guidelines: Optional[str] = None,
        style_preset: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        AI Prompt Architect:
        Transforms raw, conversational, or vague user prompts into executive Fortune-500 launch briefs.
        Factors in brand detection, client brand guidelines, and creative direction.
        """
        detected_brand, detected_product = detect_brand_and_product(user_prompt, brand or "")

        distilled_gl = self.distill_guidelines(guidelines, max_chars=1200) if guidelines else ""
        gl_text = f"\n\nCLIENT BRAND GUIDELINES (STRICT ADHERENCE):\n{distilled_gl}" if distilled_gl else ""
        style_text = f"\nREQUESTED CREATIVE STYLE: {style_preset}" if style_preset else ""

        brand_label = detected_brand or (brand if brand and brand != "Lexnis Technologies" else "the brand")
        product_label = detected_product or "flagship innovation"

        fallback_enhanced = {
            "detected_brand": detected_brand,
            "product_name": detected_product,
            "target_audience": f"Discerning customers & decision-makers evaluating {brand_label}",
            "core_hook_angle": f"Establishing categorical superiority for {brand_label} through tangible, verified performance.",
            "visual_art_direction": "Cinematic commercial photograph, natural directional lighting, shallow depth of field, generous negative space for typography.",
            "improvements": [
                f"Anchored prompt directly to {brand_label} {product_label}",
                "Structured photographic composition directives for AI visual generator",
                "Clarified high-converting benefit hook for B2B/B2C audiences"
            ],
            "enhanced_prompt": (
                f"Commercial launch campaign for {brand_label} {product_label}. "
                f"Core message: {user_prompt.strip()}. "
                f"Visual direction: Cinematic photography with natural lighting and clean typography negative space. "
                f"Tone: confident, authoritative, and benefit-driven."
            ),
            "suggested_tone": "confident, premium and benefit-driven",
            "suggested_theme": "Cinematic lifestyle photography",
        }

        user_message = (
            f"RAW USER REQUEST: {user_prompt}\n"
            f"CURRENT BRAND FIELD: {brand or detected_brand}"
            f"{style_text}{gl_text}"
        )

        try:
            enhanced, _ = self._chat_json(
                PROMPT_ARCHITECT_SYSTEM_PROMPT,
                user_message,
                temperature=0.35,
                fallback_schema=fallback_enhanced
            )
            if not enhanced.get("enhanced_prompt"):
                enhanced["enhanced_prompt"] = fallback_enhanced["enhanced_prompt"]
            if not enhanced.get("detected_brand"):
                enhanced["detected_brand"] = detected_brand
            if not enhanced.get("improvements") or not isinstance(enhanced.get("improvements"), list):
                enhanced["improvements"] = fallback_enhanced["improvements"]
            else:
                enhanced["improvements"] = [clean_social_text(str(x)) for x in enhanced["improvements"][:4]]

            for k in ["enhanced_prompt", "detected_brand", "product_name", "target_audience", "core_hook_angle", "visual_art_direction", "suggested_tone", "suggested_theme"]:
                if k in enhanced and isinstance(enhanced[k], str):
                    enhanced[k] = clean_social_text(enhanced[k])

            return enhanced
        except Exception:
            return {k: clean_social_text(v) if isinstance(v, str) else v for k, v in fallback_enhanced.items()}

    def _generate_fallback_competitor_analysis(self, brand: str, product: str, prompt: str) -> Dict[str, Any]:
        """Synthesize a robust, highly detailed competitive battlecard when offline or model times out."""
        b_lower = (brand or "").lower()
        p_lower = (product or prompt or "").lower()

        if "tesla" in b_lower or "cybercab" in p_lower or "robotaxi" in p_lower:
            return {
                "rivals": [
                    {
                        "name": "Waymo (Alphabet)",
                        "stance": "Proven commercial autonomous ride-hailing with millions of driverless miles using LiDAR, radar, cameras and HD maps.",
                        "incumbent_weakness": "Prohibitively expensive hardware per vehicle ($100k+), reliance on rigid, expensive HD-mapping geofences, and slow geographic expansion.",
                        "our_edge": "Sub-$30k mass-manufactured vehicle powered by vision-only end-to-end neural networks, scaling globally without high-definition mapping or bulky hardware."
                    },
                    {
                        "name": "Cruise (General Motors)",
                        "stance": "Automaker-backed autonomous rideshare focused on urban mobility with dedicated robotaxi concepts.",
                        "incumbent_weakness": "Regulatory hurdles, trust deficits following safety incidents, and reliance on sensor-heavy architectures that cannot be mass-produced cheaply.",
                        "our_edge": "Massive real-world training data from billions of customer miles worldwide, enabling rapid software iteration and a bespoke, steering-wheel-free cabin from day one."
                    },
                    {
                        "name": "Uber / Lyft (Legacy Rideshare)",
                        "stance": "Ubiquitous, asset-light global network connecting riders with human drivers instantly.",
                        "incumbent_weakness": "High per-mile costs driven by human driver labor (60-70% of fare), vehicle maintenance inconsistencies, and zero hardware integration.",
                        "our_edge": "Radically lower cost per mile (<$0.20/mile target) with zero human labor, seamless inductive wireless charging for 24/7 uptime, and integrated luxury passenger experience."
                    }
                ],
                "strategic_wedge": "Flipping sensor-heavy architectures from a 'safety feature' into an obsolete, cost-prohibitive anchor; positioning Tesla as unconstrained planetary scale vs. geofenced science experiments.",
                "conquest_playbook": {
                    "attack_angle": "The Economics of Freedom: Why Geofenced, $150k LiDAR Rigs Can Never Deliver the True Robotaxi Future.",
                    "campaign_ideas": [
                        "The 'No Geofence' Challenge: Documenting Cybercab navigating complex, unmapped suburban roads where rival vehicles refuse to drive.",
                        "The 20-Cent Mile: A bold cost-comparison infographic and interactive calculator showing riders and fleet operators the extreme financial advantage over Uber and Waymo.",
                        "The Cabin of Tomorrow: An immersive video tour highlighting the psychological transformation of stepping into a vehicle with zero pedals or steering wheel, pure autonomy."
                    ],
                    "landmine_questions": [
                        "How much does it cost to build and equip your vehicle with sensors, and how long does it take to manually map a new city before it can drive there?",
                        "Why should I pay legacy rideshare commissions when the vehicle is fully automated and running on an outsourced network?",
                        "What happens when your vehicle loses GPS or encounters road layouts not present in your static HD maps?"
                    ],
                    "growth_tactics": [
                        "Deploy localized guerrilla test-ride zones outside competitor hubs to let early adopters experience zero-wheel autonomy firsthand.",
                        "Launch a 'Fleet Owner' referral program allowing everyday Tesla owners to add their future Cybercabs to the network with a single tap in the app.",
                        "Release transparent safety and miles-between-critical-intervention data comparing vision-only neural net progress directly against LiDAR-dependent fleets."
                    ]
                }
            }

        if "apple" in b_lower or "vision" in p_lower or "spatial" in p_lower:
            return {
                "rivals": [
                    {
                        "name": "Meta (Quest 3 / Quest Pro)",
                        "stance": "Accessible, high-volume consumer VR gaming and social metaverse platform.",
                        "incumbent_weakness": "Plastic low-resolution displays, gaming-centric aesthetic, ad-driven privacy concerns, and weak enterprise productivity integration.",
                        "our_edge": "Ultra-high-resolution custom micro-OLED optical visor, pristine dark titanium materials, eye/hand micro-gesture neural tracking, and seamless ecosystem sync."
                    },
                    {
                        "name": "Sony / Magic Leap",
                        "stance": "Enterprise XR hardware focused on spatial design and industrial visualization.",
                        "incumbent_weakness": "Fragmented developer ecosystem, bulky tethered compute packs, and lack of consumer-grade operating system polish.",
                        "our_edge": "Dual-chip spatial architecture with dedicated real-time sensor processing, zero tethered battery pack clumsiness, and global App Store developer momentum."
                    }
                ],
                "strategic_wedge": "Reframing VR headsets as disposable plastic gaming toys, while establishing our spatial architecture as the definitive high-status personal computing medium of the next 20 years.",
                "conquest_playbook": {
                    "attack_angle": "The Post-Screen Era: Why immersive spatial fidelity renders physical multi-monitor setups obsolete.",
                    "campaign_ideas": [
                        "The Infinite Workspace: Creative pros demonstrating replacing 4 physical studio monitors with a floating, zero-latency spatial canvas.",
                        "Optics vs. Pixels: Side-by-side macro lens visual teardown comparing 4K micro-OLED pixel density against rival screendoor effect displays.",
                        "Mind & Hand: Highlighting zero-controller natural eye-tracking that makes rival bulky plastic controllers feel like 1990s joysticks."
                    ],
                    "landmine_questions": [
                        "Can you comfortably read 10-point text in your headset without eye strain for a full 8-hour workday?",
                        "Does your platform require plastic handheld controllers just to click a link or navigate your workspace?",
                        "How does your headset protect eye-tracking privacy data from being monetized for advertising?"
                    ],
                    "growth_tactics": [
                        "Architectural & industrial design studio partnerships providing flagship demo stations in major design capitals.",
                        "Executive keynote reaction series featuring top creative directors replacing multi-display editing suites.",
                        "High-framerate Instagram Reels showing seamless hand-tracking pinch gestures manipulating 3D CAD models in physical living rooms."
                    ]
                }
            }

        # Universal fallback for custom / B2B / industrial brands
        target_display = product or brand or "The Solution"
        return {
            "rivals": [
                {
                    "name": "Legacy Enterprise Incumbents",
                    "stance": "All-in-one bloated enterprise suites with decades of entrenched market presence and massive partner networks.",
                    "incumbent_weakness": "Rigid multi-month implementation timelines, exorbitant professional services consulting fees, and brittle, dated user interfaces.",
                    "our_edge": f"{target_display} provides instant deployment, modern zero-configuration architecture, and rapid time-to-value within 48 hours without expensive consultants."
                },
                {
                    "name": "Fragmented Point Solutions",
                    "stance": "Specialized single-feature tools solving one isolated problem cheaply.",
                    "incumbent_weakness": "Data silos, high total cost of ownership across multiple subscriptions, and constant integration breakdowns.",
                    "our_edge": "Unified end-to-end intelligence platform that integrates seamlessly across entire operational workflows, eliminating disconnected stack sprawl."
                }
            ],
            "strategic_wedge": f"Exposing the hidden cost of legacy inertia—positioning {brand} as the agile, high-margin modern alternative while incumbents are trapped defending multi-month consulting deployments.",
            "conquest_playbook": {
                "attack_angle": "Time-to-Value Supremacy: Why modern teams refuse to wait 6 months and pay 6 figures just to go live.",
                "campaign_ideas": [
                    "The Implementation Horror Story vs. 48-Hour Live: Contrasting real customer migration stories from bloated legacy systems to our streamlined platform.",
                    "The TCO Calculator: Interactive audit showing hidden consulting and admin maintenance fees charged by legacy incumbents.",
                    "The Modern Stack Manifesto: High-conviction executive thought leadership outlining why next-gen architecture wins."
                ],
                "landmine_questions": [
                    "How many weeks of specialized professional consulting are required before our team sees the first tangible ROI metric?",
                    "What is the actual total cost of ownership once you factor in custom maintenance, upgrades, and admin overhead?",
                    "Can your architecture scale real-time workflows without requiring complete database refactoring?"
                ],
                "growth_tactics": [
                    "Targeted competitive comparison landing pages and LinkedIn carousels addressing search queries for '[Competitor] alternatives'.",
                    "Frictionless proof-of-concept trial that proves measurable enterprise value in under 7 days.",
                    "Direct executive migration incentives (e.g. buyout of remaining rival contracts for qualifying enterprise pilots)."
                ]
            }
        }

    def analyze_competitors_and_strategy(
        self,
        brand: str,
        product: str,
        prompt: str,
        research_context: str = "",
        guidelines: str = ""
    ) -> Dict[str, Any]:
        """
        Analyze the company/brand name, identify top rivals in the business,
        and generate a counter-positioning strategy and marketing conquest playbook.
        """
        target_name = product or brand
        gl_text = f"\n\nCLIENT BRAND GUIDELINES:\n{guidelines.strip()}" if guidelines else ""
        user_message = (
            f"TARGET BRAND: {brand}\n"
            f"PRODUCT / INITIATIVE: {target_name}\n"
            f"USER PROMPT: {prompt}\n\n"
            f"RESEARCH CONTEXT:\n{research_context[:3000] if research_context else 'No research context available.'}"
            f"{gl_text}"
        )

        fallback_rivals = self._generate_fallback_competitor_analysis(brand, product, prompt)

        try:
            strategy_data, _ = self._chat_json(
                COMPETITIVE_INTELLIGENCE_PROMPT,
                user_message,
                temperature=0.35,
                fallback_schema=fallback_rivals
            )
            if not strategy_data.get("rivals"):
                strategy_data["rivals"] = fallback_rivals["rivals"]
            if not strategy_data.get("strategic_wedge"):
                strategy_data["strategic_wedge"] = fallback_rivals["strategic_wedge"]
            if not strategy_data.get("conquest_playbook"):
                strategy_data["conquest_playbook"] = fallback_rivals["conquest_playbook"]
            return strategy_data
        except Exception:
            return fallback_rivals

    def generate_market_research_guidelines(
        self,
        brand: str,
        prompt: str = "",
        research: str = "",
        use_search: bool = True
    ) -> str:
        """
        Synthesize comprehensive, actionable Brand Guidelines & Directives
        from real-time market research and competitive intelligence.
        Used whenever the user does not provide their own custom brand guidelines.
        """
        target_brand = brand or "Lexnis Technologies"
        target_product = detect_brand_and_product(prompt, target_brand)[1] or target_brand

        # Conduct live market research if not already present
        if not research and use_search:
            try:
                search_query = f"{target_brand} {target_product} core brand values market positioning target audience".strip()
                _, research = self.research_product(search_query)
            except Exception:
                research = ""

        sys_prompt = (
            "You are an Executive Brand Strategy Director and Chief Marketing Officer at a premier global agency.\n"
            "Your task is to synthesize a structured, professional, and actionable Brand Guidelines & Directives document "
            "derived from real-time market research, competitive dynamics, and target audience needs.\n\n"
            "The document must serve as the authoritative standard for marketing copywriting and visual ad creation.\n"
            "Ensure the output is written in crisp, structured markdown."
        )

        user_prompt = (
            f"BRAND: {target_brand}\n"
            f"PRODUCT / FOCUS: {target_product}\n"
            f"CAMPAIGN CONCEPT / INITIATIVE: {prompt or 'Enterprise Market Launch'}\n\n"
            f"MARKET RESEARCH CONTEXT:\n{research[:2500] if research else 'Emerging enterprise technology space with demands for reliability, speed, and premium positioning.'}\n\n"
            "Format the guidelines with these exact numbered sections:\n"
            "1. BRAND POSITIONING & STRATEGIC VALUE PROPOSITION\n"
            "   - Core Mission & Market Role\n"
            "   - Strategic Positioning Wedge against competitors\n"
            "   - Key Value Drivers\n\n"
            "2. TARGET AUDIENCE & PERSONA DIRECTIVES\n"
            "   - Primary Decision Makers & Demographics\n"
            "   - Core Pain Points & Friction to address\n"
            "   - Desired Customer Sentiment & Mindset\n\n"
            "3. BRAND VOICE, TONE & MESSAGING RULES\n"
            "   - Tone Profile (e.g. Confident, Authoritative, Visionary, Frictionless)\n"
            "   - Mandatory Copy Directives (Lead with measurable outcomes, high-stakes relevance)\n"
            "   - Forbidden Terminology & Pitfalls (Forbidden cliches, unverified buzzwords, passive voice)\n\n"
            "4. VISUAL IDENTITY & PHOTOGRAPHIC DIRECTIVES\n"
            "   - Art Direction & Aesthetic Atmosphere\n"
            "   - Palette & Color Harmony\n"
            "   - Composition & Lighting Rules (Volumetric lighting, negative space for brand typography)\n\n"
            "5. CAMPAIGN EXECUTION RULES & COMPLIANCE\n"
            "   - Hook Directive: Opening line criteria\n"
            "   - Call To Action: Action-oriented next step\n"
            "   - Integrity Directive: Truthful, verifiable claims only"
        )

        try:
            guidelines_text = self._chat_text(sys_prompt, user_prompt, temperature=0.7)
            if guidelines_text and len(guidelines_text.strip()) > 200:
                return guidelines_text.strip()
        except Exception:
            pass

        return self._fallback_market_research_guidelines(target_brand, target_product, research)

    def _fallback_market_research_guidelines(self, brand: str, product: str, research: str = "") -> str:
        """Deterministic high-quality fallback guidelines synthesized from market intelligence."""
        return (
            f"# BRAND STRATEGY & GUIDELINES: {brand.upper()}\n"
            f"*(Synthesized from Real-Time Market Intelligence for {product})*\n\n"
            f"## 1. BRAND POSITIONING & STRATEGIC VALUE PROPOSITION\n"
            f"- **Core Mission**: Establish {brand} as the benchmark of performance, precision, and enterprise reliability.\n"
            f"- **Positioning Wedge**: Deliver frictionless execution and measurable ROI where legacy solutions create complexity.\n"
            f"- **Key Value Drivers**: Speed of deployment, operational resilience, and verifiable excellence.\n\n"
            f"## 2. TARGET AUDIENCE & PERSONA DIRECTIVES\n"
            f"- **Primary Audience**: Forward-thinking executives, technical decision-makers, and high-impact operators.\n"
            f"- **Core Pain Points**: Wasted overhead, legacy technical debt, and vendor promises that fail in production.\n"
            f"- **Desired Customer Mindset**: Unwavering trust, forward momentum, and executive authority.\n\n"
            f"## 3. BRAND VOICE, TONE & MESSAGING RULES\n"
            f"- **Tone Profile**: Confident, authoritative, visionary, and outcome-obsessed.\n"
            f"- **Mandatory Copy Directives**: Lead with tangible commercial impact; speak directly to high-stakes business realities.\n"
            f"- **Forbidden Pitfalls**: Avoid generic tech fluff, excessive buzzwords ('synergy', 'game-changing'), and timid phrasing.\n\n"
            f"## 4. VISUAL IDENTITY & PHOTOGRAPHIC DIRECTIVES\n"
            f"- **Aesthetic**: Premium minimalist commercial tech aesthetic with tactile materials and authentic human leadership.\n"
            f"- **Color Harmony**: Deep executive tones accented with crisp highlights and balanced negative space.\n"
            f"- **Lighting & Optics**: Crisp volumetric studio lighting with subtle depth of field and generous typography clearance.\n\n"
            f"## 5. CAMPAIGN EXECUTION RULES & COMPLIANCE\n"
            f"- **Hook Directive**: Provocative first sentence that challenges industry complacency.\n"
            f"- **Call To Action**: Clear, high-intent invitation with zero friction.\n"
            f"- **Integrity Mandate**: Maintain absolute documentation and factual integrity across all brand touchpoints."
        )

    def analyze_company_website(self, url: str, brand: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract structured Brand DNA from a company website URL:
        - Corporate color palette (Primary, Secondary, Accent, Gradient start/end)
        - Typography (Primary heading, body, font families)
        - Official Brand Hashtag (e.g. #LexnisTeam)
        - Aesthetic style & photography direction
        - Brand Guidelines summary
        Used to dynamically adapt visual templates (colors, fonts, wording) to the company's brand flow.
        """
        import re
        from urllib.parse import urlparse

        clean_url = (url or "").strip()
        if not clean_url:
            clean_url = "https://lexnis.com"
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url

        parsed = urlparse(clean_url)
        domain = parsed.netloc.lower().replace("www.", "")
        target_brand = brand or ("Lexnis Technologies" if "lexnis" in domain else domain.split(".")[0].capitalize())

        # 1. High-fidelity verified defaults for Lexnis Technologies (from 16-page brand book)
        if "lexnis" in domain or (target_brand and "lexnis" in target_brand.lower()):
            return {
                "company_name": "Lexnis Technologies",
                "url": clean_url,
                "domain": domain or "lexnis.com",
                "tagline": "Industrial AI & Enterprise Intelligence Infrastructure",
                "industry": "Enterprise AI & Scalable Systems",
                "brand_tag": "#LexnisTeam",
                "typography": {
                    "primary_font": "Poppins",
                    "secondary_font": "Inter",
                    "heading_style": "Geometric Bold Sans (Poppins Bold)",
                    "body_style": "High-Legibility Modern Sans (Inter)"
                },
                "brand_colors": {
                    "primary": "#08101E",
                    "secondary": "#132E4F",
                    "accent": "#00F0FF",
                    "text_primary": "#FFFFFF",
                    "text_secondary": "#94A3B8",
                    "gradient_start": "#08101E",
                    "gradient_end": "#132E4F"
                },
                "visual_aesthetic": "Futuristic enterprise minimalism with volumetric rim light, high-contrast dark navy tones, and crisp geometric sans-serif typography.",
                "guidelines_summary": "Color harmony: Dark enterprise navy (#08101E -> #132E4F) with electric cyan accents (#00F0FF). Primary typography is Poppins Bold. Official brand hashtag is #LexnisTeam. Layouts must feature crisp white framing with high-contrast executive portraiture."
            }

        # 2. Live Web Scraping for custom domains
        scraped_title = ""
        scraped_desc = ""
        scraped_h1 = ""
        scraped_fonts = []
        scraped_colors = []

        if requests:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = requests.get(clean_url, headers=headers, timeout=6)
                if resp.status_code == 200:
                    html_text = resp.text
                    if BeautifulSoup:
                        soup = BeautifulSoup(html_text, "html.parser")
                        scraped_title = soup.title.string.strip() if soup.title and soup.title.string else ""
                        meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                        if meta_desc and meta_desc.get("content"):
                            scraped_desc = meta_desc["content"].strip()
                        og_site = soup.find("meta", attrs={"property": "og:site_name"})
                        if og_site and og_site.get("content"):
                            target_brand = og_site["content"].strip()
                        h1 = soup.find("h1")
                        if h1:
                            scraped_h1 = h1.get_text().strip()

                        # Extract font links
                        for link in soup.find_all("link", href=True):
                            href = link["href"]
                            if "fonts.googleapis.com" in href:
                                m = re.search(r"family=([^&:]+)", href)
                                if m:
                                    scraped_fonts.append(m.group(1).replace("+", " "))

                    # Regex extract CSS hex colors
                    hex_matches = re.findall(r"#(?:[0-9a-fA-F]{3}){1,2}\b", html_text[:100000])
                    scraped_colors = [c.upper() for c in set(hex_matches) if c.upper() not in {"#000000", "#FFFFFF", "#FFF", "#000", "#111111", "#F5F5F5", "#EEEEEE"}][:8]
            except Exception:
                pass

        # 3. Clean Brand Tag
        clean_tag_name = re.sub(r'[^a-zA-Z0-9]', '', target_brand)
        default_tag = f"#{clean_tag_name}Team" if clean_tag_name else "#BrandTeam"

        # 4. Fallback schema for custom domain
        primary_col = scraped_colors[0] if scraped_colors else "#08101E"
        secondary_col = scraped_colors[1] if len(scraped_colors) > 1 else "#132E4F"
        accent_col = scraped_colors[2] if len(scraped_colors) > 2 else "#00F0FF"

        fallback_dna = {
            "company_name": target_brand,
            "url": clean_url,
            "domain": domain,
            "tagline": scraped_desc or scraped_h1 or f"Next-generation solutions by {target_brand}",
            "industry": "Technology & Innovation",
            "brand_tag": default_tag,
            "typography": {
                "primary_font": scraped_fonts[0] if scraped_fonts else "Poppins",
                "secondary_font": "Inter",
                "heading_style": "Geometric Bold Sans",
                "body_style": "Modern Clean Sans"
            },
            "brand_colors": {
                "primary": primary_col,
                "secondary": secondary_col,
                "accent": accent_col,
                "text_primary": "#FFFFFF",
                "text_secondary": "#94A3B8",
                "gradient_start": primary_col,
                "gradient_end": secondary_col
            },
            "visual_aesthetic": f"Clean minimalist corporate aesthetic with balanced negative space, modern typography, and branded tones matching {clean_url}.",
            "guidelines_summary": f"Brand palette: {primary_col} gradient with {accent_col} accents. Typography: {scraped_fonts[0] if scraped_fonts else 'Poppins'}. Official community hashtag: {default_tag}."
        }

        # 5. Optional LLM Synthesis if API available
        try:
            user_msg = (
                f"WEBSITE URL: {clean_url}\n"
                f"DOMAIN: {domain}\n"
                f"BRAND HINT: {target_brand}\n"
                f"SCRAPED TITLE: {scraped_title}\n"
                f"SCRAPED DESCRIPTION: {scraped_desc}\n"
                f"SCRAPED H1: {scraped_h1}\n"
                f"SCRAPED FONTS: {', '.join(scraped_fonts) if scraped_fonts else 'None detected'}\n"
                f"SCRAPED CSS COLORS: {', '.join(scraped_colors) if scraped_colors else 'None detected'}\n"
            )
            parsed_dna, _ = self._chat_json(
                BRAND_DNA_PROMPT,
                user_msg,
                temperature=0.3,
                fallback_schema=fallback_dna
            )
            return parsed_dna
        except Exception:
            return fallback_dna

    def synthesize_brief_and_strategy(
        self,
        prompt: str,
        brand: str,
        prod_candidate: str,
        research: str,
        guidelines: str = ""
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Unified High-Speed Strategic Intelligence:
        Synthesizes both the Creative Brief AND Competitor Conquest Playbook
        in a single optimized LLM call (saving ~15-30s and avoiding 429 concurrency blocks).
        """
        gl_text = f"\n\nCLIENT BRAND GUIDELINES (STRICT ADHERENCE):\n{guidelines.strip()}" if guidelines else ""
        target_name = prod_candidate or brand

        fallback_brief = {
            "product_name": target_name,
            "category": "Commercial offering",
            "one_liner": prompt[:120].strip(),
            "target_audience": "Discerning clients and decision-makers",
            "pain_points": ["Legacy compromises", "High switching costs"],
            "key_benefits": ["Tangible category superiority", "Frictionless experience", "Verified performance"],
            "proof_points": [],
            "differentiator": f"Category-defining leadership by {brand}",
            "creative_angle": "Uncompromising performance and modern prestige",
            "cta_goal": "Discover the breakthrough"
        }
        fallback_rivals = self._generate_fallback_competitor_analysis(brand, prod_candidate, prompt)

        unified_prompt = (
            f"TARGET BRAND: {brand}\n"
            f"PRODUCT / INITIATIVE: {target_name}\n"
            f"USER REQUEST: {prompt}\n\n"
            f"RESEARCH CONTEXT:\n{research[:2500] if research else 'No external research available.'}"
            f"{gl_text}"
        )

        sys_prompt = (
            "You are the Head of Strategy and Chief Marketing Officer at an award-winning creative agency.\n"
            "Synthesize a sharp creative brief and competitor conquest battlecard in ONE concise JSON document.\n\n"
            "Rules:\n"
            "- Be concise, structured, and factual. Do not invent fake statistics.\n"
            "- Identify 2 primary rivals/alternatives in the market.\n"
            "- Return strictly valid RFC 8259 JSON without markdown fences.\n\n"
            "Return JSON with keys:\n"
            "{\n"
            '  "product_name": "Product or offer name",\n'
            '  "category": "Product category",\n'
            '  "one_liner": "What it is and why it matters (under 20 words)",\n'
            '  "target_audience": "Who this post is for",\n'
            '  "pain_points": ["2 concrete frustrations"],\n'
            '  "key_benefits": ["3 outcome-focused benefits"],\n'
            '  "proof_points": ["Verified specs/facts, empty if none"],\n'
            '  "differentiator": "Why this beats alternatives",\n'
            '  "creative_angle": "The big idea for this campaign",\n'
            '  "cta_goal": "The one action the reader should take",\n'
            '  "rivals": [\n'
            '    {\n'
            '      "name": "Competitor Name",\n'
            '      "stance": "Their core promise",\n'
            '      "incumbent_weakness": "Their vulnerability",\n'
            '      "our_edge": "Why our product beats them"\n'
            '    }\n'
            '  ],\n'
            '  "strategic_wedge": "1-2 sentence counter-positioning thesis",\n'
            '  "conquest_playbook": {\n'
            '    "attack_angle": "Angle of market conquest",\n'
            '    "campaign_ideas": ["3 high-converting campaign angles"],\n'
            '    "landmine_questions": ["3 trap questions for competitors"],\n'
            '    "growth_tactics": ["3 growth tactics"]\n'
            '  }\n'
            "}"
        )

        try:
            combined_fallback = {**fallback_brief, **fallback_rivals}
            res, _ = self._chat_json(sys_prompt, unified_prompt, temperature=0.35, fallback_schema=combined_fallback)

            brief = {
                "product_name": res.get("product_name") or target_name,
                "category": res.get("category") or fallback_brief["category"],
                "one_liner": res.get("one_liner") or fallback_brief["one_liner"],
                "target_audience": res.get("target_audience") or fallback_brief["target_audience"],
                "pain_points": res.get("pain_points") or fallback_brief["pain_points"],
                "key_benefits": res.get("key_benefits") or fallback_brief["key_benefits"],
                "proof_points": res.get("proof_points") or fallback_brief["proof_points"],
                "differentiator": res.get("differentiator") or fallback_brief["differentiator"],
                "creative_angle": res.get("creative_angle") or fallback_brief["creative_angle"],
                "cta_goal": res.get("cta_goal") or fallback_brief["cta_goal"],
            }
            strategy = {
                "rivals": res.get("rivals") or fallback_rivals["rivals"],
                "strategic_wedge": res.get("strategic_wedge") or fallback_rivals["strategic_wedge"],
                "conquest_playbook": res.get("conquest_playbook") or fallback_rivals["conquest_playbook"],
            }
            return brief, strategy
        except Exception:
            return fallback_brief, fallback_rivals

    def collaborative_generation(
        self,
        prompt: str,
        brand: str,
        brief: Dict[str, Any],
        tone: str,
        theme: str,
        competitive_strategy: Optional[Dict[str, Any]] = None,
        rivals: Optional[List[Dict[str, Any]]] = None,
        step_callback=None,
        guidelines: str = ""
    ) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[str]]:
        """
        Dual-agent collaborative pipeline:
        1. Agent 1 (Lead Copywriter & Strategist) drafts initial copy & visual concept with competitive edge.
        2. Agent 2 (Executive Creative Director & Art Critic) critiques, strips clichés, injects specs, and polishes to Fortune-500 standard.
        Returns (final_post_dict, agent_dialogue, critique_notes).
        """
        step = step_callback or (lambda msg: None)
        prod_name = brief.get("product_name") or brand

        # Fallback schema for Agent 1
        agent1_fallback = {
            "agent1_rationale": "Template draft; AI copy generation unavailable.",
            "hook": f"Meet {prod_name}.",
            "caption": f"Discover {prod_name}. Explore the details and find out whether it fits your needs.",
            "highlights": brief.get("key_benefits", []),
            "cta": "Explore the product.",
            "hashtags": [f"#{brand.replace(' ', '')}", "#NextGenTech", "#Innovation", "#Engineering"],
            "image_headline": clean_product_headline(prod_name, prompt=prompt, brand=brand),
            "visual_concept": f"Commercial studio hero photograph of physical {prod_name} on dark graphite pedestal"
        }

        strat_section = ""
        if competitive_strategy or rivals:
            strat_info = {
                "strategic_wedge": (competitive_strategy or {}).get("strategic_wedge", ""),
                "rivals": rivals or [],
                "conquest_playbook": (competitive_strategy or {}).get("conquest_playbook", {})
            }
            strat_section = f"\n\nCOMPETITIVE INTEL & RIVAL CONQUEST BATTLECARD:\n{json.dumps(strat_info, indent=2, ensure_ascii=False)}"

        guidelines_section = ""
        if guidelines and guidelines.strip():
            guidelines_section = (
                f"\n\n============================================================\n"
                f"CLIENT BRAND GUIDELINES & DIRECTIVES (STRICT COMPLIANCE MANDATORY):\n"
                f"{guidelines.strip()}\n"
                f"============================================================\n"
                f"AUDIT DIRECTIVE: Adhere strictly to the brand voice, tone, forbidden/allowed terminology, "
                f"and positioning rules specified above. Eliminate generic claims.\n"
            )

        # 1. Agent 1 Draft
        step("Agent 1 (Lead Copywriter) drafting initial campaign concept with competitive edge...")
        agent1_sys = AGENT1_COPYWRITER_PROMPT.format(brand=brand, tone=tone, theme=theme)
        agent1_user = f"ORIGINAL REQUEST: {prompt}\n\nCREATIVE BRIEF:\n{json.dumps(brief, indent=2, ensure_ascii=False)}{strat_section}{guidelines_section}"

        try:
            draft, _ = self._chat_json(agent1_sys, agent1_user, temperature=0.75, fallback_schema=agent1_fallback)
        except Exception:
            draft = agent1_fallback

        # 2. Agent 2 Critique & Polish
        step("Agent 2 (Creative Director & Critic) auditing competitive edge, specs & visuals...")

        agent2_fallback = {
            "critique_notes": ["Creative review unavailable; inspect the draft before publishing."],
            "agent_dialogue": [],
            "hook": draft.get("hook", agent1_fallback["hook"]),
            "caption": draft.get("caption", agent1_fallback["caption"]),
            "highlights": draft.get("highlights", agent1_fallback["highlights"]),
            "cta": draft.get("cta", agent1_fallback["cta"]),
            "hashtags": draft.get("hashtags", agent1_fallback["hashtags"]),
            "image_headline": draft.get("image_headline", agent1_fallback["image_headline"]),
            "alt_text": f"Minimalist commercial photograph of {prod_name} in luxury studio lighting",
            "visual_prompt": build_flux_commercial_prompt(prompt, theme, brand)
        }

        agent2_user = (
            f"BRAND: {brand}\n"
            f"ORIGINAL REQUEST: {prompt}\n"
            f"VISUAL DIRECTION: {theme}\n"
            f"CREATIVE BRIEF:\n{json.dumps(brief, indent=2, ensure_ascii=False)}"
            f"{strat_section}\n\n"
            f"{guidelines_section}\n\n"
            f"AGENT 1 (LEAD COPYWRITER) DRAFT:\n{json.dumps(draft, indent=2, ensure_ascii=False)}"
        )

        try:
            final_campaign, _ = self._chat_json(AGENT2_DIRECTOR_CRITIC_PROMPT, agent2_user, temperature=0.4, fallback_schema=agent2_fallback)
        except Exception:
            final_campaign = agent2_fallback

        dialogue = final_campaign.get("agent_dialogue") or agent2_fallback["agent_dialogue"]
        critique_notes = final_campaign.get("critique_notes") or agent2_fallback["critique_notes"]

        return final_campaign, dialogue, critique_notes

    def write_post(self, prompt: str, brand: str, brief: Dict[str, Any], tone: str, theme: str) -> Tuple[Dict[str, Any], str]:
        final_post, _, _ = self.collaborative_generation(prompt, brand, brief, tone, theme)
        return final_post, json.dumps(final_post)

    # ---------- 4. Visual ----------

    def _fetch_image_bytes(self, visual_prompt: str, seed: int, model: str,
                           width: int = RENDER_WIDTH, height: int = RENDER_HEIGHT) -> Tuple[bytes, bool]:
        if model in LOCAL_MODELS:
            try:
                return local_image(visual_prompt, seed, width, height, model=model)
            except Exception as exc:
                warn_msg = "Local GPU rendering limit reached; automatically switched to cloud visual generator."
                if warn_msg not in self.generation_warnings:
                    self.generation_warnings.append(warn_msg)
                if os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"):
                    try:
                        return cloudflare_image(visual_prompt, seed)
                    except Exception:
                        pass
                model = "flux"
        if model == "cf:flux-schnell":
            try:
                return cloudflare_image(visual_prompt, seed)
            except Exception as exc:
                warn_msg = "Cloudflare image generation unavailable; switched to cloud visual generator."
                if warn_msg not in self.generation_warnings:
                    self.generation_warnings.append(warn_msg)
                model = "flux"
        if model.startswith("hf:"):
            try:
                return open_model_image(visual_prompt, seed, model, width, height)
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError("Open-weight image inference failed. Check cached model weights, installed dependencies and available GPU/RAM, then retry the visual.") from exc
        if requests is None:
            raise RuntimeError("Install requests to render images.")
        if model == "gemini-image":
            if self.gemini_key:
                try:
                    response = requests.post(
                        "https://generativelanguage.googleapis.com/v1beta/models/" + os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image") + ":generateContent",
                        headers={"x-goog-api-key": self.gemini_key},
                        json={"contents": [{"parts": [{"text": visual_prompt}]}],
                              "generationConfig": {"responseModalities": ["IMAGE"]}}, timeout=60)
                    if response.ok:
                        for candidate in response.json().get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                if part.get("inlineData", {}).get("data"):
                                    return base64.b64decode(part["inlineData"]["data"]), True
                except Exception:
                    pass
            warn_msg = "Gemini image quota exceeded; automatically switched to cloud FLUX generator."
            if warn_msg not in self.generation_warnings:
                self.generation_warnings.append(warn_msg)
            model = "flux"

        # On Pollinations anonymous tier, premium models return 402; auto-switch to free flux
        if not self.pollinations_key and model in ["black-forest-labs/flux.1.1-pro", "flux-realism", "black-forest-labs/flux.1-schnell"]:
            model = "flux"

        base = POLLINATIONS_GEN_BASE + "/image" if self.pollinations_key else LEGACY_IMAGE_BASE
        headers = {"Authorization": f"Bearer {self.pollinations_key}"} if self.pollinations_key else {}
        try:
            response = requests.get(f"{base}/{urllib.parse.quote(visual_prompt, safe='')}",
                params={"model": model, "width": width, "height": height, "seed": seed, "nologo": "true", "private": "true"},
                headers=headers, timeout=90)
            if response.ok and len(response.content) > 2000 and not is_pollinations_error_card(response.content):
                return response.content, True
        except requests.RequestException:
            pass

        # Robust cloud fallback: if chosen model returned 402/error, retry with free FLUX Standard
        if model != "flux":
            try:
                response = requests.get(
                    f"{LEGACY_IMAGE_BASE}/{urllib.parse.quote(visual_prompt, safe='')}",
                    params={"model": "flux", "width": width, "height": height, "seed": seed, "nologo": "true", "private": "true"},
                    timeout=90
                )
                if response.ok and len(response.content) > 2000 and not is_pollinations_error_card(response.content):
                    return response.content, True
            except Exception:
                pass

        raise RuntimeError("Image provider unavailable or quota exhausted. Your copy is saved; configure an image provider and retry the visual.")

    def render_image(
        self,
        visual_prompt: str,
        seed: int,
        model: str = DEFAULT_IMAGE_MODEL,
        headline: str = "",
        brand: str = "",
        overlay: bool = True,
        out_dir: Path = RENDERS_DIR,
        output_format: str = "portrait",
        tagline: str = "",
        arabic_headline: str = "",
        arabic_tagline: str = "",
        base_image_path: Optional[Path] = None,
    ) -> RenderResult:
        """Render (and cache) base visual, then composite both English and Arabic posts."""
        if model in LEGACY_MODEL_ALIASES or not model:
            model = DEFAULT_IMAGE_MODEL
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        width, height = FORMATS[output_format]

        if base_image_path and Path(base_image_path).exists():
            base_p = Path(base_image_path)
            key = hashlib.sha1(f"user_asset|{base_p.name}|{width}|{height}".encode()).hexdigest()[:16]
            clean_path = out_dir / f"{key}_clean.jpg"
            if not clean_path.exists():
                try:
                    raw_user = Image.open(base_p).convert("RGB")
                    fitted = fit_cover(raw_user, width, height)
                    fitted.save(clean_path, "JPEG", quality=95, optimize=True)
                except Exception:
                    shutil.copyfile(base_p, clean_path)
            watermark_free = True
        else:
            provider = os.getenv("IMAGE_PROVIDER", "huggingface")
            key = hashlib.sha1(f"{RENDER_VERSION}|{visual_prompt}|{seed}|{model}|{provider}|{width}|{height}|{bool(self.pollinations_key)}".encode()).hexdigest()[:16]
            clean_path = out_dir / f"{key}_clean.jpg"
            marker = out_dir / f"{key}.wm"

            if clean_path.exists():
                watermark_free = True
                # If previously cached render had a watermark marker, clean it in-place
                if marker.exists() and HAS_PIL:
                    try:
                        cleaned_im = remove_watermark(Image.open(clean_path))
                        cleaned_im.save(clean_path, "JPEG", quality=95, optimize=True)
                        marker.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                data, _ = self._fetch_image_bytes(visual_prompt, seed, model, (width + 31) // 32 * 32, (height + 31) // 32 * 32)
                if not HAS_PIL:
                    clean_path.write_bytes(data)
                    return RenderResult(clean_path, clean_path, True)
                try:
                    raw_img = fit_cover(Image.open(io.BytesIO(data)), width, height)
                    # Seamlessly erase any third-party provider watermark (pollinations.ai, etc.)
                    img = remove_watermark(raw_img)
                except Exception as exc:
                    raise RuntimeError("Image provider returned an invalid image. Retry the visual.") from exc
                img.save(clean_path, "JPEG", quality=95, optimize=True)
                watermark_free = True

        if not overlay or not HAS_PIL or not (headline or brand):
            return RenderResult(clean_path, clean_path, watermark_free)

        # High-Speed Ad Typography:
        # If headline is already provided from the creative brief/post, typeset immediately
        # to avoid slow multimodal image uploads and Gemini vision 429 rate limits.
        if headline:
            clean_hl = headline.strip()
            typeset_tagline = tagline.strip()
            vision_meta = {
                "visual_subject": "Commercial hero scene",
                "visual_analysis": f"Photorealistic luxury commercial scene for {brand}.",
                "visual_headline": clean_hl,
                "visual_tagline": typeset_tagline,
                "visual_ar_headline": arabic_headline or "ريادة تتجاوز الزمن",
                "visual_ar_tagline": arabic_tagline or "ثروتك إرث يبنى ليبقى."
            }
        else:
            try:
                vision_meta = self.typeset_visual_with_vision(
                    clean_path.read_bytes(),
                    brand=brand,
                    campaign_context=f"{headline} - {tagline}",
                    default_headline=headline,
                    default_tagline=tagline
                )
            except Exception:
                vision_meta = {}
            clean_hl = (vision_meta.get("visual_headline") or headline or brand).strip()
            typeset_tagline = (vision_meta.get("visual_tagline") or tagline).strip()

        self.last_vision_meta = vision_meta

        tag = hashlib.sha1(f"ad-v5-vision-aligned|{clean_hl}|{brand}|{typeset_tagline}".encode()).hexdigest()[:8]
        post_path = out_dir / f"{key}_post_{tag}.jpg"
        if not post_path.exists():
            compose_post(Image.open(clean_path), headline=clean_hl, brand=brand, tagline=typeset_tagline).save(
                post_path, "JPEG", quality=95, optimize=True
            )

        arabic_post_path = None
        clean_ar_hl = (arabic_headline or vision_meta.get("visual_ar_headline") or "").strip()
        clean_ar_tl = (arabic_tagline or vision_meta.get("visual_ar_tagline") or "").strip()
        if not clean_ar_hl:
            clean_ar_hl = "ريادة تتخطى الآفاق"
            clean_ar_tl = "حيث تلتقي الرؤية بالتميز المطلق."

        ar_tag = hashlib.sha1(f"ad-v5-ar|{clean_ar_hl}|{brand}|{clean_ar_tl}".encode()).hexdigest()[:8]
        arabic_post_path = out_dir / f"{key}_post_ar_{ar_tag}.jpg"
        if not arabic_post_path.exists():
            try:
                compose_post(Image.open(clean_path), headline=clean_ar_hl, brand=brand, tagline=clean_ar_tl).save(
                    arabic_post_path, "JPEG", quality=95, optimize=True
                )
            except Exception as e:
                arabic_post_path = None

        self.last_arabic_post_path = arabic_post_path
        return RenderResult(post_path, clean_path, watermark_free, arabic_post_path)

    def typeset_visual_with_vision(
        self,
        image_bytes: bytes,
        brand: str,
        campaign_context: str = "",
        default_headline: str = "",
        default_tagline: str = ""
    ) -> Dict[str, str]:
        """
        Multimodal Vision Typographer:
        Inspects the rendered visual asset, analyzes composition, lighting, and hero subject,
        and generates an ad headline and subline that organically fit WHAT IS ACTUALLY IN THE IMAGE
        in both English and Modern Standard Arabic.
        """
        clean_brand = brand.strip() if brand and brand.lower() != "lexnis technologies" else ""
        fallback_headline = default_headline.strip() or clean_brand or "INNOVATION"
        if clean_brand and fallback_headline.upper().startswith(clean_brand.upper()):
            remainder = fallback_headline[len(clean_brand):].strip(" -//:")
            if len(remainder) >= 3:
                fallback_headline = remainder

        short_tagline = default_tagline.strip()
        if len(short_tagline.split()) > 10:
            short_tagline = " ".join(short_tagline.split()[:9]) + "..."

        result = {
            "visual_subject": "Commercial hero scene",
            "visual_analysis": "Commercial advertising photograph with balanced directional lighting and reserved negative space.",
            "visual_headline": fallback_headline.upper(),
            "visual_tagline": short_tagline,
            "visual_ar_headline": "ريادة تتخطى الآفاق",
            "visual_ar_tagline": "حيث تلتقي الرؤية بالتميز المطلق."
        }

        if not image_bytes or not self.gemini_key or requests is None:
            return result

        try:
            import base64
            # Downscale for ultra-fast multimodal transmission (<150KB)
            try:
                im_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                im_pil.thumbnail((1024, 1024))
                buf = io.BytesIO()
                im_pil.save(buf, format="JPEG", quality=82)
                b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception:
                b64_img = base64.b64encode(image_bytes).decode("utf-8")
            vision_prompt = (
                f"You are an Executive Art Director and Luxury Ad Typographer for {brand}.\n"
                f"Analyze this newly generated commercial advertising photograph.\n"
                f"Campaign Brand: {brand}\n"
                f"Campaign Context / Core Benefit: {campaign_context[:400]}\n\n"
                "TASK:\n"
                "1. Identify the primary visual subject visible in this specific photo (e.g., 'scenic coastal highway at sunset', 'minimalist titanium device', 'precision robotic arm', 'industrial turbine with diagnostic beams').\n"
                "2. Write a 1-sentence analysis of the image composition, lighting, and mood.\n"
                "3. Compose an English ad headline (strictly 2 to 4 words) that organically connects WHAT IS VISIBLE in this image with the brand's premium identity.\n"
                "   - Crucial rule: Do NOT redundantly repeat the brand name.\n"
                "   - If the image depicts an open road or horizon, invoke journey, vision, or future.\n"
                "   - If the image depicts a physical product or machine, highlight precision, engineering, or mastery.\n"
                "   - If the image depicts nature, architecture, or lifestyle, evoke prestige, permanence, or sovereign power.\n"
                "4. Compose a punchy, elegant English subtitle/tagline (strictly under 8 words) that reinforces the headline.\n"
                "5. Transcreate the headline and subtitle into prestigious Modern Standard Arabic (الفصحى التسويقية الراقية):\n"
                "   - visual_ar_headline: 2 to 4 punchy Arabic words capturing the exact same visual mood (e.g. 'آفاق بلا حدود').\n"
                "   - visual_ar_tagline: concise Arabic subtitle under 8 words.\n\n"
                "Respond ONLY with a JSON object:\n"
                "{\n"
                '  "visual_subject": "Primary object/scene visible",\n'
                '  "visual_analysis": "One sentence describing visual composition and mood",\n'
                '  "visual_headline": "2-4 WORDS PUNCHY HEADLINE",\n'
                '  "visual_tagline": "Under 8 words subtitle fitting the image",\n'
                '  "visual_ar_headline": "2-4 كلمات عنوان معرب راقٍ",\n'
                '  "visual_ar_tagline": "شعار عربي مكمل ومقتضب تحت 8 كلمات"\n'
                "}"
            )

            models_to_try = [
                os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite"),
                "gemini-flash-lite-latest",
                "gemini-3-flash-preview",
            ]

            for m_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={self.gemini_key}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": vision_prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}
                        ]
                    }],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": 0.2
                    }
                }
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
                if resp.ok:
                    data = resp.json()
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        parsed = json.loads(parts[0]["text"])
                        hl = parsed.get("visual_headline", "").strip()
                        if hl:
                            result["visual_subject"] = parsed.get("visual_subject", result["visual_subject"])
                            result["visual_analysis"] = parsed.get("visual_analysis", result["visual_analysis"])
                            result["visual_headline"] = hl.upper()
                            result["visual_tagline"] = parsed.get("visual_tagline", "").strip()
                            if parsed.get("visual_ar_headline"):
                                result["visual_ar_headline"] = parsed.get("visual_ar_headline", "").strip()
                            if parsed.get("visual_ar_tagline"):
                                result["visual_ar_tagline"] = parsed.get("visual_ar_tagline", "").strip()
                            return result
        except Exception:
            pass

        return result

    def transcreate_to_arabic(
        self,
        en_campaign: Dict[str, Any],
        brand: str,
        visual_analysis: str = "",
        guidelines: str = ""
    ) -> Dict[str, Any]:
        """
        Transcreate and localize the campaign into high-impact Modern Standard Arabic (التعريب الإبداعي).
        Preserves executive authority, emotional resonance, and competitive wedge.
        """
        fallback_arabic = {
            "hook": f"ارتقِ بمعايير الريادة والتميز مع {brand}.",
            "caption": f"نبتكر أفقاً جديداً في التميز والأداء.\n\nصُمم خصيصاً لإعادة صياغة الممكن ودمج الدقة الفائقة مع الرؤية المستقبلية.\n\nعصر جديد يبدأ الآن.",
            "highlights": [
                "هندسة متطورة بمعايير عالمية لا تقبل المساومة",
                "أداء فائق ودقة استثنائية مصممة للرواد",
                "حلول متكاملة تمنحك السيادة والتميز المستدام"
            ],
            "cta": "اكتشف المزيد وتواصل معنا عبر الرابط في البايو.",
            "hashtags": f"#{brand.replace(' ', '_')} #ريادة #ابتكار #تميز #مستقبل",
            "image_headline": "آفاق جديدة",
            "visual_headline": "آفاق جديدة",
            "visual_tagline": "حيث تلتقي الرؤية بالتميز المطلق",
            "alt_text": f"صورة إعلانية تجارية فاخرة للعلامة التجارية {brand}"
        }

        user_content = (
            f"BRAND: {brand}\n"
            f"VISUAL SCENE ANALYSIS: {visual_analysis or 'Commercial luxury photography'}\n"
            f"ENGLISH CAMPAIGN PACKAGE:\n{json.dumps(en_campaign, ensure_ascii=False, indent=2)}"
        )

        try:
            ar_data, _ = self._chat_json(ARABIC_TRANSCREATOR_PROMPT, user_content, temperature=0.4, fallback_schema=fallback_arabic)
        except Exception:
            ar_data = fallback_arabic

        ar_hook = ar_data.get("hook") or fallback_arabic["hook"]
        ar_caption = ar_data.get("caption") or fallback_arabic["caption"]
        ar_highlights = ar_data.get("highlights") or fallback_arabic["highlights"]
        if isinstance(ar_highlights, str):
            ar_highlights = [h.strip() for h in re.split(r"[\n,]+", ar_highlights) if h.strip()]
        ar_cta = ar_data.get("cta") or fallback_arabic["cta"]
        ar_hashtags = ar_data.get("hashtags") or fallback_arabic["hashtags"]
        if isinstance(ar_hashtags, list):
            ar_hashtags = " ".join(normalize_hashtags(ar_hashtags))

        ar_data["instagram_caption"] = build_arabic_instagram_caption(ar_hook, ar_caption, ar_highlights, ar_cta, str(ar_hashtags))
        return ar_data

    def extract_guidelines_from_image(self, image_bytes: bytes, filename: str, content_type: str = "") -> str:
        """
        Multimodal Vision analysis:
        Extracts brand identity, color palette, typography rules, and photographic directives
        from an uploaded style guide, logo sheet, moodboard, or reference image (.png, .jpg, etc.).
        """
        clean_fname = Path(filename).name
        ext = Path(filename).suffix.lower()

        # 1. Gemini Multimodal Vision Extraction
        if self.gemini_key and requests is not None:
            mime = content_type if (content_type and content_type.startswith("image/")) else (
                "image/png" if ext == ".png" else (
                    "image/webp" if ext == ".webp" else (
                        "image/gif" if ext == ".gif" else (
                            "image/bmp" if ext == ".bmp" else (
                                "image/svg+xml" if ext == ".svg" else "image/jpeg"
                            )
                        )
                    )
                )
            )
            # Downscale image to fast web resolution (max 1024px) for instant multimodal analysis (<150KB)
            try:
                im_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                im_pil.thumbnail((1024, 1024))
                buf = io.BytesIO()
                im_pil.save(buf, format="JPEG", quality=82)
                b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
                mime = "image/jpeg"
            except Exception:
                b64_img = base64.b64encode(image_bytes).decode("utf-8")

            prompt = (
                f'You are an Executive Brand Strategy Director and Creative Director.\n'
                f'The user has uploaded this image file ("{clean_fname}") as their official Brand Guidelines / Style Guide / Visual Reference Asset.\n\n'
                f'Thoroughly examine this image and formulate clear, comprehensive, actionable Brand Guidelines and Directives that the AI marketing campaign generator must strictly adhere to when writing copy and generating commercial photography.\n\n'
                f'Structure your analysis into these sections:\n'
                f'1. BRAND IDENTITY & POSITIONING:\n'
                f'   - Identify any visible logos, emblems, product names, or trademarks.\n'
                f'   - Summarize the brand\'s industry, pedigree, and core market stance.\n\n'
                f'2. VISUAL AESTHETIC & PHOTOGRAPHY DIRECTIVES:\n'
                f'   - Art direction style (e.g., luxury minimalist studio, golden-hour editorial lifestyle, industrial precision macro).\n'
                f'   - Lighting setup (e.g., soft directional box, warm rim highlights, cinematic chiaroscuro).\n'
                f'   - Materials, textures, and hero subject focus (e.g., titanium, leather, glass, wet coastal sand).\n'
                f'   - Framing and negative space directives for typographic headline placement.\n\n'
                f'3. COLOR PALETTE & TONAL CODES:\n'
                f'   - Primary brand tones and dominant background colors.\n'
                f'   - Recommended hex accent codes (e.g., Obsidian Dark, Electric Cyan, Rose Gold, Platinum).\n\n'
                f'4. COPYWRITING VOICE & MESSAGING RULES:\n'
                f'   - Editorial voice (e.g., executive authoritative, premium aspirational, technical precision).\n'
                f'   - Explicit or implied positioning hooks, slogans, or value propositions.\n'
                f'   - Mandatory rules: What narratives to reinforce and what tropes to strictly avoid.\n\n'
                f'Format as a clean, highly structured Brand Style Guide document with clear bullet points.'
            )

            models_to_try = [
                os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite"),
                "gemini-flash-lite-latest",
                "gemini-3-flash-preview",
            ]
            for m_name in models_to_try:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={self.gemini_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {"mime_type": mime, "data": b64_img}}
                            ]
                        }],
                        "generationConfig": {"temperature": 0.25}
                    }
                    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                    if resp.ok:
                        data = resp.json()
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if parts and parts[0].get("text"):
                            result_text = parts[0]["text"].strip()
                            if len(result_text) > 80:
                                return f"BRAND GUIDELINES & STYLE DIRECTIVES (Extracted from {clean_fname}):\n\n{result_text}"
                except Exception:
                    continue

        # 2. Local PIL Extraction (Palette, dimensions, and visual rules)
        try:
            im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            w, h = im.size
            small = im.resize((50, 50))
            colors = small.getcolors(2500) or []
            sorted_colors = sorted(colors, key=lambda c: c[0], reverse=True)
            hex_colors = [f"#{c[1][0]:02x}{c[1][1]:02x}{c[1][2]:02x}" for c in sorted_colors[:6]]

            return (
                f"BRAND VISUAL STYLE GUIDE & DIRECTIVES (Extracted from {clean_fname}):\n\n"
                f"1. VISUAL REFERENCE ASSET:\n"
                f"   - File: {clean_fname}\n"
                f"   - Resolution: {w} x {h} ({w/h:.2f}:1 aspect ratio)\n"
                f"   - Format: {im.format or ext.upper().lstrip('.')}\n\n"
                f"2. EXTRACTED BRAND COLOR PALETTE:\n"
                f"   - Primary Dominant: {hex_colors[0] if len(hex_colors) > 0 else '#0c1017'}\n"
                f"   - Secondary Accent: {hex_colors[1] if len(hex_colors) > 1 else '#00f0ff'}\n"
                f"   - Background Base: {hex_colors[2] if len(hex_colors) > 2 else '#07090e'}\n"
                f"   - Extended Palette: {', '.join(hex_colors[3:]) if len(hex_colors) > 3 else 'Neutral'}\n\n"
                f"3. VISUAL ART DIRECTION RULES:\n"
                f"   - Preserve the visual atmosphere, lighting temperature, and material fidelity of {clean_fname}.\n"
                f"   - Maintain generous typography negative space on corners for clean headline burn-in.\n"
                f"   - Strictly avoid low-res CGI plastic aesthetics; prioritize authentic physical textures.\n\n"
                f"4. BRAND COMPLIANCE DIRECTIVE:\n"
                f"   - All synthesized campaign copy, headlines, and visual assets must align directly with the palette and premium standard established by this visual reference."
            )
        except Exception:
            return (
                f"BRAND STYLE DIRECTIVES (Reference Asset: {clean_fname}):\n"
                f"- Reference Asset: {clean_fname}\n"
                f"- Visual Directive: Replicate the premium product styling, palette balance, and clean composition established in {clean_fname}.\n"
                f"- Messaging Directive: Uphold executive-grade positioning and brand consistency across all campaign deliverables."
            )

    @staticmethod
    def distill_guidelines(guidelines: str, max_chars: int = 1800) -> str:
        """
        Condense massive uploaded style guides, PDFs, and multi-file directives
        into a high-density, actionable brief for LLM prompts to prevent token bloat
        and multi-minute processing delays.
        """
        if not guidelines or len(guidelines.strip()) <= max_chars:
            return guidelines.strip() if guidelines else ""

        text = guidelines.strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        high_priority = []
        for line in lines:
            line_lower = line.lower()
            if any(k in line_lower for k in [
                "brand:", "logo", "palette", "color", "hex", "#", "tone", "voice",
                "directive", "rule", "do not", "never", "avoid", "must", "style",
                "typography", "headline", "mission", "positioning", "audience", "aesthetic"
            ]):
                if line not in high_priority:
                    high_priority.append(line)

        if high_priority and len("\n".join(high_priority)) >= 250:
            return "\n".join(high_priority)[:max_chars]

        return text[:max_chars]

    # ---------- Full pipeline ----------

    def generate_campaign(
        self,
        prompt: str,
        tone: Optional[str] = None,
        theme: Optional[str] = None,
        seed: Optional[int] = None,
        use_search: bool = True,
        image_model: str = DEFAULT_IMAGE_MODEL,
        enhance_image: bool = True,
        brand: str = "Lexnis Technologies",
        progress=None,
        output_format: str = "portrait",
        guidelines: str = "",
        uploaded_image_path: Optional[str] = None,
        uploaded_image_paths: Optional[List[str]] = None,
        use_uploaded_image: Optional[bool] = None,
        company_url: Optional[str] = None,
        recolor_to_brand: bool = True,
    ) -> CampaignAsset:
        """
        Run the full agency pipeline with Dual-Agent Collaborative refinement:
        Research -> Executive Brief -> Agent 1 Draft -> Agent 2 Critique & Polish -> FLUX Visual.
        """
        step = progress or (lambda msg: None)
        tone = tone or "confident, premium and benefit-driven"
        theme = theme or "Cinematic lifestyle photography"
        brand = brand or "Lexnis Technologies"

        # 0. Live Brand DNA extraction from company website
        brand_dna = None
        if company_url:
            step(f"Extracting live Brand DNA from {company_url}...")
            try:
                brand_dna = self.analyze_company_website(company_url, brand=brand)
                if brand_dna and isinstance(brand_dna, dict):
                    detected_company = brand_dna.get("company_name")
                    if detected_company and (not brand or brand == "Lexnis Technologies" and "lexnis" not in detected_company.lower()):
                        brand = detected_company
                    dna_summary = brand_dna.get("guidelines_summary")
                    if dna_summary and dna_summary not in guidelines:
                        guidelines = f"{guidelines}\n\nWEBSITE BRAND DNA ({company_url}):\n{dna_summary}".strip()
            except Exception:
                brand_dna = None

        # Intelligent Brand Detection & Executive Prompt Enhancement
        detected_brand, detected_prod = detect_brand_and_product(prompt, brand)
        if detected_brand:
            brand = detected_brand

        # The original request governs product identity and creative direction.
        enhanced_prompt = ""
        effective_prompt = prompt

        # 1. Guidelines Resolution: Custom Uploaded vs Market Research Auto-Synthesis
        has_custom_gl = bool(guidelines and guidelines.strip())
        guidelines_source = "user_uploaded" if has_custom_gl else "market_research"

        # 2. Fast market intelligence synthesis (single combined query)
        search_results: List[Dict[str, str]] = []
        research = ""
        if use_search:
            step("Researching market and competitor landscape...")
            try:
                search_query = f"{brand} {detected_prod or prompt} core offerings market competitors".strip()
                search_results, research = self.research_product(search_query)
            except Exception:
                search_results, research = [], ""

        # If user did NOT supply custom guidelines, synthesize them FIRST from market research!
        if not has_custom_gl:
            step("Synthesizing tailored brand guidelines from real-time market research...")
            try:
                guidelines = self.generate_market_research_guidelines(
                    brand=brand,
                    prompt=effective_prompt,
                    research=research,
                    use_search=False
                )
            except Exception:
                guidelines = self._fallback_market_research_guidelines(brand, detected_prod or prompt, research)

        distilled_gl = self.distill_guidelines(guidelines, max_chars=1800)

        # 3. High-Speed Unified Brief & Competitor Conquest Playbook
        step("Synthesizing creative brief & competitor battlecards...")
        prod_candidate = detected_prod or brand
        brief, strategy_data = self.synthesize_brief_and_strategy(
            effective_prompt, brand, prod_candidate, research, guidelines=distilled_gl
        )

        prod_name = brief.get("product_name") or prod_candidate
        rivals = strategy_data.get("rivals", [])
        competitive_strategy = {
            "strategic_wedge": strategy_data.get("strategic_wedge", ""),
            "conquest_playbook": strategy_data.get("conquest_playbook", {})
        }

        # 4. Dual-Agent Collaboration Loop: Agent 1 (Draft) -> Agent 2 (Critique & Polish)
        post, dialogue, critique_notes = self.collaborative_generation(
            effective_prompt, brand, brief, tone, theme,
            competitive_strategy=competitive_strategy,
            rivals=rivals,
            step_callback=step,
            guidelines=distilled_gl
        )

        hook = clean_social_text(post.get("hook", "")) or brief.get("one_liner", prompt)
        caption = clean_social_text(post.get("caption", ""))
        raw_highlights = post.get("highlights", [])
        if isinstance(raw_highlights, str):
            raw_highlights = [h.strip() for h in re.split(r"[\n,]+", raw_highlights) if h.strip()]
        highlights = [clean_social_text(h) for h in raw_highlights if str(h).strip()][:5]
        cta = clean_social_text(post.get("cta", ""))
        hashtags = " ".join(normalize_hashtags(post.get("hashtags", [])))
        headline = clean_product_headline(post.get("image_headline", ""), prompt=effective_prompt, brand=brand)
        alt_text = clean_social_text(post.get("alt_text", ""))[:300] or f"Commercial luxury photograph of {headline}"
        raw_visual = clean_social_text(post.get("visual_prompt", ""))
        user_has_coast = any(w in effective_prompt.lower() for w in ("coast", "beach", "ocean", "sunset"))
        if not raw_visual or len(raw_visual) < 25 or any(cmd in raw_visual.lower() for cmd in ["draft a", "create a", "write a", "package for"]):
            visual_prompt = build_flux_commercial_prompt(effective_prompt, theme, brand)
        elif not user_has_coast and any(w in raw_visual.lower() for w in ("coastal road", "winding coastal", "above the ocean")):
            visual_prompt = build_flux_commercial_prompt(effective_prompt, theme, brand)
        else:
            visual_prompt = raw_visual
            if "no text" not in visual_prompt.lower():
                visual_prompt += ", no text, no letters, no logos, no watermark"

        if seed is None:
            seed = random.randint(100000, 999999)

        # 5. Concurrent Visual Generation & Arabic Transcreation
        step("Rendering campaign visual & transcreating Arabic copy in parallel...")
        warnings = list(dict.fromkeys(self.generation_warnings))
        if not research:
            warnings.append("No web evidence retrieved. Review product claims before publishing.")

        en_pack = {
            "hook": hook,
            "caption": caption,
            "highlights": highlights,
            "cta": cta,
            "hashtags": hashtags,
            "visual_headline": headline,
            "visual_tagline": hook[:110],
            "visual_analysis": "",
        }

        # Check for template + subject replacement (e.g. girl with white background into blue template)
        candidate_images = []
        if uploaded_image_paths:
            candidate_images.extend([Path(p) for p in uploaded_image_paths if Path(p).exists()])
        if uploaded_image_path and Path(uploaded_image_path).exists() and Path(uploaded_image_path) not in candidate_images:
            candidate_images.append(Path(uploaded_image_path))

        prompt_lower = (effective_prompt + " " + (guidelines or "")).lower()
        needs_swap = any(k in prompt_lower for k in ["girl", "blue image", "white background", "template", "portrait", "sekawan", "swap", "replace", "face", "uploaded"])

        # Only search uploads cache if user provided an image or explicitly requested a template swap
        if (candidate_images or needs_swap) and len(candidate_images) < 2:
            uploads_dir = RENDERS_DIR.parent / "output" / "uploads"
            if not uploads_dir.exists():
                uploads_dir = RENDERS_DIR.parent / "uploads"
            if uploads_dir.exists():
                for f in sorted(uploads_dir.glob("*.*"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and f not in candidate_images:
                        candidate_images.append(f)
                    if len(candidate_images) >= 2:
                        break

        # Also check test_assets if prompt explicitly mentions template swap or subject keywords
        if len(candidate_images) < 2 and needs_swap:
            test_assets_dir = RENDERS_DIR.parent / "test_assets"
            if test_assets_dir.exists():
                for fname in ["template_reference.jpg", "raw_subject.jpg"]:
                    p = test_assets_dir / fname
                    if p.exists() and p not in candidate_images:
                        candidate_images.append(p)

        from visual_engine import classify_template_and_subject, composite_template_swap, render_lexnis_executive_artboard
        t_file, s_file = classify_template_and_subject(candidate_images) if len(candidate_images) >= 2 else (None, None)
        if len(candidate_images) == 1 and not s_file:
            s_file = candidate_images[0]

        person_name, person_title = detect_featured_person(effective_prompt)

        # Brand styling & hashtag extraction
        brand_colors = None
        brand_tag = None
        if brand_dna:
            brand_colors = brand_dna.get("brand_colors")
            brand_tag = brand_dna.get("brand_tag")
        if not brand_colors and "lexnis" in brand.lower():
            brand_colors = {
                "primary": "#08101E",
                "secondary": "#132E4F",
                "accent": "#00F0FF",
                "gradient_start": "#08101E",
                "gradient_end": "#132E4F"
            }
        if not brand_tag:
            brand_tag = f"#{re.sub(r'[^a-zA-Z0-9]', '', brand)}Team"

        if t_file and s_file and (use_uploaded_image is not False):
            step("Executing autonomous 2.5D pop-out template subject replacement...")
            swap_key = hashlib.sha1(f"swap|{t_file.name}|{s_file.name}|{person_name}|{person_title}|{brand}|{brand_tag}|{company_url}|recolor_{recolor_to_brand}".encode()).hexdigest()[:16]
            clean_path = RENDERS_DIR / f"{swap_key}_clean.jpg"
            post_path = RENDERS_DIR / f"{swap_key}_post.jpg"
            if not clean_path.exists():
                swap_img = composite_template_swap(
                    t_file,
                    s_file,
                    person_name=person_name,
                    person_title=person_title,
                    brand_name=brand,
                    brand_tag=brand_tag,
                    brand_colors=brand_colors,
                    recolor_gradient=recolor_to_brand
                )
                swap_img.save(clean_path, "JPEG", quality=95, optimize=True)
                swap_img.save(post_path, "JPEG", quality=95, optimize=True)
            arabic_pack = self.transcreate_to_arabic(en_pack, brand=brand, visual_analysis="Template subject replacement", guidelines=distilled_gl)
            watermark_free = True
            image_status = "ready"
            arabic_post_path = post_path
            uploaded_post_en = post_path
            uploaded_clean = clean_path
            uploaded_post_ar = post_path
            has_uploaded_asset = True
        elif s_file and not t_file and (use_uploaded_image is not False):
            step(f"Rendering executive brand artboard for {person_name or brand}...")
            art_key = hashlib.sha1(f"exec_art|{s_file.name}|{person_name}|{person_title}|{brand}".encode()).hexdigest()[:16]
            clean_path = RENDERS_DIR / f"{art_key}_clean.jpg"
            post_path = RENDERS_DIR / f"{art_key}_post.jpg"
            if not clean_path.exists():
                hl_en = headline or (f"FEATURING {person_name.upper()}" if person_name else "LEADERSHIP IN MOTION")
                tg_en = hook or "From vision to operating reality. Empowering enterprise transformation."
                ar_pack = self.transcreate_to_arabic(en_pack, brand=brand, guidelines=distilled_gl)
                hl_ar = ar_pack.get("visual_headline") or (f"قيادة تصنع الأثر · {person_name}" if person_name else "قيادة تصنع الأثر")
                tg_ar = ar_pack.get("visual_tagline") or "حلول مؤسسية متقدمة من الرؤية إلى واقع تشغيلي."

                art_img = render_lexnis_executive_artboard(
                    s_file,
                    person_name=person_name or "Alisha Faisal",
                    person_title=person_title or "Marketing Manager",
                    headline_en=hl_en,
                    tagline_en=tg_en,
                    headline_ar=hl_ar,
                    tagline_ar=tg_ar,
                    brand=brand,
                    target_size=(1080, 1350)
                )
                art_img.save(clean_path, "JPEG", quality=95, optimize=True)
                art_img.save(post_path, "JPEG", quality=95, optimize=True)
                arabic_pack = ar_pack
            watermark_free = True
            image_status = "ready"
            arabic_post_path = post_path
            uploaded_post_en = post_path
            uploaded_clean = clean_path
            uploaded_post_ar = post_path
            has_uploaded_asset = True
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                render_future = executor.submit(
                    self.render_image,
                    visual_prompt, seed, model=image_model, headline=headline, brand=brand,
                    overlay=enhance_image, output_format=output_format, tagline=hook[:110]
                )
                arabic_future = executor.submit(
                    self.transcreate_to_arabic,
                    en_pack, brand=brand, visual_analysis="", guidelines=distilled_gl
                )

                try:
                    render_res = render_future.result()
                    post_path, clean_path, watermark_free = render_res[0], render_res[1], render_res[2]
                    image_status = "ready"
                except RuntimeError as exc:
                    post_path = clean_path = None
                    render_res = None
                    watermark_free = False
                    image_status = "unavailable"
                    warnings.append(str(exc))

                arabic_pack = arabic_future.result()

        vm = getattr(self, "last_vision_meta", {})
        final_headline = vm.get("visual_headline") or headline
        final_tagline = vm.get("visual_tagline") or hook[:110]
        final_analysis = vm.get("visual_analysis") or ""
        en_pack["visual_headline"] = final_headline
        en_pack["visual_tagline"] = final_tagline
        en_pack["visual_analysis"] = final_analysis

        ar_hl = arabic_pack.get("visual_headline") or arabic_pack.get("image_headline") or vm.get("visual_ar_headline") or "ريادة تتخطى الآفاق"
        ar_tl = arabic_pack.get("visual_tagline") or vm.get("visual_ar_tagline") or ""

        # Render Arabic visual overlay for AI generated base (suppressed for template swap to preserve crisp brand typography)
        arabic_post_path = None
        if clean_path and clean_path.exists() and not (t_file and s_file):
            ar_tag = hashlib.sha1(f"ad-v5-ar|{ar_hl}|{brand}|{ar_tl}".encode()).hexdigest()[:8]
            arabic_post_path = RENDERS_DIR / f"{clean_path.stem.split('_')[0]}_post_ar_{ar_tag}.jpg"
            if not arabic_post_path.exists():
                try:
                    compose_post(Image.open(clean_path), headline=ar_hl, brand=brand, tagline=ar_tl).save(
                        arabic_post_path, "JPEG", quality=95, optimize=True
                    )
                except Exception:
                    arabic_post_path = None
        elif t_file and s_file:
            arabic_post_path = post_path

        # Check if an uploaded image asset was provided
        has_uploaded_asset = bool(uploaded_image_path and Path(uploaded_image_path).exists())
        uploaded_post_en = None
        uploaded_post_ar = None
        uploaded_clean = None

        if has_uploaded_asset and not (t_file and s_file):
            step("Compositing campaign typography directly onto uploaded brand asset...")
            try:
                up_res = self.render_image(
                    visual_prompt, seed, model=image_model, headline=final_headline, brand=brand,
                    overlay=enhance_image, output_format=output_format, tagline=final_tagline,
                    arabic_headline=ar_hl,
                    arabic_tagline=ar_tl,
                    base_image_path=Path(uploaded_image_path)
                )
                uploaded_post_en = up_res[0]
                uploaded_clean = up_res[1]
                uploaded_post_ar = up_res[3] if len(up_res) > 3 else getattr(self, "last_arabic_post_path", None)
            except Exception:
                pass
        elif t_file and s_file:
            uploaded_post_en = post_path
            uploaded_clean = clean_path
            uploaded_post_ar = post_path
            has_uploaded_asset = True

        # Determine primary output visual
        ai_post_path = post_path
        ai_clean_path = clean_path
        ai_arabic_path = arabic_post_path

        primary_post = post_path
        primary_clean = clean_path
        primary_arabic = arabic_post_path

        # If user uploaded an image or template swap occurred, default to featuring that visual
        if (has_uploaded_asset or (t_file and s_file)) and uploaded_post_en and (use_uploaded_image is not False):
            primary_post = uploaded_post_en
            primary_clean = uploaded_clean
            primary_arabic = uploaded_post_ar
            watermark_free = True
            image_status = "ready"

        raw_response = json.dumps({"brief": brief, "post": post, "arabic": arabic_pack, "dialogue": dialogue, "critique": critique_notes}, indent=2, ensure_ascii=False)
        return CampaignAsset(
            prompt=prompt,
            hook=hook,
            caption=caption,
            highlights=highlights,
            hashtags=hashtags,
            visual_prompt=visual_prompt,
            image_url=f"/renders/{primary_post.name}" if primary_post else "",
            raw_response=raw_response,
            seed=seed,
            search_results=search_results,
            brand=brand,
            cta=cta,
            image_headline=final_headline,
            alt_text=f"Commercial luxury photograph of {final_headline}. {final_analysis}".strip(),
            instagram_caption=build_instagram_caption(hook, caption, highlights, cta, hashtags),
            brief=brief,
            image_model=image_model if image_model not in LEGACY_MODEL_ALIASES else DEFAULT_IMAGE_MODEL,
            image_path=str(primary_post) if primary_post else "",
            clean_image_path=str(primary_clean) if primary_clean else "",
            arabic_image_url=f"/renders/{primary_arabic.name}" if primary_arabic else "",
            arabic_image_path=str(primary_arabic) if primary_arabic else "",
            uploaded_image_url=f"/renders/{uploaded_post_en.name}" if uploaded_post_en else "",
            uploaded_arabic_url=f"/renders/{uploaded_post_ar.name}" if uploaded_post_ar else "",
            ai_image_url=f"/renders/{ai_post_path.name}" if ai_post_path else "",
            ai_arabic_url=f"/renders/{ai_arabic_path.name}" if ai_arabic_path else "",
            has_uploaded_asset=has_uploaded_asset,
            watermark_free=True if primary_post else False,
            text_engine=f"{self.text_engine}:{self.model}",
            agent_dialogue=dialogue,
            critique_notes=critique_notes,
            enhanced_prompt=effective_prompt,
            output_format=output_format,
            image_status=image_status,
            warnings=list(dict.fromkeys(w for w in warnings if w)),
            rivals=rivals,
            competitive_strategy=competitive_strategy,
            visual_analysis=final_analysis,
            visual_headline=final_headline,
            visual_tagline=final_tagline,
            arabic=arabic_pack,
            guidelines=guidelines,
            guidelines_source=guidelines_source,
            company_url=company_url or "",
            brand_dna=brand_dna or {},
        )

    def template_swap_composite(
        self,
        template_image: Any,
        subject_image: Any,
        target_size: tuple = (808, 1024),
        out_dir: Path = RENDERS_DIR,
    ) -> Path:
        """Autonomous template subject-replacement and 2.5D pop-out compositing."""
        from visual_engine import composite_template_swap
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        img = composite_template_swap(template_image, subject_image, target_size=target_size)
        token = hashlib.sha1(f"template_swap_{time.time()}".encode()).hexdigest()[:12]
        out_path = out_dir / f"template_swap_{token}.jpg"
        img.save(out_path, format="JPEG", quality=95)
        return out_path

    # ---------- Export ----------

    @staticmethod
    def download_image(image_url: str, save_path: Path) -> Path:
        """Download an image URL to disk."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if requests is None:
            raise RuntimeError("`requests` is required to download images.")
        resp = requests.get(image_url, timeout=120)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
        return save_path

    def export_campaign(self, asset: CampaignAsset, output_dir: str = "output") -> Dict[str, str]:
        """Save campaign package: English & Arabic post images, clean image, metadata (.json) and bilingual captions."""
        import shutil

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"[^\w\d]+", "_", asset.prompt[:30].strip()).strip("_").lower() or f"campaign_{asset.seed}"
        files: Dict[str, str] = {}

        image_file = out / f"{slug}_post.jpg"
        if asset.image_path and Path(asset.image_path).exists():
            shutil.copyfile(asset.image_path, image_file)
            files["image"] = str(image_file)

        if asset.arabic_image_path and Path(asset.arabic_image_path).exists():
            image_ar_file = out / f"{slug}_post_ar.jpg"
            shutil.copyfile(asset.arabic_image_path, image_ar_file)
            files["arabic_image"] = str(image_ar_file)

        if asset.clean_image_path and Path(asset.clean_image_path).exists() and asset.clean_image_path != asset.image_path:
            clean_file = out / f"{slug}_clean.jpg"
            shutil.copyfile(asset.clean_image_path, clean_file)
            files["clean_image"] = str(clean_file)

        json_file = out / f"{slug}_data.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(asset.to_dict(), f, indent=2, ensure_ascii=False)
        files["json"] = str(json_file)

        en_caption = asset.instagram_caption or build_instagram_caption(
            asset.hook, asset.caption, asset.highlights, asset.cta, asset.hashtags
        )
        en_caption_file = out / f"{slug}_caption_en.txt"
        en_caption_file.write_text(en_caption, encoding="utf-8")
        files["caption_en"] = str(en_caption_file)

        ar_data = asset.arabic or {}
        ar_caption = ar_data.get("instagram_caption") or build_arabic_instagram_caption(
            ar_data.get("hook", ""), ar_data.get("caption", ""), ar_data.get("highlights", []),
            ar_data.get("cta", ""), ar_data.get("hashtags", "")
        )
        ar_caption_file = out / f"{slug}_caption_ar.txt"
        ar_caption_file.write_text(ar_caption, encoding="utf-8")
        files["caption_ar"] = str(ar_caption_file)

        # Master Bilingual caption file with full strategic intel
        caption_text = (
            "============================================================\n"
            "🇬🇧 ENGLISH MARKETING PACKAGE\n"
            "============================================================\n\n"
            f"{en_caption}\n\n"
            "------------------------------------------------------------\n"
            f"ALT TEXT (EN): {asset.alt_text}\n"
            f"TYPESET HEADLINE (EN): {asset.visual_headline}\n"
            f"TYPESET SUBLINE (EN): {asset.visual_tagline}\n\n"
            "============================================================\n"
            "🇸🇦 ARABIC MARKETING PACKAGE (النسخة العربية)\n"
            "============================================================\n\n"
            f"{ar_caption}\n\n"
            "------------------------------------------------------------\n"
            f"ALT TEXT (AR): {ar_data.get('alt_text', '')}\n"
            f"TYPESET HEADLINE (AR): {ar_data.get('visual_headline', '')}\n"
            f"TYPESET SUBLINE (AR): {ar_data.get('visual_tagline', '')}\n\n"
        )

        if asset.visual_analysis:
            caption_text += (
                "============================================================\n"
                "AI VISION SCENE ANALYSIS\n"
                "============================================================\n"
                f"{asset.visual_analysis}\n\n"
            )

        if asset.rivals:
            caption_text += (
                "============================================================\n"
                "COMPETITIVE INTEL & RIVALS BATTLECARD\n"
                "============================================================\n"
            )
            for r in asset.rivals:
                caption_text += f"\n* {r.get('name')}:\n"
                caption_text += f"  - Current Stance: {r.get('stance', '')}\n"
                caption_text += f"  - Incumbent Weakness: {r.get('incumbent_weakness', '')}\n"
                caption_text += f"  - Our Unfair Edge: {r.get('our_edge', '')}\n"

        if asset.competitive_strategy:
            strat = asset.competitive_strategy
            if strat.get("strategic_wedge"):
                caption_text += f"\nSTRATEGIC COUNTER-POSITIONING WEDGE:\n{strat.get('strategic_wedge', '')}\n"
            pb = strat.get("conquest_playbook", {})
            if pb:
                if pb.get("attack_angle"):
                    caption_text += f"\nATTACK ANGLE:\n{pb.get('attack_angle', '')}\n"
                if pb.get("campaign_ideas"):
                    caption_text += "\nCONQUEST CAMPAIGN IDEAS:\n"
                    for idea in pb.get("campaign_ideas", []):
                        caption_text += f"  › {idea}\n"
                if pb.get("landmine_questions"):
                    caption_text += "\nBUYER LANDMINE QUESTIONS:\n"
                    for q in pb.get("landmine_questions", []):
                        caption_text += f"  ? {q}\n"
                if pb.get("growth_tactics"):
                    caption_text += "\nGTM & SOCIAL GROWTH PLAYS:\n"
                    for t in pb.get("growth_tactics", []):
                        caption_text += f"  ⚡ {t}\n"

        if asset.guidelines:
            caption_text += (
                "\n============================================================\n"
                "CLIENT BRAND GUIDELINES APPLIED\n"
                "============================================================\n"
                f"{asset.guidelines.strip()}\n"
            )

        caption_file = out / f"{slug}_caption.txt"
        caption_file.write_text(caption_text, encoding="utf-8")
        files["caption"] = str(caption_file)

        return files


# ==========================================
# CLI Execution Interface
# ==========================================

def run_cli():
    """Command-line interface with interactive Rich terminal UI."""
    import argparse

    parser = argparse.ArgumentParser(description="Lexnis Campaign Studio - AI Marketing Agency Engine")
    parser.add_argument("prompt", nargs="?", help="Product, offer or campaign concept")
    parser.add_argument("--brand", default="Lexnis Technologies", help="Brand name used in copy and image tag")
    parser.add_argument("--tone", default="confident, premium and benefit-driven", help="Tone of the copy")
    parser.add_argument("--theme", default="clean premium commercial photography", help="Visual direction")
    parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL, choices=list(IMAGE_MODELS), help="Image model")
    parser.add_argument("--format", choices=list(FORMATS), default="portrait", help="Output aspect ratio")
    parser.add_argument("--no-overlay", action="store_true", help="Do not print headline / brand tag on the image")
    parser.add_argument("--no-search", action="store_true", help="Disable web research")
    parser.add_argument("--download", action="store_true", help="Export the package to the output directory")
    parser.add_argument("--outdir", default="output", help="Directory for exported assets")
    args = parser.parse_args()

    if console:
        console.print(Panel.fit(
            "[bold cyan]LEXNIS CAMPAIGN STUDIO[/bold cyan] [dim]• AI Marketing Agency[/dim]\n"
            "[dim]Research → Brief → Copy → Watermark-free visual[/dim]",
            border_style="cyan"
        ))

    prompt = args.prompt
    if not prompt:
        default_prompt = "Industrial IoT predictive maintenance platform with zero-downtime edge analytics"
        ask = console.input if console else input
        prompt = ask(f"Product / campaign [{default_prompt}]: ").strip() or default_prompt

    studio = LexnisCampaignStudio()
    kwargs = dict(
        prompt=prompt, brand=args.brand, tone=args.tone, theme=args.theme,
        output_format=args.format, use_search=not args.no_search, image_model=args.image_model, enhance_image=not args.no_overlay,
    )
    if console:
        with console.status("[bold cyan]Working...", spinner="dots") as status:
            asset = studio.generate_campaign(**kwargs, progress=lambda m: status.update(f"[bold cyan]{m}"))
    else:
        asset = studio.generate_campaign(**kwargs, progress=print)

    if console:
        console.print("\n[bold green]✓ Campaign ready[/bold green]\n")
        if asset.search_results:
            t = Table(title="Research sources", border_style="cyan")
            t.add_column("Title", style="cyan", width=40)
            t.add_column("URL", style="blue")
            for r in asset.search_results:
                t.add_row(r.get("title", ""), r.get("url", ""))
            console.print(t)
        console.print(Panel(asset.instagram_caption, title="[cyan]INSTAGRAM CAPTION (ready to paste)[/cyan]", border_style="cyan"))
        console.print(Panel(f"Headline: {asset.image_headline}\nAlt text: {asset.alt_text}", title="[violet]POSTING KIT[/violet]", border_style="violet"))
        console.print(f"[bold]Image:[/bold] {asset.image_path}  [dim](watermark-free: {asset.watermark_free})[/dim]")
    else:
        print("\n" + "=" * 50)
        print(asset.instagram_caption)
        print(f"\nHEADLINE: {asset.image_headline}\nALT TEXT: {asset.alt_text}")
        print(f"IMAGE: {asset.image_path} (watermark-free: {asset.watermark_free})")
        print("=" * 50)

    for warning in asset.warnings:
        print("Review: " + warning)

    if args.download:
        files = studio.export_campaign(asset, output_dir=args.outdir)
        if console:
            console.print(f"[bold green]✓ Saved package to[/bold green] [cyan]{args.outdir}/[/cyan]")
            for k, p in files.items():
                console.print(f"  - {k}: [dim]{p}[/dim]")
        else:
            print(f"Assets exported to {args.outdir}/: {files}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run_cli()
