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
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict, field

from visual_engine import OPEN_MODELS, FORMATS, photo_direction, open_model_image, compose_ad, cloudflare_image, LOCAL_MODEL, local_model_ready, local_image

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
DEFAULT_IMAGE_MODEL = os.getenv("IMAGE_MODEL") or (LOCAL_MODEL if local_model_ready() else "cf:flux-schnell")

# Image models available (Google AI Studio Imagen + FLUX photorealism)
IMAGE_MODELS = {
    "gemini-image": "Google AI Studio Imagen (Gemini Image)",
    "black-forest-labs/flux.1.1-pro": "FLUX 1.1 Pro (Apple/Studio Photorealism)",
    "flux-realism": "FLUX Realism (Hardware Macro & Textures)",
    "black-forest-labs/flux.1-schnell": "FLUX Schnell (High-Speed Packshot)",
    "flux": "FLUX Standard (Commercial Tech)",
}
IMAGE_MODELS.update(OPEN_MODELS)
IMAGE_MODELS[LOCAL_MODEL] = "Segmind Vega — local GPU, no API key"
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


PROMPT_ENHANCER_PROMPT = """Improve this marketing request while preserving its exact product,
brand, color, location and user intent. Never select a different product for an ambiguous brand.
Never add specifications, dates, launch availability, prices or performance claims.
Use a photographic campaign concept with a clear audience and a single emotional benefit.
Return JSON with detected_brand, product_name, enhanced_prompt, suggested_tone, suggested_theme.
Include the original request verbatim in enhanced_prompt. If product is unknown, leave product_name empty.
"""


AGENT1_COPYWRITER_PROMPT = """You are Agent 1: Senior Copywriter and Creative Strategist at an award-winning creative agency.
Draft an initial Instagram product launch campaign for the brand "{brand}" based on the creative brief below.

Tone: {tone}
Visual direction: {theme}

Rules:
- Plain text only. NO markdown: no **bold**, no #headings, no bullet asterisks.
- The hook must stop the scroll in under 125 characters.
- Caption: 3-4 short paragraphs (1-3 sentences each), scannable, written to ONE person ("you").
- Use 0-3 tasteful emojis max, never at the start of every line.
- Highlights: 3 short benefit lines (max 12 words each), outcome first.
- Hashtags: 8-12 relevant hashtags.
- Image Headline: 2-4 word luxury product title (e.g. 'TESLA // CYBERCAB').
- visual_concept: Detailed description of physical subject, materials, setting, and lighting.
- agent1_rationale: 1-2 sentence explanation of your chosen creative angle and target audience hook.

Return strictly valid RFC 8259 JSON:
{{
  "agent1_rationale": "Why I chose this creative angle...",
  "hook": "scroll-stopping first line, max 110 characters",
  "caption": "caption body paragraphs separated by blank lines",
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "cta": "one clear call to action line",
  "hashtags": ["#tag1", "#tag2"],
  "image_headline": "2-4 word luxury title",
  "visual_concept": "detailed description of the physical hardware and studio setting"
}}"""

COPYWRITER_PROMPT = AGENT1_COPYWRITER_PROMPT


AGENT2_DIRECTOR_CRITIC_PROMPT = """You are a creative director reviewing a marketing draft.
Return valid JSON with hook, caption, highlights (list), cta, hashtags (list),
image_headline (product name), alt_text, visual_prompt, critique_notes (list),
and agent_dialogue (list of objects with agent and message).
Use only facts from the supplied research/brief. Remove unsupported specifications and statistics.
Preserve the user's exact product and visual direction. Do not assume every Tesla is a Cybercab.
Create a photographic scene with natural materials, believable lighting and a clear hero product.
Use an appropriate lens; outdoor automotive campaigns need a wide tracking composition, not macro.
Reserve upper left and lower right negative space for typography. No text or watermarks in the photo.
Write a short, distinctive emotional hook, concise benefits and one clear CTA.
Never invent a website, official affiliation or endorsements. Report only changes actually made.
"""


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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


def detect_brand_and_product(prompt: str, current_brand: str = "") -> Tuple[str, str]:
    """
    Intelligently infer true target brand and concrete flagship product from user prompt.
    Preserve explicit product names. A brand without a product stays ambiguous.
    """
    p = (prompt or "").lower()
    b = (current_brand or "").strip()

    brand_catalog = [
        ("tesla", "Tesla", ["model 3", "model y", "model s", "model x", "cybercab", "robotaxi", "optimus", "roadster", "cybertruck", "fsd"]),
        ("apple", "Apple", ["vision pro", "spatial", "iphone", "macbook", "neural"]),
        ("nike", "Nike", ["alphafly", "vaporfly", "air max", "adapt"]),
        ("nvidia", "NVIDIA", ["blackwell", "dgx", "geforce", "cuda"]),
        ("porsche", "Porsche", ["mission x", "taycan", "911"]),
        ("sony", "Sony", ["alpha 1", "playstation", "spatial reality"]),
        ("microsoft", "Microsoft", ["surface", "copilot", "quantum"]),
    ]

    detected_brand = b if b and b.lower() != "lexnis technologies" else ""
    detected_product = ""

    for brand_key, canonical_name, products in brand_catalog:
        if re.search(rf"\b{brand_key}\b", p):
            if not detected_brand or b.lower() == "lexnis technologies":
                detected_brand = canonical_name
            for prod in products:
                if prod in p:
                    detected_product = f"{canonical_name} {prod.title()}"
                    break
            break

    if not detected_brand:
        detected_brand = b or "Lexnis Technologies"

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


# ==========================================
# Image helpers
# ==========================================

_FONT_CANDIDATES = {
    True: ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
    False: ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf"],
}


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
        if draw.textlength(test, font=font) <= max_width:
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
                for r in googlesearch.search(query, num_results=max_results, advanced=True):
                    results.append({
                        "title": getattr(r, "title", None) or query,
                        "url": getattr(r, "url", None) or "",
                        "description": getattr(r, "description", None) or "",
                    })
                    if len(results) >= max_results:
                        break
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
        """Free Google Search grounding through the Gemini API (needs GEMINI_API_KEY)."""
        key = os.getenv("GEMINI_API_KEY", "")
        if not key or requests is None:
            return [], ""
        model = os.getenv("GEMINI_RESEARCH_MODEL", DEFAULT_GEMINI_MODEL)
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={
                "contents": [{"parts": [{"text":
                    "Research this product/offer for a marketing team. Report: what it is, who makes it, "
                    "price range, key features and specs, verified numbers, what reviewers praise and "
                    f"criticize, main competitors, target customers. Be factual and concise.\n\nPRODUCT: {query}"
                }]}],
                "tools": [{"google_search": {}}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        cand = resp.json().get("candidates", [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        sources = [
            {"title": c["web"].get("title", ""), "url": c["web"].get("uri", ""), "description": ""}
            for c in cand.get("groundingMetadata", {}).get("groundingChunks", []) if c.get("web")
        ]
        return sources, text

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
        return sources + results, "\n".join(sections)

    # ---------- 2/3. LLM calls ----------

    def _chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.8, json_mode: bool = True) -> str:
        """Chat call that waits out short rate limits (anonymous tier: 1 reply / 30s per IP)."""
        import time
        for attempt in range(3):
            try:
                return self._chat_once(system_prompt, user_prompt, temperature, json_mode)
            except Exception as e:
                wait = re.search(r"[Rr]etry after (\d+)\s*s", str(e))
                if attempt == 2 or not wait or int(wait.group(1)) > 60:
                    raise
                time.sleep(int(wait.group(1)) + 1)

    def _chat_once(self, system_prompt: str, user_prompt: str, temperature: float, json_mode: bool) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}

        # Fallback models if using Gemini or Pollinations endpoint
        models_to_try = [self.model]
        if getattr(self, "text_engine", "") == "gemini":
            for m in ["gemini-3.5-flash-lite", "gemini-3.5-flash"]:
                if m not in models_to_try:
                    models_to_try.append(m)
        elif "pollinations" in getattr(self, "base_url", "").lower() or getattr(self, "text_engine", "") == "pollinations-anonymous":
            for m in ["mistral", "deepseek", "qwen"]:
                if m not in models_to_try:
                    models_to_try.append(m)

        last_exc = None
        for current_model in models_to_try:
            try:
                if HAS_OPENAI_LIB:
                    client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=45.0)
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
                        timeout=45,
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"] or ""
                    if content.strip():
                        return content
            except Exception as e:
                last_exc = e
                # If model is 503/502/504 or rate-limited, try next candidate model
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
            self.generation_warnings.append("A text generation step failed; template copy needs editorial review.")
            return dict(fallback_schema), raw or ""

        raise RuntimeError(f"Model did not return valid JSON: {last_err}")

    def build_brief(self, prompt: str, brand: str, research: str) -> Dict[str, Any]:
        user = f"BRAND: {brand}\nREQUEST: {prompt}\n\nWEB RESEARCH:\n{research or 'No research available.'}"
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

    def enhance_user_prompt(self, user_prompt: str, brand: Optional[str] = None) -> Dict[str, Any]:
        """
        Transform a conversational, vague or instructional prompt into an executive-grade Fortune-500 launch brief.
        Also detects the true intended brand (e.g. Tesla instead of Lexnis Technologies).
        """
        detected_brand, detected_product = detect_brand_and_product(user_prompt, brand or "")

        fallback_enhanced = {
            "detected_brand": detected_brand,
            "product_name": detected_product,
            "enhanced_prompt": user_prompt + " Create a focused photographic campaign with a clear audience, one emotional benefit and concise copy. Verify any technical claims before use.",
            "suggested_tone": "confident, premium and benefit-driven",
            "suggested_theme": "Cinematic lifestyle photography",
        }

        user_message = f"RAW USER REQUEST: {user_prompt}\nCURRENT BRAND FIELD: {brand or detected_brand}"

        try:
            enhanced, _ = self._chat_json(PROMPT_ENHANCER_PROMPT, user_message, temperature=0.3, fallback_schema=fallback_enhanced)
            if not enhanced.get("enhanced_prompt"):
                enhanced["enhanced_prompt"] = fallback_enhanced["enhanced_prompt"]
            if not enhanced.get("detected_brand"):
                enhanced["detected_brand"] = detected_brand
            for k in ["enhanced_prompt", "detected_brand", "product_name", "suggested_tone", "suggested_theme"]:
                if k in enhanced and isinstance(enhanced[k], str):
                    enhanced[k] = clean_social_text(enhanced[k])
            return enhanced
        except Exception:
            return {k: clean_social_text(v) if isinstance(v, str) else v for k, v in fallback_enhanced.items()}

    def collaborative_generation(
        self,
        prompt: str,
        brand: str,
        brief: Dict[str, Any],
        tone: str,
        theme: str,
        step_callback=None
    ) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[str]]:
        """
        Dual-agent collaborative pipeline:
        1. Agent 1 (Lead Copywriter & Strategist) drafts initial copy & visual concept.
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

        # 1. Agent 1 Draft
        step("Agent 1 (Lead Copywriter) drafting initial campaign concept...")
        agent1_sys = AGENT1_COPYWRITER_PROMPT.format(brand=brand, tone=tone, theme=theme)
        agent1_user = f"ORIGINAL REQUEST: {prompt}\n\nCREATIVE BRIEF:\n{json.dumps(brief, indent=2, ensure_ascii=False)}"

        try:
            draft, _ = self._chat_json(agent1_sys, agent1_user, temperature=0.75, fallback_schema=agent1_fallback)
        except Exception:
            draft = agent1_fallback

        # 2. Agent 2 Critique & Polish
        step("Agent 2 (Creative Director & Art Critic) reviewing, critiquing & polishing...")

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
            f"CREATIVE BRIEF:\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
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
        if model == LOCAL_MODEL:
            return local_image(visual_prompt, seed, width, height)
        if model == "cf:flux-schnell":
            return cloudflare_image(visual_prompt, seed)
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
            if not self.gemini_key:
                raise RuntimeError("Set GEMINI_API_KEY to use Gemini image generation. Image access depends on your quota.")
            try:
                response = requests.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/" + os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image") + ":generateContent",
                    headers={"x-goog-api-key": self.gemini_key},
                    json={"contents": [{"parts": [{"text": visual_prompt}]}],
                          "generationConfig": {"responseModalities": ["IMAGE"]}}, timeout=120)
                if response.ok:
                    for candidate in response.json().get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if part.get("inlineData", {}).get("data"):
                                return base64.b64decode(part["inlineData"]["data"]), True
            except requests.RequestException as exc:
                raise RuntimeError("Cannot connect to Gemini image generation. Check network access and retry the visual.") from exc
            raise RuntimeError(f"Gemini image generation failed (HTTP {response.status_code}). Check your model access and image quota.")
        base = POLLINATIONS_GEN_BASE + "/image" if self.pollinations_key else LEGACY_IMAGE_BASE
        headers = {"Authorization": f"Bearer {self.pollinations_key}"} if self.pollinations_key else {}
        try:
            response = requests.get(f"{base}/{urllib.parse.quote(visual_prompt, safe='')}",
                params={"model": model, "width": width, "height": height, "seed": seed},
                headers=headers, timeout=90)
            if response.ok and len(response.content) > 2000 and not is_pollinations_error_card(response.content):
                return response.content, bool(self.pollinations_key)
        except requests.RequestException:
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
    ) -> Tuple[Path, Path, bool]:
        """Render (and cache) the base visual, then composite the post. Returns (post, clean, watermark_free)."""
        if model in LEGACY_MODEL_ALIASES or not model:
            model = DEFAULT_IMAGE_MODEL
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        width, height = FORMATS[output_format]
        provider = os.getenv("IMAGE_PROVIDER", "huggingface")
        key = hashlib.sha1(f"photo-v3|{visual_prompt}|{seed}|{model}|{provider}|{width}|{height}|{bool(self.pollinations_key)}".encode()).hexdigest()[:16]
        clean_path = out_dir / f"{key}_clean.jpg"
        marker = out_dir / f"{key}.wm"  # present when the cached render came from the anonymous tier

        if clean_path.exists():
            watermark_free = not marker.exists()
        else:
            data, watermark_free = self._fetch_image_bytes(visual_prompt, seed, model, (width + 31) // 32 * 32, (height + 31) // 32 * 32)
            if not HAS_PIL:
                clean_path.write_bytes(data)
                return clean_path, clean_path, watermark_free
            try:
                img = fit_cover(Image.open(io.BytesIO(data)), width, height)
            except Exception as exc:
                raise RuntimeError("Image provider returned an invalid image. Retry the visual.") from exc
            img = ImageEnhance.Contrast(img).enhance(1.04)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))
            img.save(clean_path, "JPEG", quality=95, optimize=True)
            if not watermark_free:
                marker.touch()

        if not overlay or not HAS_PIL or not (headline or brand):
            return clean_path, clean_path, watermark_free

        clean_hl = headline.strip()
        tag = hashlib.sha1(f"ad-v3|{clean_hl}|{brand}|{tagline}".encode()).hexdigest()[:8]
        post_path = out_dir / f"{key}_post_{tag}.jpg"
        if not post_path.exists():
            compose_post(Image.open(clean_path), headline=clean_hl, brand=brand, tagline=tagline).save(
                post_path, "JPEG", quality=95, optimize=True
            )
        return post_path, clean_path, watermark_free

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
    ) -> CampaignAsset:
        """
        Run the full agency pipeline with Dual-Agent Collaborative refinement:
        Research -> Executive Brief -> Agent 1 Draft -> Agent 2 Critique & Polish -> FLUX Visual.
        """
        step = progress or (lambda msg: None)
        tone = tone or "confident, premium and benefit-driven"
        theme = theme or "Cinematic lifestyle photography"
        brand = brand or "Lexnis Technologies"

        # 0. Intelligent Brand Detection & Executive Prompt Enhancement
        detected_brand, detected_prod = detect_brand_and_product(prompt, brand)
        if detected_brand and (brand.lower() == "lexnis technologies" or not brand):
            brand = detected_brand

        # The original request governs product identity and creative direction.
        enhanced_prompt = ""
        effective_prompt = prompt

        search_results: List[Dict[str, str]] = []
        research = ""
        if use_search:
            step("Researching the product on the web...")
            try:
                search_query = f"{brand} {detected_prod or prompt}"
                search_results, research = self.research_product(search_query)
            except Exception:
                search_results, research = [], ""

        step("Building the creative brief...")
        brief = self.build_brief(effective_prompt, brand, research)

        # Dual-Agent Collaboration Loop: Agent 1 (Draft) -> Agent 2 (Critique & Polish)
        post, dialogue, critique_notes = self.collaborative_generation(
            effective_prompt, brand, brief, tone, theme, step_callback=step
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
        if not raw_visual or len(raw_visual) < 25 or any(cmd in raw_visual.lower() for cmd in ["draft a", "create a", "write a", "package for"]):
            visual_prompt = build_flux_commercial_prompt(effective_prompt, theme, brand)
        else:
            visual_prompt = raw_visual
            if "no text" not in visual_prompt.lower():
                visual_prompt += ", no text, no letters, no logos, no watermark"

        if seed is None:
            seed = random.randint(100000, 999999)

        step("Rendering the visual...")
        warnings = list(self.generation_warnings)
        if not research:
            warnings.append("No web evidence retrieved. Review product claims before publishing.")
        try:
            post_path, clean_path, watermark_free = self.render_image(
                visual_prompt, seed, model=image_model, headline=headline, brand=brand,
                overlay=enhance_image, output_format=output_format, tagline=hook[:110])
            image_status = "ready"
        except RuntimeError as exc:
            post_path = clean_path = None
            watermark_free = False
            image_status = "unavailable"
            warnings.append(str(exc))

        raw_response = json.dumps({"brief": brief, "post": post, "dialogue": dialogue, "critique": critique_notes}, indent=2, ensure_ascii=False)
        return CampaignAsset(
            prompt=prompt,
            hook=hook,
            caption=caption,
            highlights=highlights,
            hashtags=hashtags,
            visual_prompt=visual_prompt,
            image_url=post_path.as_uri() if post_path else "",
            raw_response=raw_response,
            seed=seed,
            search_results=search_results,
            brand=brand,
            cta=cta,
            image_headline=headline,
            alt_text=alt_text,
            instagram_caption=build_instagram_caption(hook, caption, highlights, cta, hashtags),
            brief=brief,
            image_model=image_model if image_model not in LEGACY_MODEL_ALIASES else DEFAULT_IMAGE_MODEL,
            image_path=str(post_path) if post_path else "",
            clean_image_path=str(clean_path) if clean_path else "",
            watermark_free=watermark_free,
            text_engine=f"{self.text_engine}:{self.model}",
            agent_dialogue=dialogue,
            critique_notes=critique_notes,
            enhanced_prompt=enhanced_prompt,
            output_format=output_format, image_status=image_status, warnings=warnings,
        )

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
        """Save campaign package: post image, clean image, metadata (.json) and caption (.txt)."""
        import shutil

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"[^\w\d]+", "_", asset.prompt[:30].strip()).strip("_").lower() or f"campaign_{asset.seed}"
        files: Dict[str, str] = {}

        image_file = out / f"{slug}_post.jpg"
        if asset.image_path and Path(asset.image_path).exists():
            shutil.copyfile(asset.image_path, image_file)
            files["image"] = str(image_file)

        if asset.clean_image_path and Path(asset.clean_image_path).exists() and asset.clean_image_path != asset.image_path:
            clean_file = out / f"{slug}_clean.jpg"
            shutil.copyfile(asset.clean_image_path, clean_file)
            files["clean_image"] = str(clean_file)

        json_file = out / f"{slug}_data.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(asset.to_dict(), f, indent=2, ensure_ascii=False)
        files["json"] = str(json_file)

        caption_text = asset.instagram_caption or build_instagram_caption(
            asset.hook, asset.caption, asset.highlights, asset.cta, asset.hashtags
        )
        if asset.alt_text:
            caption_text += f"\n\n---\nALT TEXT: {asset.alt_text}"
        if asset.critique_notes:
            caption_text += "\n\n---\nEXECUTIVE CRITIQUE & POLISH NOTES:\n" + "\n".join(
                f"- {note}" for note in asset.critique_notes
            )
        if asset.agent_dialogue:
            caption_text += "\n\n---\nDUAL-AGENT COLLABORATION LOG:\n" + "\n".join(
                f"[{msg.get('agent', 'Agent')}]: {msg.get('message', '')}" for msg in asset.agent_dialogue
            )
        if asset.search_results:
            caption_text += "\n\n---\nRESEARCH SOURCES:\n" + "\n".join(
                f"- {r.get('title')}: {r.get('url')}" for r in asset.search_results
            )
        txt_file = out / f"{slug}_caption.txt"
        txt_file.write_text(caption_text, encoding="utf-8")
        files["caption"] = str(txt_file)

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
