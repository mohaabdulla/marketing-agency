"""First-class caption document model, subtitle parsing/formatting, and Pillow overlay rendering."""
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image
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
    font_name: str = Field('', max_length=80)
    font_size_px: float | None = Field(None, ge=12, le=160)
    reference_width: int | None = Field(None,ge=128,le=1920)
    min_font_px: int = Field(18, ge=12, le=48)
    tracking: float = Field(0, ge=-1, le=8)
    line_height: float = Field(1.22, ge=1, le=2)
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
    # Horizontal placement: widest text line and block centre, as fractions of the frame width.
    max_width_pct: float = Field(0.8, ge=0.3, le=0.95)
    x_center_pct: float = Field(0.5, ge=0.2, le=0.8)


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
    'lower-third': CaptionStyle(id='lower-third', name='Speaker lower third', font_size=40, fill='#ffffff', stroke=None, stroke_width=0,
        background='#07111ce0', padding=14, y_pct=.6, max_chars_per_line=40, max_lines=2),
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


TIMING = re.compile(r'^\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$')


def parse_srt(srt_text: str) -> List[CaptionSegment]:
    """Parse SubRip (.srt) into CaptionSegments, one blank-line separated block at a time.

    A block is an optional counter, a timing line and the text. Text lines that are only digits
    stay text, a UTF-8 byte-order mark and CRLF line ends are accepted, and anything after the end
    time on the timing line (legacy X1/Y1 position coordinates) is ignored.
    """
    text = srt_text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    segments = []
    for block in re.split(r'\n[ \t]*\n', text.strip()):
        lines = block.split('\n')
        index = next((i for i, line in enumerate(lines[:2]) if TIMING.match(line)), None)
        if index is None:
            continue
        g = TIMING.match(lines[index]).groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
        stop = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
        body = '\n'.join(line.rstrip() for line in lines[index + 1:]).strip()
        if body and stop > start:
            segments.append(CaptionSegment(id=uid(), start=round(start, 3), end=round(stop, 3), text=body))
    return segments


def _clock(seconds: float, separator: str) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{separator}{ms:03}"


def _cue_text(text: str) -> str:
    """Cue text without blank lines (a blank line ends a cue) and without the timing arrow."""
    lines = [line.strip() for line in text.replace('\r', '').split('\n')]
    return '\n'.join(line for line in lines if line).replace('-->', '->')


def to_srt(segments: List[CaptionSegment]) -> str:
    """Format CaptionSegments into standard SubRip (.srt): comma milliseconds, CRLF-safe blocks."""
    lines = []
    for i, seg in enumerate(sorted(segments, key=lambda s: s.start), 1):
        lines += [str(i), f"{_clock(seg.start, ',')} --> {_clock(seg.end, ',')}", _cue_text(seg.text), ""]
    return "\n".join(lines)


def to_vtt(segments: List[CaptionSegment]) -> str:
    """Format CaptionSegments into WebVTT (W3C): '.' milliseconds and escaped cue text.

    WebVTT cue text is markup, so &, < and > are written as character references; otherwise
    "R&D" or "<10 ms" is read as an entity or a tag by players.
    """
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(sorted(segments, key=lambda s: s.start), 1):
        body = _cue_text(seg.text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        lines += [str(i), f"{_clock(seg.start, '.')} --> {_clock(seg.end, '.')}", body, ""]
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


def track_style(track) -> CaptionStyle:
    """Style for a caption track, with the track's own vertical position when it sets one
    (used to keep captions above a platform's interface area)."""
    style = DEFAULT_CAPTION_STYLES.get(track.get('style_id', 'brand-primary'), DEFAULT_CAPTION_STYLES['brand-primary'])
    if track.get('brand_style'):
        style = CaptionStyle.model_validate(track['brand_style'])
    update = {}
    if track.get('y_pct') is not None:
        update['y_pct'] = min(.95, max(.1, float(track['y_pct'])))
    if track.get('max_width_pct') is not None:
        update['max_width_pct'] = min(.95, max(.3, float(track['max_width_pct'])))
    if track.get('x_center_pct') is not None:
        update['x_center_pct'] = min(.8, max(.2, float(track['x_center_pct'])))
    return style.model_copy(update=update) if update else style


def cue_style(track, segment):
    base = track_style(track)
    override = dict(segment.get('layout_style') or {})
    origin=segment.get('layout_track_origin') or {}
    for key in ('y_pct','x_center_pct','max_width_pct'):
        if key in origin and track.get(key) is not None and track[key]!=origin[key] and key in override:
            override[key]=override[key]+track[key]-origin[key]
    return CaptionStyle.model_validate(dict(base.model_dump(), **override))


def brand_caption_style(rules, language='en', base='quick-social'):
    """Snapshot reviewed rules into the track so later library changes cannot alter a render."""
    from video_fonts import choose
    font, warnings = choose(rules.font_preferences)
    style = DEFAULT_CAPTION_STYLES[base].model_copy(deep=True)
    style.font_name = font
    style.font_family = 'arabic' if language.startswith('ar') else 'sans'
    if rules.caption_color:
        style.fill = rules.caption_color
    if rules.caption_size:
        style.font_size = max(18, min(96, rules.caption_size))
        if style.font_size != rules.caption_size:
            warnings.append('Caption size limited to the supported 18–96 range; inspect readability.')
    return style.model_dump(), warnings


def render_caption_image(text: str, width: int, height: int, style: CaptionStyle) -> Image.Image:
    """Central complete-text renderer; every word is retained and overflow is explicit."""
    from video_typography import render
    return render(text, width, height, style)


def caption_qa(segments, style: CaptionStyle, width: int, height: int, max_cps: float = 20.0, min_duration: float = 0.7,
               max_duration: float = 7.0, low_confidence: float = 0.6, track=None):
    """Readability review of caption cues. Returns (issues, stats); issues are review flags.

    Reading speed (characters per second), minimum/maximum display time and line limits are
    common subtitling guidelines exposed as parameters, not a formal standard.
    """
    issues, speeds = [], []
    ordered = sorted(segments, key=lambda s: s['start'])
    for index, seg in enumerate(ordered):
        text = ' '.join(str(seg.get('text', '')).split())
        duration = seg['end'] - seg['start']
        where = f'cue {index + 1} ({seg["start"]:.2f}s)'
        if not text:
            issues.append(dict(code='empty', severity='FAIL', message=where + ' has no text'))
            continue
        cps = len(text) / duration if duration > 0 else float('inf')
        speeds.append(cps)
        if duration < min_duration:
            issues.append(dict(code='too_short', severity='WARNING', message=f'{where} is shown for {duration:.2f}s (under {min_duration}s)'))
        if duration > max_duration:
            issues.append(dict(code='too_long', severity='WARNING', message=f'{where} stays for {duration:.1f}s'))
        if cps > max_cps:
            issues.append(dict(code='reading_speed', severity='WARNING', message=f'{where} needs {cps:.0f} characters/second (guideline {max_cps:.0f})'))
        if index and seg['start'] < ordered[index - 1]['end'] - 0.01:
            issues.append(dict(code='overlap', severity='FAIL', message=where + ' overlaps the previous cue'))
        current_style=cue_style(track,seg) if track else style
        layout = render_caption_image(text, width, height, current_style).info['caption_layout']
        if layout['truncated'] or layout.get('exceeds_lines') or layout.get('oversized_word'):
            issues.append(dict(code='truncated', severity='FAIL', message=f'{where} needs {layout["wrapped_lines"]} lines or an overwide word; reflow/retime is required. Text was retained rather than silently removed.'))
        box = layout['box']
        if box[0] < width * 0.04 or box[2] > width * 0.96 or box[1] < height * 0.05 or box[3] > height * 0.95:
            issues.append(dict(code='safe_zone', severity='WARNING', message=where + ' sits outside the 4-5% edge safe margin'))
        for word in seg.get('words', []) or []:
            if word.get('probability', 1) < low_confidence:
                issues.append(dict(code='low_confidence', severity='WARNING', message=f'{where}: check the recognised word "{str(word.get("word", "")).strip()}"'))
    stats = dict(cues=len(ordered), max_characters_per_second=round(max(speeds), 1) if speeds else None,
                 mean_characters_per_second=round(sum(speeds) / len(speeds), 1) if speeds else None)
    return issues, stats

