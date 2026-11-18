"""Pixel-measured type, logical phrase wrapping, tracking, line spacing and complete text."""
import re
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, features


@lru_cache(maxsize=96)
def font_for(name, family, size, weight, arabic):
    from video.fonts import path, choose
    selected = path(name, weight)
    if not selected:
        selected = path(choose([family])[0], weight)
    if selected:
        return ImageFont.truetype(selected, size)
    from image.visual_engine import get_font
    return get_font('Cairo' if arabic else 'Inter', size, weight)


def compose(text, width, height, style):
    arabic = bool(re.search(r'[\u0600-\u06ff]', text))
    direction = {'direction': 'rtl', 'language': 'ar'} if arabic and features.check_feature('raqm') else {}
    def shape(line):
        if not arabic or direction:
            return line
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(line))
        except ImportError as exc:
            raise ValueError('Arabic captions require RAQM or arabic-reshaper and python-bidi') from exc
    scale=width/style.reference_width if style.reference_width else 1.
    original_size=round(style.font_size_px*scale if style.font_size_px else max(style.min_font_px, style.font_size * width / 1280))
    size=min(160,original_size)
    tracking = 0. if arabic else style.tracking
    draw = ImageDraw.Draw(Image.new('L', (1, 1)))
    # An authored line break (speaker name / role) is a hard break, never re-flowed.
    paragraphs = [p.split() for p in text.split('\n') if p.strip()]
    words = text.split()
    max_width = width * style.max_width_pct
    minimum = max(9,round(min(size, style.min_font_px*scale)))
    while True:
        font = font_for(style.font_name, style.font_family, size, style.font_weight, arabic)
        def measure(line):
            rendered = shape(line)
            if tracking:
                return sum(font.getlength(c) for c in rendered) + tracking * max(0, len(rendered)-1)
            return draw.textlength(rendered, font=font, **direction)
        lines = []
        for paragraph in paragraphs:
            current = ''
            for word in paragraph:
                candidate = (current + ' ' + word).strip()
                if current and measure(candidate) > max_width:
                    lines.append(current); current = word
                else:
                    current = candidate
            if current: lines.append(current)
        # Balance two lines at a linguistic boundary, without reversing RTL paragraphs.
        if len(paragraphs) == 1 and len(lines) == 2 and len(words) > 2:
            candidates = []
            for split in range(1, len(words)):
                a,b = ' '.join(words[:split]), ' '.join(words[split:])
                aw,bw=measure(a),measure(b)
                if max(aw,bw) <= max_width:
                    orphan = 100 if split == 1 or split == len(words)-1 else 0
                    weak = 50 if words[split-1].casefold() in {'a','an','the','to','of','and','or','with','in'} else 0
                    punctuation = -20 if re.search(r'[,;:،.!?؟]$',words[split-1]) else 0
                    candidates.append((abs(aw-bw)+orphan+weak+punctuation,[a,b]))
            if candidates: lines=min(candidates,key=lambda x:x[0])[1]
        if len(lines) <= style.max_lines and all(measure(line) <= max_width for line in lines) or size <= minimum:
            break
        size -= 1
    rendered = [shape(line) for line in lines]
    line_height = max(size, round(size * style.line_height))
    widths = [measure(line) for line in lines]
    text_width = max(widths or [0.])
    glyph_height = max((draw.textbbox((0,0),line,font=font,anchor='lt',**direction)[3] for line in rendered), default=size)
    text_height = (len(lines)-1)*line_height+glyph_height
    cx,cy = width*style.x_center_pct,height*style.y_pct
    x0,y0 = round(cx-text_width/2),round(cy-text_height/2)
    pad = style.padding + style.stroke_width
    info = dict(box=[x0-pad,y0-pad,round(cx+text_width/2)+pad,y0+text_height+pad],
                text_box=[x0,y0,round(cx+text_width/2),y0+text_height],font_size=size,lines=len(lines),
                wrapped_lines=len(lines),logical_lines=lines,truncated=False,
                exceeds_lines=len(lines)>style.max_lines,oversized_word=any(v>max_width for v in widths),
                font_reduced=size < original_size,
                tracking_applied=tracking,line_height_px=line_height)
    return info,rendered,widths,font,direction


def render(text,width,height,style):
    info,lines,widths,font,direction=compose(text,width,height,style)
    image=Image.new('RGBA',(width,height))
    draw=ImageDraw.Draw(image)
    from creative.colors import parse_color
    if style.background:
        draw.rounded_rectangle(info['box'],radius=style.bg_radius,fill=parse_color(style.background))
    y=info['text_box'][1]
    for line,line_width in zip(lines,widths):
        x=round(width*style.x_center_pct-line_width/2)
        params=dict(font=font,fill=style.fill,anchor='lt',stroke_width=style.stroke_width if style.stroke else 0,
                    stroke_fill=parse_color(style.stroke) if style.stroke else None,**direction)
        if info['tracking_applied']:
            # Letter-spaced text is drawn glyph by glyph on one shared baseline. Anchoring each
            # glyph by its own top ('lt') lifts short letters and makes the line wavy.
            ascent=-draw.textbbox((0,0),line,font=font,anchor='ls')[1]
            spaced=dict(params,anchor='ls')
            for char in line:
                draw.text((x,y+ascent),char,**spaced)
                x+=font.getlength(char)+info['tracking_applied']
        else:
            draw.text((x,y),line,**params)
        y+=info['line_height_px']
    info['outside_frame']=info['box'][0]<0 or info['box'][1]<0 or info['box'][2]>width or info['box'][3]>height
    image.info['caption_layout']=info
    return image
