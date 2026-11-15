"""First-class caption document model, subtitle parsing/formatting, and Pillow overlay rendering."""
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image, ImageDraw, ImageFont, features
from video_storage import uid


class StrictCaption(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class CaptionSegment(StrictCaption):
    id: str = Field(default_factory=uid)
    start: float = Field(0.0, ge=0.0)
    end: float = Field(0.0, ge=0.0)
    text: str = Field(..., min_length=1, max_length=1000)
    speaker: Optional[str] = None
    words: List[Dict[str, Any]] = Field(default_factory=list)


class CaptionStyle(StrictCaption):
    id: str
    name: str
    font_family: Literal['sans', 'arabic', 'serif'] = 'sans'
    font_size: int = Field(38, ge=18, le=96)
    font_weight: str = 'bold'
    fill: str = '#ffffff'
    stroke: Optional[str] = '#000000'
    stroke_width: int = 2
    background: Optional[str] = '#00000099'
    bg_radius: int = 8
    padding: int = 12
    alignment: Literal['left', 'center', 'right'] = 'center'
    position: Literal['top', 'middle', 'bottom'] = 'bottom'
    y_pct: float = Field(0.85, ge=0.1, le=0.95)
    max_chars_per_line: int = Field(36, ge=15, le=80)
    max_lines: int = Field(2, ge=1, le=4)


class CaptionTrack(StrictCaption):
    id: str = Field(default_factory=uid)
    language: str = 'en'
    source: Literal['manual', 'whisper', 'imported', 'derived'] = 'manual'
    style_id: str = 'brand-primary'
    segments: List[CaptionSegment] = Field(default_factory=list)
    burn_in: bool = True


DEFAULT_CAPTION_STYLES: Dict[str, CaptionStyle] = {
    'quick-social': CaptionStyle(id='quick-social',name='Readable social captions',font_size=64,
        fill='#ffffff',stroke='#000000',stroke_width=2,background='#07111cbb',y_pct=.82,max_chars_per_line=32,max_lines=2),
    'brand-primary': CaptionStyle(
        id='brand-primary', name='Brand Primary (High Legibility)',
        font_family='sans', font_size=38, fill='#ffffff', stroke='#041b15',
        stroke_width=2, background='#041b15cc', y_pct=0.84, max_chars_per_line=36
    ),
    'social-bold': CaptionStyle(
        id='social-bold', name='Social Bold (Punchy Outline)',
        font_family='sans', font_size=44, fill='#00ffa3', stroke='#000000',
        stroke_width=4, background=None, y_pct=0.80, max_chars_per_line=30
    ),
    'subtitle-minimal': CaptionStyle(
        id='subtitle-minimal', name='Subtitle Minimal',
        font_family='sans', font_size=32, fill='#ffffff', stroke='#000000',
        stroke_width=2, background=None, y_pct=0.88, max_chars_per_line=45
    ),
    'arabic-corporate': CaptionStyle(
        id='arabic-corporate', name='Arabic Corporate (RTL Enforced)',
        font_family='arabic', font_size=42, fill='#ffffff', stroke='#041b15',
        stroke_width=2, background='#041b15d9', y_pct=0.84, max_chars_per_line=32
    ),
}


def parse_srt(srt_text: str) -> List[CaptionSegment]:
    """Parse SubRip (.srt) string into structured CaptionSegments."""
    segments = []
    pattern = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n'
        r'([\s\S]*?)(?=\n\s*\d+\s*\n|\Z)',
        re.MULTILINE
    )

    def to_secs(t_str: str) -> float:
        parts = re.split(r'[:,.]', t_str)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000.0

    for match in pattern.finditer(srt_text.strip()):
        s_time = to_secs(match.group(2))
        e_time = to_secs(match.group(3))
        text = match.group(4).strip().replace('\r', '')
        if text:
            segments.append(CaptionSegment(
                id=uid(),
                start=round(s_time, 3),
                end=round(e_time, 3),
                text=text
            ))
    return segments


def to_srt(segments: List[CaptionSegment]) -> str:
    """Format CaptionSegments into standard SubRip (.srt) string."""
    def stamp(seconds: float) -> str:
        ms = round(seconds * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines = []
    for i, seg in enumerate(sorted(segments, key=lambda s: s.start), 1):
        lines.append(str(i))
        lines.append(f"{stamp(seg.start)} --> {stamp(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments: List[CaptionSegment]) -> str:
    """Format CaptionSegments into WebVTT string."""
    def stamp(seconds: float) -> str:
        ms = round(seconds * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02}.{ms:03}"

    lines = ["WEBVTT", ""]
    for i, seg in enumerate(sorted(segments, key=lambda s: s.start), 1):
        lines.append(str(i))
        lines.append(f"{stamp(seg.start)} --> {stamp(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def segment_transcript(cues: List[Dict[str, Any]], max_chars: int = 36, max_lines: int = 2) -> List[CaptionSegment]:
    """Break long speech cues into paced, readable 1-to-2 line caption segments."""
    results = []
    for cue in cues:
        raw_text = cue.get('text', '').strip()
        if not raw_text:
            continue
        c_start = float(cue.get('start', 0.0))
        c_end = float(cue.get('end', c_start + 2.0))
        dur = max(0.5, c_end - c_start)

        words = raw_text.split()
        if len(raw_text) <= max_chars * max_lines:
            results.append(CaptionSegment(
                id=uid(),
                start=round(c_start, 3),
                end=round(c_end, 3),
                text=raw_text
            ))
        else:
            # Chunk words across duration
            chunk_size = max(4, len(words) // 2)
            w_chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
            step = dur / len(w_chunks)
            for idx, chunk in enumerate(w_chunks):
                results.append(CaptionSegment(
                    id=uid(),
                    start=round(c_start + idx * step, 3),
                    end=round(c_start + (idx + 1) * step, 3),
                    text=" ".join(chunk)
                ))
    return results


def render_caption_image(
    text: str,
    width: int,
    height: int,
    style: CaptionStyle,
) -> Image.Image:
    """Render a styled caption into a transparent RGBA image positioned by style coordinates."""
    im = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    font_size = max(18, round(style.font_size * width / 1280))
    # Discover font
    font = None
    try:
        from visual_engine import get_font
        is_ar = any('\u0600' <= c <= '\u06ff' for c in text)
        family = "Cairo" if is_ar else "Inter"
        font = get_font(family, font_size, "bold")
    except Exception:
        font = ImageFont.load_default()

    # RTL preparation
    is_ar = any('\u0600' <= c <= '\u06ff' for c in text)
    rendered_text = text
    if is_ar:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            rendered_text = get_display(arabic_reshaper.reshape(text))
        except Exception:
            pass

    # Word wrapping
    words = rendered_text.split()
    lines = []
    curr = ""
    for w in words:
        candidate = f"{curr} {w}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) > (width * 0.8) and curr:
            lines.append(curr)
            curr = w
        else:
            curr = candidate
    if curr:
        lines.append(curr)

    lines = lines[:style.max_lines]
    full_str = "\n".join(lines)
    t_bbox = draw.multiline_textbbox((0, 0), full_str, font=font, align=style.alignment)
    t_w = t_bbox[2] - t_bbox[0]
    t_h = t_bbox[3] - t_bbox[1]

    # Coordinate calculation
    x_pos = (width - t_w) // 2 if style.alignment == 'center' else int(width * 0.1)
    y_pos = int(height * style.y_pct - t_h // 2)

    pad = style.padding
    if style.background:
        from creative.colors import parse_color
        bg_col = parse_color(style.background)
        draw.rounded_rectangle(
            [x_pos - pad, y_pos - pad, x_pos + t_w + pad, y_pos + t_h + pad],
            radius=style.bg_radius,
            fill=bg_col
        )

    # Outline / stroke
    if style.stroke and style.stroke_width > 0:
        from creative.colors import parse_color
        s_col = parse_color(style.stroke)
        draw.multiline_text(
            (x_pos, y_pos), full_str, font=font, fill=style.fill,
            align=style.alignment, stroke_width=style.stroke_width, stroke_fill=s_col
        )
    else:
        draw.multiline_text(
            (x_pos, y_pos), full_str, font=font, fill=style.fill, align=style.alignment
        )

    return im

