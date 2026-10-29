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
import hashlib
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict, field

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
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
DEFAULT_IMAGE_MODEL = os.getenv("IMAGE_MODEL", "black-forest-labs/flux.1.1-pro")

# Image models available on the Pollinations gen API (FLUX is the gold-standard for photorealism)
IMAGE_MODELS = {
    "black-forest-labs/flux.1.1-pro": "FLUX 1.1 Pro (Apple/Studio Photorealism)",
    "flux-realism": "FLUX Realism (Hardware Macro & Textures)",
    "black-forest-labs/flux.1-schnell": "FLUX Schnell (High-Speed Packshot)",
    "flux": "FLUX Standard (Commercial Tech)",
}
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


PROMPT_ENHANCER_PROMPT = """You are the Principal Creative Strategist at an elite Silicon Valley marketing agency (ex-Apple, ex-Tesla launch directors).
Your mission is to take simple, vague, conversational, or under-specified campaign requests (like "Research Tesla and write...", "New Apple device", "Nike launch") and transform them into an ultra-specific, executive-grade product launch brief for Fortune-500 brands.

Rules:
1. Detect or infer the true target Brand:
   - If the request mentions Tesla, brand is "Tesla" (never combine with default brands like Lexnis). If Apple, brand is "Apple".
2. Select or engineer a concrete flagship innovation / product:
   - For Tesla: e.g. "Tesla Cybercab" (Autonomous Robotaxi Unveiling) with zero steering wheel, zero pedals, 20 kW inductive resonant wireless charging, unpainted cold-rolled 300-series stainless steel dihedral doors, end-to-end neural vision.
   - For Apple: e.g. "Apple Vision Pro Spatial Computing & Neural Engine".
   - If already specific, preserve and deepen the technical specificity.
3. Inject authentic physical materials, engineering physics, and hardware design details.
4. Define a high-stakes commercial launch hook and target market.
5. Format strictly as valid RFC 8259 JSON. No trailing commas.

Return ONLY a JSON object:
{
  "detected_brand": "Tesla",
  "product_name": "Tesla Cybercab",
  "enhanced_prompt": "Tesla Cybercab Autonomous Robotaxi Launch: Announce the arrival of commercial driverless transit. Highlight the zero-steering-wheel/zero-pedal cabin architecture, 20 kW resonant inductive wireless charging (no charge ports), butterfly dihedral doors, unpainted cold-rolled stainless steel body, and end-to-end neural vision AI. Target enterprise fleet operators and urban commuters.",
  "suggested_tone": "confident, visionary and disruptive",
  "suggested_theme": "Apple Minimalist Hero (Luxury Tech)"
}"""


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


AGENT2_DIRECTOR_CRITIC_PROMPT = """You are Agent 2: Executive Creative Director and Head of Visuals (former creative director for Fortune-500 launches at Apple, Tesla, and Porsche).
You are reviewing the initial campaign draft produced by Agent 1 (Senior Copywriter).
Your mission is to ruthlessly critique the draft, strip any corporate clichés or passive language, ensure high-stakes commercial urgency, and finalize the production-ready campaign assets.

Critique Checklist:
1. Hook Urgency: Is it passive or cliché? Replace with a high-impact, scroll-stopping opening.
2. Authentic Engineering: Ensure verified technical specs (e.g., zero steering wheel, zero pedals, 20 kW inductive charging, stainless steel) are prominent.
3. FLUX Photography Direction: Transform the visual concept into a pristine 5-part FLUX commercial photography prompt:
   - 1. Tangible physical hardware & materials (matte dark titanium, cold-rolled stainless steel, curved obsidian glass).
   - 2. Studio pedestal & setting (dark honed graphite floor, seamless dark slate infinity cove).
   - 3. Studio lighting (overhead strip softbox casting razor-sharp specular reflection line along body curves, subtle cyan rim light).
   - 4. Camera & optics (Hasselblad H6D-100c, 100mm f/2.8 commercial macro lens, shallow DOF).
   - 5. Composition: Clean negative space in top third for headline.
   - ABSOLUTELY NO text, letters, numbers, logos, or watermarks.

Return strictly valid RFC 8259 JSON:
{{
  "critique_notes": [
    "Critique of Agent 1's hook and how it was elevated for scroll-stopping impact",
    "Critique of technical accuracy, specs, and brand identity injection",
    "Critique of visual lighting, optics, and FLUX photography parameters"
  ],
  "agent_dialogue": [
    {{"agent": "Agent 1 (Lead Copywriter)", "message": "Drafted initial concept: [summary of draft]"}},
    {{"agent": "Agent 2 (Executive Creative Director)", "message": "Critique & Polish: [specific enhancements made to hook, copy & FLUX art direction]"}}
  ],
  "hook": "Final scroll-stopping first line, max 110 characters",
  "caption": "Final polished caption body",
  "highlights": ["final spec 1", "final spec 2", "final spec 3"],
  "cta": "Final clear call to action",
  "hashtags": ["#tag1", "#tag2", ...],
  "image_headline": "2-4 word luxury product title (e.g. 'TESLA // CYBERCAB')",
  "alt_text": "Accessible description of the image, max 200 characters",
  "visual_prompt": "Final 5-part FLUX commercial photography prompt"
}}"""


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
    E.g., if user writes 'Research Tesla and write a product launch hook...',
    it detects brand 'Tesla' and product 'Tesla Cybercab' instead of staying 'Lexnis Technologies'.
    """
    p = (prompt or "").lower()
    b = (current_brand or "").strip()

    brand_catalog = [
        ("tesla", "Tesla", ["cybercab", "robotaxi", "optimus", "roadster", "cybertruck", "fsd"]),
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
            if not detected_product:
                if brand_key == "tesla":
                    detected_product = "Tesla Cybercab"
                elif brand_key == "apple":
                    detected_product = "Apple Spatial Computing"
                elif brand_key == "nvidia":
                    detected_product = "NVIDIA AI Accelerator"
                elif brand_key == "nike":
                    detected_product = "Nike Flagship Innovation"
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
    """
    Synthesize a luxury, magazine-editorial product title (2-4 words) with optional // accent.
    Never outputs instructional verbs like 'Draft a...' or 'Product launch package for...'.
    """
    s = (text or "").strip()
    bad_tokens = [
        "draft a", "create a", "write a", "generate a", "design a",
        "product launch", "launch pack", "launch package", "pac", "package for",
        "keynote script", "specifications", "complete product", "visual image description", "social media post"
    ]
    if not s or any(tok in s.lower() for tok in bad_tokens):
        s = prompt or text or brand

    # Strip instruction command prefixes
    s = re.sub(
        r"^(?:draft|create|generate|write|design|build|produce|research)\s+(?:a|an)?\s*(?:complete\s+)?(?:product\s+)?(?:launch\s+)?(?:package|post|copy|campaign|specifications|announcement|hook)?\s*(?:for|about)?\s*(?:a|an)?\s*(?:revolutionary\s+|new\s+|cutting-edge\s+|next-gen\s+)*",
        "",
        s,
        flags=re.I,
    ).strip()
    s = re.sub(r"^.*?\b(?:package|post|campaign|announcement|description)\s+(?:for|about)\s+", "", s, flags=re.I).strip()

    # Strip trailing clauses
    s = re.split(r"[.;,]\s*(?:include|focusing|with|designed|featuring|and\s+a)", s, flags=re.I)[0].strip()
    s = re.sub(r"\s+(?:for|about|with|and|in|on|at|a|the)$", "", s, flags=re.I).strip()

    # Enrich high-impact prompt keywords if title is generic
    prompt_lower = (prompt or "").lower()
    brand_lower = (brand or "").lower()

    if "tesla" in prompt_lower or brand_lower == "tesla":
        if "cybercab" in prompt_lower or "robotaxi" in prompt_lower or "unsupervised" in prompt_lower:
            s = "TESLA // CYBERCAB"
        elif "optimus" in prompt_lower or "humanoid" in prompt_lower or "robot" in prompt_lower:
            s = "TESLA // OPTIMUS"
        elif "roadster" in prompt_lower:
            s = "TESLA // ROADSTER"
        elif "fsd" in prompt_lower or "autonom" in prompt_lower:
            s = "TESLA // AUTONOMOUS"
        else:
            s = "TESLA // CYBERCAB"
    elif "apple" in prompt_lower or brand_lower == "apple":
        if "spatial" in prompt_lower or "neural" in prompt_lower or "vision" in prompt_lower:
            s = "APPLE SPATIAL // NEURAL VISION"
        else:
            s = "APPLE // NEXT-GEN DEVICE"
    elif "nvidia" in prompt_lower or brand_lower == "nvidia":
        s = "NVIDIA // BLACKWELL AI"
    elif "porsche" in prompt_lower or brand_lower == "porsche":
        s = "PORSCHE // MISSION X"
    elif "nike" in prompt_lower or brand_lower == "nike":
        s = "NIKE // NEXT-GEN PRO"
    elif "predictive" in prompt_lower or "iot" in prompt_lower or "maintenance" in prompt_lower:
        s = "LEXNIS // PREDICTIVE IoT"
    elif "robotic" in prompt_lower or "fleet" in prompt_lower:
        s = "AUTONOMOUS // ROBOTICS FLEET"
    elif "digital twin" in prompt_lower:
        s = "DIGITAL TWIN // REAL-TIME AI"

    words = s.split()
    if len(words) > 4:
        s = " ".join(words[:4])

    s = s.upper()
    if not s or len(s) < 3 or s in ["PAC", "PACKAGE", "DEVICE", "LAUNCH", "HOOK"]:
        s = f"{brand.upper()} // INNOVATION"
    elif " // " not in s and len(words) >= 2:
        w = s.split()
        if len(w) == 2:
            s = f"{w[0]} // {w[1]}"
        elif len(w) >= 3:
            remainder = " ".join(w[2:])
            s = f"{w[0]} {w[1]} // {remainder}"
    return s


def build_flux_commercial_prompt(user_prompt: str, theme: str = "", brand: str = "Lexnis Technologies") -> str:
    """
    Construct a world-class 5-part commercial photography prompt optimized for FLUX.1 models.
    Enforces pure physical hardware product photography and completely crowds out anime/CGI.
    Structure: Physical Hardware Subject & Materials + Setting/Pedestal + Studio Lighting + Optics & Camera + Clean Space.
    """
    p = (user_prompt or "").lower()
    t = (theme or "").lower()
    b = (brand or "").lower()

    if "tesla" in p or b == "tesla":
        if "optimus" in p or "humanoid" in p:
            subject = "genuine commercial catalog studio photograph of a physical Tesla Optimus Gen-3 humanoid robot, matte white composite and dark carbon fiber finish, precision tactile fingers, dark obsidian visor head unit"
            setting = "standing poised on a dark honed graphite pedestal in a cleanroom minimalist studio"
            lighting = "dramatic low-key studio lighting, overhead linear strip softbox casting crisp specular highlight line down the shoulder actuators, cool cyan edge rim light, soft floor contact shadows"
        else:
            subject = "genuine commercial studio hero photograph of a physical, tangible Tesla Cybercab autonomous vehicle, monolithic unpainted cold-rolled 300-series stainless steel exterior, aerodynamic sculpted fastback silhouette with gullwing butterfly doors, continuous horizon LED lightbar across the front fascia, dark tinted obsidian glass panoramic canopy"
            setting = "resting on a seamless dark slate infinity cove with subtle reflections"
            lighting = "overhead linear strip softbox casting razor-sharp specular reflection line along the stainless steel body curves, cool ambient fill, velvety contact shadows"
    elif "apple" in p or b == "apple":
        subject = "genuine commercial catalog studio photograph of a physical, tangible minimalist spatial computing headset with curved obsidian micro-OLED optical visor, machined matte dark titanium frame, chamfered precision ceramic edges"
        setting = "floating above a dark honed graphite monolith on a seamless dark slate infinity cove"
        lighting = "dramatic low-key commercial studio lighting, overhead linear strip softbox casting razor-sharp specular reflection along the curved titanium rim, subtle cool electric cyan edge rim light, velvety contact shadows"
    elif "robotic" in p or "fleet" in p:
        subject = "genuine commercial product photograph of a physical high-precision autonomous industrial robotic arm, matte black anodized steel, exposed orange telemetry fiber optics"
        setting = "in a pristine futuristic cleanroom factory floor with dark polished reflective epoxy surface"
        lighting = "cool daylight studio key light, crisp neon cyan edge illumination, soft natural contact shadows underneath"
    elif "predictive" in p or "iot" in p or "sensor" in p:
        subject = "authentic commercial photograph of a tangible industrial edge AI compute module, brushed dark aluminum heatsink fins, glowing optic fiber data channels"
        setting = "resting on dark architectural slate, centered heroic product composition"
        lighting = "overhead diffused softbox with deep directional shadows, subtle electric cyan specular accent highlights"
    elif "digital twin" in p:
        subject = "commercial photography of a physical industrial digital twin optical glass display module, floating translucent cyan telemetry nodes and laser wireframes"
        setting = "in a dark minimalist executive tech showroom on a dark obsidian table"
        lighting = "ambient neon luminescence, sharp rim lighting from behind, deep contrast"
    else:
        clean_sub = re.sub(r'^(?:draft|create|generate|write|design|research)\s+(?:a|an)?\s*[^.]*?(?:package|post|copy|campaign|device|launch|hook)\s+(?:for|about)?\s*', '', user_prompt, flags=re.I).strip()
        clean_sub = clean_sub.split('.')[0][:80] or "industrial automation hardware device"
        subject = f"commercial luxury product hero photograph of a tangible physical {clean_sub}, machined matte dark finish, precision chamfered details"
        setting = "resting on a dark minimalist stone pedestal in a luxury studio"
        lighting = "linear overhead strip-box lighting, crisp edge reflections, soft wrap-around fill light, natural contact shadows"

    if "teenage engineering" in t:
        setting = "resting on an architectural charcoal concrete workbench with subtle CAD blueprint alignment markings"
        lighting = "diffused daylight key light from the left and controlled fill light, crisp edge separation"
    elif "dyson" in t or "deep tech" in t:
        setting = "dark obsidian infinity cove background with subtle atmospheric haze"
        lighting = "cinematic low-key studio lighting with high-contrast edge rim highlights and crisp specular reflections on optical glass"

    optics = "shot on Hasselblad H6D-100c, 100mm f/2.8 commercial macro lens, eye-level hero perspective, shallow depth of field, sharp focus across body"
    composition = "real physical material textures with fine microscopic directional grain lines, clean empty negative space in top third for editorial headline, luxury commercial advertisement aesthetic, genuine physical hardware product photograph, zero digital illustration, no humans, no anime, no face, no watermark"

    return f"{subject}, {setting}, {lighting}, {optics}, {composition}"


def compose_post(img: Image.Image, headline: str = "", brand: str = "", accent: str = "#00F0FF") -> Image.Image:
    """Compose post with luxury magazine editorial typography, glassmorphism badge, and corner telemetry."""
    img = img.convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    pad = 72
    cyan_rgb = _hex_to_rgb(accent)

    # 1. Soft top & bottom gradient for text contrast
    grad_h = int(h * 0.40)
    for y in range(grad_h):
        alpha = int(220 * (1 - y / grad_h) ** 1.8)
        draw.line([(0, y), (w, y)], fill=(6, 9, 15, alpha))

    foot_h = int(h * 0.16)
    for y in range(h - foot_h, h):
        progress = (y - (h - foot_h)) / foot_h
        alpha = int(200 * progress ** 1.5)
        draw.line([(0, y), (w, y)], fill=(6, 9, 15, alpha))

    # 2. Minimalist Corner Telemetry Brackets
    c_len, c_w = 28, 2
    c_color = cyan_rgb + (140,)
    m = 36  # margin
    draw.line([(m, m), (m + c_len, m)], fill=c_color, width=c_w)
    draw.line([(m, m), (m, m + c_len)], fill=c_color, width=c_w)
    draw.line([(w - m - c_len, m), (w - m, m)], fill=c_color, width=c_w)
    draw.line([(w - m, m), (w - m, m + c_len)], fill=c_color, width=c_w)
    draw.line([(m, h - m), (m + c_len, h - m)], fill=c_color, width=c_w)
    draw.line([(m, h - m), (m, h - m - c_len)], fill=c_color, width=c_w)
    draw.line([(w - m - c_len, h - m), (w - m, h - m)], fill=c_color, width=c_w)
    draw.line([(w - m, h - m), (w - m, h - m - c_len)], fill=c_color, width=c_w)

    # 3. Top Frosted Glass Badge
    b_font = _load_font(20, bold=True)
    clean_b = (brand or "LEXNIS TECHNOLOGIES").strip().upper()
    if clean_b in ["TESLA", "APPLE", "NIKE", "NVIDIA", "PORSCHE"]:
        b_label = f"{clean_b} // OFFICIAL ARCHIVE"
    else:
        b_label = f"{clean_b} // B2B COMMERCIAL ARCHIVE"
    b_tw = draw.textlength(b_label, font=b_font)
    bx0, by0 = pad, pad - 12
    bx1, by1 = bx0 + b_tw + 48, by0 + 38
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=19, fill=(10, 14, 22, 190), outline=cyan_rgb + (90,), width=1)
    draw.ellipse([bx0 + 14, by0 + 14, bx0 + 24, by0 + 24], fill=cyan_rgb + (255,))
    draw.text((bx0 + 32, by0 + 9), b_label, font=b_font, fill=(230, 240, 255, 230))
    b_tw = draw.textlength(b_label, font=b_font)
    bx0, by0 = pad, pad - 12
    bx1, by1 = bx0 + b_tw + 48, by0 + 38
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=19, fill=(10, 14, 22, 190), outline=cyan_rgb + (90,), width=1)
    draw.ellipse([bx0 + 14, by0 + 14, bx0 + 24, by0 + 24], fill=cyan_rgb + (255,))
    draw.text((bx0 + 32, by0 + 9), b_label, font=b_font, fill=(230, 240, 255, 230))

    # 4. Editorial Headline
    if headline:
        headline = headline.strip()
        size = 80
        font = _load_font(size, bold=True)
        lines = _wrap(draw, headline, font, w - 2 * pad)
        while len(lines) > 3 and size > 48:
            size -= 6
            font = _load_font(size, bold=True)
            lines = _wrap(draw, headline, font, w - 2 * pad)

        y = by1 + 28
        line_h = int(size * 1.12)
        for line in lines[:3]:
            # Drop shadow
            draw.text((pad + 2, y + 3), line, font=font, fill=(0, 0, 0, 190))
            if " // " in line:
                part1, part2 = line.split(" // ", 1)
                p1_w = draw.textlength(part1, font=font)
                div_w = draw.textlength(" // ", font=font)
                draw.text((pad, y), part1, font=font, fill=(255, 255, 255, 255))
                draw.text((pad + p1_w, y), " // ", font=font, fill=cyan_rgb + (255,))
                draw.text((pad + p1_w + div_w, y), part2, font=font, fill=(240, 248, 255, 255))
            else:
                draw.text((pad, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_h

    # 5. Bottom Brand Tag & Telemetry Pill
    tag_font = _load_font(24, bold=True)
    t_label = (brand or "LEXNIS TECHNOLOGIES").upper()
    t_tw = draw.textlength(t_label, font=tag_font)
    tx0, ty1 = pad, h - pad
    tx0_end = tx0 + t_tw + 56
    draw.rounded_rectangle([tx0, ty1 - 48, tx0_end, ty1], radius=24, fill=(10, 14, 22, 190), outline=cyan_rgb + (80,), width=1)
    draw.ellipse([tx0 + 16, ty1 - 32, tx0 + 26, ty1 - 22], fill=cyan_rgb + (255,))
    draw.text((tx0 + 36, ty1 - 37), t_label, font=tag_font, fill=(255, 255, 255, 240))

    # Right technical pill
    spec_font = _load_font(20, bold=False)
    spec_text = "4:5 UHD // 1080×1350 // FLUX.1"
    spec_tw = draw.textlength(spec_text, font=spec_font)
    sx1 = w - pad
    sx0 = sx1 - spec_tw - 36
    draw.rounded_rectangle([sx0, ty1 - 44, sx1, ty1 - 4], radius=20, fill=(10, 14, 22, 160), outline=(255, 255, 255, 40), width=1)
    draw.text((sx0 + 18, ty1 - 35), spec_text, font=spec_font, fill=(160, 180, 205, 220))

    final = Image.alpha_composite(img, overlay).convert("RGB")
    final = ImageEnhance.Contrast(final).enhance(1.05)
    return final


def create_fallback_graphic(width: int = POST_WIDTH, height: int = POST_HEIGHT) -> bytes:
    """Generate a sleek, dark obsidian industrial 3D isometric schematic graphic."""
    img = Image.new("RGB", (width, height), (9, 13, 20))
    draw = ImageDraw.Draw(img)

    # 1. Perspective Grid
    cx, cy = width // 2, int(height * 0.6)
    grid_color = (20, 28, 42)
    cyan_dim = (0, 70, 90)
    cyan_bright = (0, 240, 255)

    for x in range(0, width + 1, 60):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height + 1, 60):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # 2. Glowing Core Ambient Light
    core_radius = 280
    for r in range(core_radius, 0, -10):
        alpha = int(45 * (1 - r / core_radius) ** 1.5)
        color = (int(0 * alpha / 45), int(220 * alpha / 45), int(255 * alpha / 45))
        draw.ellipse([cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.7)], fill=color)

    # 3. Isometric Central Chip / Cube Wireframe
    cube_size = 180
    top_pts = [
        (cx, cy - cube_size),
        (cx + int(cube_size * 1.2), cy - int(cube_size * 0.4)),
        (cx, cy + int(cube_size * 0.2)),
        (cx - int(cube_size * 1.2), cy - int(cube_size * 0.4)),
    ]
    draw.polygon(top_pts, fill=(15, 23, 36), outline=cyan_bright, width=2)

    left_pts = [
        (cx - int(cube_size * 1.2), cy - int(cube_size * 0.4)),
        (cx, cy + int(cube_size * 0.2)),
        (cx, cy + int(cube_size * 1.2)),
        (cx - int(cube_size * 1.2), cy + int(cube_size * 0.6)),
    ]
    draw.polygon(left_pts, fill=(12, 18, 28), outline=cyan_bright, width=2)

    right_pts = [
        (cx, cy + int(cube_size * 0.2)),
        (cx + int(cube_size * 1.2), cy - int(cube_size * 0.4)),
        (cx + int(cube_size * 1.2), cy + int(cube_size * 0.6)),
        (cx, cy + int(cube_size * 1.2)),
    ]
    draw.polygon(right_pts, fill=(18, 27, 42), outline=cyan_bright, width=2)

    # Laser Circuit Traces radiating outward
    for angle_deg in [30, 60, 120, 150, 210, 240, 300, 330]:
        rad = math.radians(angle_deg)
        x1 = cx + int(math.cos(rad) * 220)
        y1 = cy + int(math.sin(rad) * 160)
        x2 = cx + int(math.cos(rad) * 420)
        y2 = cy + int(math.sin(rad) * 310)
        draw.line([(x1, y1), (x2, y2)], fill=cyan_dim, width=2)
        draw.ellipse([x2 - 4, y2 - 4, x2 + 4, y2 + 4], fill=cyan_bright)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


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
        gemini_key = os.getenv("GEMINI_API_KEY", "")

        # Explicit overrides > Gemini > Pollinations (keyed) > anonymous legacy endpoint
        if api_key and base_url:
            self.api_key, self.base_url, self.model, self.text_engine = api_key, base_url, model or DEFAULT_TEXT_MODEL, "custom"
        elif gemini_key:
            self.api_key, self.base_url, self.model, self.text_engine = gemini_key, GEMINI_OPENAI_BASE, model or DEFAULT_GEMINI_MODEL, "gemini"
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

        # Fallback models if using anonymous Pollinations endpoint
        models_to_try = [self.model]
        if "pollinations" in getattr(self, "base_url", "").lower() or getattr(self, "text_engine", "") == "pollinations-anonymous":
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
                parsed = extract_json(raw, fallback_schema=fallback_schema)
                if parsed:
                    return parsed, raw
            except Exception as e:
                last_err = e
                user_prompt += "\n\nCRITICAL: Return ONLY a valid JSON object. Do not include markdown codeblocks, comments, or trailing commas."

        if raw:
            try:
                parsed = extract_json(raw, fallback_schema=fallback_schema)
                if parsed:
                    return parsed, raw
            except Exception:
                pass

        if fallback_schema:
            return dict(fallback_schema), raw or ""

        raise RuntimeError(f"Model did not return valid JSON: {last_err}")

    def build_brief(self, prompt: str, brand: str, research: str) -> Dict[str, Any]:
        user = f"BRAND: {brand}\nREQUEST: {prompt}\n\nWEB RESEARCH:\n{research or 'No research available.'}"
        fallback = {
            "product_name": prompt[:40].strip(),
            "category": "Next-Gen Technology",
            "one_liner": prompt[:120].strip(),
            "target_audience": "Forward-thinking developers, creators, and enterprise leaders",
            "pain_points": ["Legacy system constraints", "High latency and downtime"],
            "key_benefits": ["Unprecedented neural speed", "Sub-millisecond latency", "Enterprise-grade reliability"],
            "proof_points": [],
            "differentiator": "Proprietary neural architecture and spatial precision",
            "creative_angle": "The future of spatial intelligence, realized today",
            "cta_goal": "Explore the launch keynote and technical specifications"
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
            "product_name": detected_product or f"{detected_brand} Flagship Innovation",
            "enhanced_prompt": (
                f"{detected_product or detected_brand} Launch Package: Announce the next breakthrough in {detected_brand} engineering. "
                f"Highlight core physical hardware specifications, precision industrial design materials, and transformative commercial value. "
                f"Deliver an authoritative, high-urgency keynote hook, engaging narrative copy, and luxury studio hero photography."
            ),
            "suggested_tone": "confident, visionary and disruptive",
            "suggested_theme": "Apple Minimalist Hero (Luxury Tech)"
        }

        # If user explicitly asks about Tesla
        if "tesla" in user_prompt.lower() or detected_brand.lower() == "tesla":
            fallback_enhanced["enhanced_prompt"] = (
                "Tesla Cybercab Autonomous Robotaxi Launch: Announce the commercial arrival of full driverless mobility. "
                "Highlight the zero-steering-wheel and zero-pedal cabin architecture, 20 kW resonant inductive wireless charging (no charge plugs), "
                "sculpted butterfly dihedral doors, unpainted cold-rolled 300-series stainless steel exterior, and vision-only end-to-end neural networks. "
                "Deliver an ultra-compelling scroll-stopping hook, technical highlights, and luxury studio packshot photography."
            )
            fallback_enhanced["product_name"] = "Tesla Cybercab"
            fallback_enhanced["detected_brand"] = "Tesla"

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
            "agent1_rationale": f"Positioned {prod_name} as an industry-defining technological leap with high-urgency market appeal.",
            "hook": brief.get("one_liner") or f"Meet {prod_name}: the next leap in computing.",
            "caption": (
                f"Breakthrough architecture meets revolutionary precision.\n\n"
                f"Built to redefine what is possible, {prod_name} brings advanced intelligence into seamless harmony.\n\n"
                f"The next era of technology starts now."
            ),
            "highlights": [
                "Dedicated neural architecture with real-time processing",
                "Sub-millisecond latency and ultra-high efficiency",
                "Engineered for pro workflows and creative mastery"
            ],
            "cta": f"Discover the keynote and full specifications at {brand.lower().replace(' ', '')}.com",
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
            "critique_notes": [
                "Tightened the hook to eliminate passive phrasing and maximize scroll-stopping curiosity.",
                f"Verified and highlighted tangible technical specifications for {brand}.",
                "Upgraded visual art direction to 5-part FLUX commercial studio lighting with Hasselblad 100mm macro optics."
            ],
            "agent_dialogue": [
                {
                    "agent": "Agent 1 (Lead Copywriter)",
                    "message": f"Drafted launch concept for {prod_name}: '{draft.get('hook', '')}' emphasizing core capabilities and market differentiation."
                },
                {
                    "agent": "Agent 2 (Executive Creative Director)",
                    "message": "Elevated the copy: sharpened hook urgency, tightened paragraph pacing, and crafted the 5-part FLUX commercial photography prompt with clean editorial space."
                }
            ],
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

    def _fetch_image_bytes(self, visual_prompt: str, seed: int, model: str) -> Tuple[bytes, bool]:
        """Returns (image bytes, watermark_free). Tries multiple models/endpoints with fallback graphic."""
        if requests is None:
            raise RuntimeError("`requests` is required to render images.")

        clean_prompt = re.sub(
            r"^(?:draft|create|generate|write|design)\s+(?:a|an)\s+[^.]*?(?:package|post|copy|campaign|device|launch)\s+(?:for|about)?\s*",
            "",
            visual_prompt,
            flags=re.IGNORECASE,
        ).strip()
        if not clean_prompt or len(clean_prompt) < 15:
            clean_prompt = visual_prompt
        clean_prompt = clean_prompt[:600]

        encoded = urllib.parse.quote(clean_prompt)

        # 1. Keyed Pollinations API
        if self.pollinations_key:
            try:
                resp = requests.get(
                    f"{POLLINATIONS_GEN_BASE}/image/{encoded}",
                    params={"model": model, "width": RENDER_WIDTH, "height": RENDER_HEIGHT, "seed": seed},
                    headers={"Authorization": f"Bearer {self.pollinations_key}"},
                    timeout=45,
                )
                if resp.ok and len(resp.content) > 1000:
                    return resp.content, True
            except Exception:
                pass

        # 2. Free Pollinations Image endpoint with model rotation (flux -> turbo -> flux-realism -> default)
        # We request 864x1080 (native 4:5 FLUX aspect ratio) for 3x faster generation, then fit_cover upscales & sharpens to 1080x1350
        models_to_try = ["flux", "turbo", "flux-realism", None]
        for m in models_to_try:
            params = {"width": 864, "height": 1080, "seed": seed, "nologo": "true"}
            if m:
                params["model"] = m
            try:
                resp = requests.get(f"{LEGACY_IMAGE_BASE}/{encoded}", params=params, timeout=50)
                if resp.ok and len(resp.content) > 2000:
                    return resp.content, False
            except Exception:
                continue

        # 3. Gen API Schnell endpoint (public free tier fallback)
        try:
            resp = requests.get(
                f"{POLLINATIONS_GEN_BASE}/image/{encoded}",
                params={"model": "black-forest-labs/flux.1-schnell", "width": 864, "height": 1080, "seed": seed},
                timeout=45,
            )
            if resp.ok and len(resp.content) > 2000:
                return resp.content, True
        except Exception:
            pass

        # 4. If all external image servers are 503 / down, generate an elegant synthetic graphic
        if HAS_PIL:
            return create_fallback_graphic(POST_WIDTH, POST_HEIGHT), True

        raise RuntimeError("Image rendering servers are currently experiencing 503 high load. Please retry.")

    def render_image(
        self,
        visual_prompt: str,
        seed: int,
        model: str = DEFAULT_IMAGE_MODEL,
        headline: str = "",
        brand: str = "",
        overlay: bool = True,
        out_dir: Path = RENDERS_DIR,
    ) -> Tuple[Path, Path, bool]:
        """Render (and cache) the base visual, then composite the post. Returns (post, clean, watermark_free)."""
        if model in LEGACY_MODEL_ALIASES or not model:
            model = DEFAULT_IMAGE_MODEL
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        key = hashlib.sha1(f"{visual_prompt}|{seed}|{model}|{bool(self.pollinations_key)}".encode()).hexdigest()[:16]
        clean_path = out_dir / f"{key}_clean.jpg"
        marker = out_dir / f"{key}.wm"  # present when the cached render came from the anonymous tier

        if clean_path.exists():
            watermark_free = not marker.exists()
        else:
            data, watermark_free = self._fetch_image_bytes(visual_prompt, seed, model)
            if not HAS_PIL:
                clean_path.write_bytes(data)
                return clean_path, clean_path, watermark_free
            img = fit_cover(Image.open(io.BytesIO(data)))
            img = ImageEnhance.Contrast(img).enhance(1.04)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))
            img.save(clean_path, "JPEG", quality=95, optimize=True)
            if not watermark_free:
                marker.touch()

        if not overlay or not HAS_PIL or not (headline or brand):
            return clean_path, clean_path, watermark_free

        clean_hl = clean_product_headline(headline, brand=brand)
        tag = hashlib.sha1(f"{clean_hl}|{brand}".encode()).hexdigest()[:8]
        post_path = out_dir / f"{key}_post_{tag}.jpg"
        if not post_path.exists():
            compose_post(Image.open(clean_path), headline=clean_hl, brand=brand).save(
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
    ) -> CampaignAsset:
        """
        Run the full agency pipeline with Dual-Agent Collaborative refinement:
        Research -> Executive Brief -> Agent 1 Draft -> Agent 2 Critique & Polish -> FLUX Visual.
        """
        step = progress or (lambda msg: None)
        tone = tone or "confident, premium and benefit-driven"
        theme = theme or "clean premium commercial photography"
        brand = brand or "Lexnis Technologies"

        # 0. Intelligent Brand Detection & Executive Prompt Enhancement
        detected_brand, detected_prod = detect_brand_and_product(prompt, brand)
        if detected_brand and (brand.lower() == "lexnis technologies" or not brand):
            brand = detected_brand

        # Auto-enhance if the user prompt is conversational or instructional
        is_instructional = bool(re.search(r"\b(research|write|draft|create|generate|produce)\b.*?\b(post|hook|description|package|copy)\b", prompt, re.I))
        is_short = len(prompt.strip()) < 50
        enhanced_prompt = ""
        effective_prompt = prompt

        if is_instructional or is_short:
            step("Enhancing prompt with Executive Strategy Agent...")
            enhanced_data = self.enhance_user_prompt(prompt, brand)
            if enhanced_data.get("enhanced_prompt"):
                enhanced_prompt = enhanced_data["enhanced_prompt"]
                effective_prompt = enhanced_prompt
            if enhanced_data.get("detected_brand"):
                brand = enhanced_data["detected_brand"]

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
        if not highlights:
            highlights = [clean_social_text(h) for h in brief.get("key_benefits", []) if str(h).strip()][:5]
        if not highlights:
            highlights = [clean_social_text(h) for h in brief.get("proof_points", []) if str(h).strip()][:5]
        if not highlights:
            highlights = [
                "Full autonomous mobility guided by end-to-end neural vision AI",
                "20 kW resonant inductive wireless charging with zero cables",
                "Monolithic cold-rolled 300-series stainless steel durability"
            ] if brand.lower() == "tesla" else [
                "Dedicated neural architecture with real-time processing",
                "Breakthrough precision engineering and mission-critical reliability",
                "Engineered for pro workflows and enterprise leadership"
            ]
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
        post_path, clean_path, watermark_free = self.render_image(
            visual_prompt, seed, model=image_model, headline=headline, brand=brand, overlay=enhance_image
        )

        raw_response = json.dumps({"brief": brief, "post": post, "dialogue": dialogue, "critique": critique_notes}, indent=2, ensure_ascii=False)
        return CampaignAsset(
            prompt=prompt,
            hook=hook,
            caption=caption,
            highlights=highlights,
            hashtags=hashtags,
            visual_prompt=visual_prompt,
            image_url=post_path.as_uri(),
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
            image_path=str(post_path),
            clean_image_path=str(clean_path),
            watermark_free=watermark_free,
            text_engine=f"{self.text_engine}:{self.model}",
            agent_dialogue=dialogue,
            critique_notes=critique_notes,
            enhanced_prompt=enhanced_prompt,
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
        else:
            post_path, clean_path, wm_free = self.render_image(
                asset.visual_prompt, asset.seed, model=asset.image_model,
                headline=asset.image_headline, brand=asset.brand,
            )
            shutil.copyfile(post_path, image_file)
            asset.clean_image_path = str(clean_path)
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
    if not studio.pollinations_key:
        msg = "No POLLINATIONS_API_KEY in .env: images will be low-res and carry the Pollinations logo."
        console.print(f"[yellow]{msg}[/yellow]") if console else print(msg)

    kwargs = dict(
        prompt=prompt, brand=args.brand, tone=args.tone, theme=args.theme,
        use_search=not args.no_search, image_model=args.image_model, enhance_image=not args.no_overlay,
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
