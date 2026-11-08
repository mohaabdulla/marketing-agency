import os
import sys
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import (
    render_depth_gradient,
    render_lexnis_logo,
    load_logo_pil,
    prepare_bidi_text,
    ensure_brand_fonts,
    FONTS_DIR
)

def balance_lines(text: str, max_chars_per_line: int = 24) -> list[str]:
    """
    Splits text into 1 or 2 visually balanced lines, guaranteeing NO single-word orphans.
    Minimizes the absolute difference in line length while respecting natural word boundaries.
    """
    if not text:
        return [""]
    text = text.strip()
    # If explicit newlines are present, check if balanced
    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(raw_lines) == 2:
        w1, w2 = raw_lines[0].split(), raw_lines[1].split()
        if len(w1) >= 2 and len(w2) >= 2:
            return raw_lines

    words = text.replace("\n", " ").split()
    if len(words) <= 3:
        if len(" ".join(words)) <= max_chars_per_line:
            return [" ".join(words)]
        if len(words) == 2:
            return [words[0], words[1]]
        elif len(words) == 3:
            return [" ".join(words[:2]), words[2]] if len(words[2]) > 6 else [" ".join(words)]

    best_split = None
    min_diff = float("inf")
    for i in range(1, len(words)):
        line1_words = words[:i]
        line2_words = words[i:]
        # Strictly forbid 1-word lines unless that single word is >= 9 chars
        if len(line2_words) == 1 and len(line2_words[0]) < 9:
            continue
        if len(line1_words) == 1 and len(line1_words[0]) < 9:
            continue
        l1 = " ".join(line1_words)
        l2 = " ".join(line2_words)
        diff = abs(len(l1) - len(l2))
        penalty = 0
        if len(l1) > max_chars_per_line:
            penalty += (len(l1) - max_chars_per_line) * 2
        if len(l2) > max_chars_per_line:
            penalty += (len(l2) - max_chars_per_line) * 2
        total_cost = diff + penalty
        if total_cost < min_diff:
            min_diff = total_cost
            best_split = (l1, l2)

    if best_split:
        return [best_split[0], best_split[1]]
    return [" ".join(words)]

def draw_optically_centered_pill(
    draw,
    pill_box,
    text: str,
    font,
    fill_color,
    outline_color=None,
    outline_width=1,
    radius=None,
    text_color=(255, 255, 255),
    is_ar: bool = False
):
    """
    Draws a pill and optically centers text to the exact pixel using ink bounding box.
    """
    x1, y1, x2, y2 = pill_box
    pw = x2 - x1
    ph = y2 - y1
    r = radius if radius is not None else ph // 2

    draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=fill_color, outline=outline_color, width=outline_width)

    disp = prepare_bidi_text(text) if is_ar else text
    bbox = draw.textbbox((0, 0), disp, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tx = x1 + (pw - tw) / 2.0 - bbox[0]
    ty = y1 + (ph - th) / 2.0 - bbox[1]

    draw.text((tx, ty), disp, font=font, fill=text_color)

def generate_thick_ribbon_chevron_field(width: int, height: int, opacity: float = 0.11, ribbon_thick: int = 34) -> Image.Image:
    """
    Renders official Brand Guidelines Core Chevron Field:
    Thick geometric polygon ribbons (thickness 34px, 52° angle, horizontal flat cuts).
    4 large bold chevrons across canvas width drifting diagonally.
    """
    pat = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pat)

    cw = int(round(width / 4.0)) # ~270px
    ch = int(round(cw * (284.0 / 336.0))) # ~228px
    pitch_x = int(round(cw * (261.0 / 336.0))) # ~210px
    step_y = int(round(ch * 0.72)) # ~164px
    step_x = int(round(cw * (-130.0 / 336.0)))
    dx = int(round((ch / 2.0) / math.tan(math.radians(52.0)))) # ~89px
    t = ribbon_thick # 34px

    c_start = np.array([2, 48, 36], dtype=np.float32)
    c_end = np.array([83, 184, 73], dtype=np.float32)

    y_min = -ch * 2
    y_max = height + ch * 2
    x_min = -cw * 3
    x_max = width + cw * 3

    row = 0
    y = y_min
    while y < y_max:
        row_offset = (row * step_x) % pitch_x
        x = x_min + row_offset
        cy = y + ch // 2
        top = cy - ch // 2
        bot = cy + ch // 2
        while x < x_max:
            diag = np.clip(((x / float(width)) + (1.0 - (y / float(height)))) * 0.5, 0.0, 1.0)
            col_rgb = (c_start * (1.0 - diag) + c_end * diag).clip(0, 255).astype(int)
            fill_rgba = (col_rgb[0], col_rgb[1], col_rgb[2], int(255 * opacity))

            # Authentic right-facing geometric ribbon polygon
            pts = [
                (x, top),
                (x + t, top),
                (x + dx + t, cy),
                (x + t, bot),
                (x, bot),
                (x + dx, cy)
            ]
            draw.polygon(pts, fill=fill_rgba)
            x += pitch_x
        y += step_y
        row += 1

    return pat

def generate_studio_emerald_spotlight(width: int, height: int, cx: int = 540, cy: int = 580, radius: int = 620, max_alpha: int = 36) -> Image.Image:
    """
    Renders soft radial emerald studio spotlight (#53B849 at 14% max opacity).
    """
    spot = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    y_idx, x_idx = np.ogrid[:height, :width]
    dist_sq = (x_idx - cx) ** 2 + (y_idx - cy) ** 2
    rad_sq = radius ** 2
    mask = dist_sq < rad_sq

    dist = np.sqrt(dist_sq)
    norm_dist = np.clip(dist / float(radius), 0.0, 1.0)
    falloff = np.clip((1.0 - norm_dist ** 1.4), 0.0, 1.0)
    alpha = (falloff * max_alpha).astype(np.uint8)

    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[:, :, 0] = 83   # R
    arr[:, :, 1] = 184  # G
    arr[:, :, 2] = 73   # B
    arr[:, :, 3] = alpha

    return Image.fromarray(arr, 'RGBA')

def render_agency_hiring_card(
    role_title: str = "Senior Machine Learning &\nVision Systems Engineer",
    team_location: str = "Manama, Bahrain  •  Full-Time  •  On-Site",
    hook_headline: str = None,
    subcopy: str = None,
    language: str = "en",
    brand_name: str = "Lexnis Technologies",
    brand_tag: str = None,
    logo_image = None,
    base_image = None,
    target_size = (1080, 1350)
) -> Image.Image:
    """
    Senior Agency Art Director Quality Recruitment Master (1080x1350, 4:5).
    """
    import cv2
    ensure_brand_fonts()
    W, H = target_size
    is_ar = (str(language).lower() in ["ar", "arabic"])

    # Official Lexnis Brand Color System
    dark_navy = (19, 23, 36)        # #131724
    deep_forest = (2, 48, 36)       # #023024
    tech_green = (83, 184, 73)      # #53B849
    lime_green = (188, 215, 85)     # #BCD755
    white = (255, 255, 255)
    slate_border = (203, 213, 225)  # #CBD5E1
    chip_bg = (241, 245, 249)       # #F1F5F9
    soft_white = (226, 232, 240)    # #E2E8F0

    # 1. Background: 135° Depth Gradient + Optional 75% Tinted Base Image
    bg_bgr = render_depth_gradient(W, H, "#131724", "#023024")
    bg_gradient = Image.fromarray(cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB))
    bg_rgba = bg_gradient.convert("RGBA")

    if base_image:
        try:
            if isinstance(base_image, (str, Path)) and Path(base_image).exists():
                b_im = Image.open(base_image).convert("RGBA")
            elif isinstance(base_image, Image.Image):
                b_im = base_image.convert("RGBA")
            else:
                b_im = None
            if b_im:
                b_fitted = ImageOps.fit(b_im, (W, H), method=Image.Resampling.LANCZOS)
                canvas = Image.blend(b_fitted, bg_rgba, alpha=0.75)
            else:
                canvas = bg_rgba
        except Exception:
            canvas = bg_rgba
    else:
        canvas = bg_rgba

    # Add Studio Emerald Spotlight (behind hero & card)
    spotlight = generate_studio_emerald_spotlight(W, H, cx=W//2, cy=580, radius=620, max_alpha=36)
    canvas.alpha_composite(spotlight)

    # Add Authentic Thick Ribbon Chevron Field (11% opacity)
    chev_field = generate_thick_ribbon_chevron_field(W, H, opacity=0.11, ribbon_thick=34)
    canvas.alpha_composite(chev_field)

    draw = ImageDraw.Draw(canvas)

    # 2. Header Bar (y = 72px)
    # 2a. Top-Left Logo (Rule 01: solid chevrons always point right >> in EN & AR)
    logo_pasted = False
    if logo_image:
        custom_logo = load_logo_pil(logo_image, is_dark_bg=True)
        if custom_logo:
            max_lh = 36
            max_lw = 240
            aspect = custom_logo.width / float(custom_logo.height)
            target_lh = min(max_lh, int(round(max_lw / aspect)))
            target_lw = int(round(target_lh * aspect))
            logo_resized = custom_logo.resize((target_lw, target_lh), Image.Resampling.LANCZOS)
            canvas.paste(logo_resized, (72, 72), logo_resized)
            logo_pasted = True

    if not logo_pasted:
        official_logo = render_lexnis_logo(height=32, is_dark_bg=True)
        canvas.paste(official_logo, (72, 72), official_logo)

    # 2b. Top-Right Hashtag
    tag_str = brand_tag or ("#وظائف_لكسنس" if is_ar else "#LexnisCareers")
    if is_ar and not ("لكسنس" in tag_str or "#وظائف" in tag_str or "فريق" in tag_str):
        tag_str = "#وظائف_لكسنس"
    
    f_tag_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-Medium.ttf")
    f_tag = ImageFont.truetype(str(f_tag_path), 22) if f_tag_path.exists() else ImageFont.load_default()
    disp_tag = prepare_bidi_text(tag_str) if is_ar else tag_str
    tag_bbox = draw.textbbox((0, 0), disp_tag, font=f_tag)
    tag_w = tag_bbox[2] - tag_bbox[0]
    draw.text((1008 - tag_w, 78), disp_tag, font=f_tag, fill=lime_green)

    # 3. Layer 1: Eyebrow Badge (The Category Signal)
    # EN: "WE'RE HIRING  •  MANAMA" / AR: "نحن نوظف  •  المنامة"
    city = "MANAMA" if not is_ar else "المنامة"
    if "bahrain" in (team_location or "").lower() or "manama" in (team_location or "").lower():
        city = "MANAMA" if not is_ar else "المنامة"
    eyebrow_text = f"نحن نوظف  •  {city}" if is_ar else f"WE'RE HIRING  •  {city}"

    f_eye_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-Bold.ttf")
    eye_size = 20 if is_ar else 19
    f_eye = ImageFont.truetype(str(f_eye_path), eye_size) if f_eye_path.exists() else ImageFont.load_default()

    disp_eye = prepare_bidi_text(eyebrow_text) if is_ar else eyebrow_text
    eye_bbox = draw.textbbox((0, 0), disp_eye, font=f_eye)
    ew = eye_bbox[2] - eye_bbox[0]
    eh = eye_bbox[3] - eye_bbox[1]

    eye_pad_x = 22
    eye_pad_y = 10
    eye_w = ew + eye_pad_x * 2
    eye_h = eh + eye_pad_y * 2
    eye_y = 195
    eye_x = (1008 - eye_w) if is_ar else 72

    # Draw semi-transparent pill overlay
    pill_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill_overlay)
    draw_optically_centered_pill(
        p_draw,
        (eye_x, eye_y, eye_x + eye_w, eye_y + eye_h),
        eyebrow_text,
        f_eye,
        fill_color=(83, 184, 73, 46), # 18% Tech Green fill
        outline_color=tech_green + (255,),
        outline_width=2,
        radius=eye_h // 2,
        text_color=lime_green,
        is_ar=is_ar
    )
    canvas.alpha_composite(pill_overlay)
    draw = ImageDraw.Draw(canvas)

    # 4. Layer 2: Hero Hook Headline (Inspiring Mission Hook, NEVER the job title!)
    # Clean role title from hook if duplicated
    def sanitize_hook(h, role):
        if not h:
            return ""
        if role and (role.lower() in h.lower() or h.lower() in role.lower()):
            return ""
        # Remove company name prefix
        h = h.replace("LEXNIS TECHNOLOGIES", "").replace("Lexnis Technologies", "").replace("Lexnis", "").strip()
        return h

    clean_hook = sanitize_hook(hook_headline, role_title)
    if not clean_hook:
        if is_ar:
            clean_hook = "اصنع مستقبل الذكاء\nالاصطناعي والرؤية"
        else:
            clean_hook = "ARCHITECT THE\nNEXT ERA OF AI."

    # Balance lines to ensure ZERO single-word orphans!
    hook_lines = balance_lines(clean_hook, max_chars_per_line=20)
    if len(hook_lines) == 1:
        # If single line, try splitting into 2 balanced lines
        hook_lines = balance_lines(clean_hook, max_chars_per_line=14)

    f_hook_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-Bold.ttf")
    hook_font_size = 72 if is_ar else 74
    f_hook = ImageFont.truetype(str(f_hook_path), hook_font_size) if f_hook_path.exists() else ImageFont.load_default()

    hook_y = eye_y + eye_h + 26
    line_spacing = int(round(hook_font_size * 1.10))

    for idx, line in enumerate(hook_lines[:2]):
        disp_line = prepare_bidi_text(line) if is_ar else line
        l_bbox = draw.textbbox((0, 0), disp_line, font=f_hook)
        lw = l_bbox[2] - l_bbox[0]
        lx = (1008 - lw) if is_ar else 72

        # Agency-grade color punch: Line 1 is Pure White (#FFFFFF), Line 2 is Lime Green (#BCD755)
        text_color = lime_green if idx == 1 else white
        draw.text((lx, hook_y + idx * line_spacing), disp_line, font=f_hook, fill=text_color)

    # 5. Layer 3: 2.5D Architectural Role Card (x = 72..1008, y = 660..980, height = 320px)
    card_x1 = 72
    card_y1 = 660
    card_w = 936
    card_h = 320
    card_x2 = card_x1 + card_w
    card_y2 = card_y1 + card_h

    # 5a. Drop Shadow & Ambient Depth Layer
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_layer)
    # Subtle back-card offset accent (x+10, y+10) in 22% Tech Green
    s_draw.rounded_rectangle(
        [card_x1 + 10, card_y1 + 10, card_x2 + 10, card_y2 + 10],
        radius=16,
        fill=(83, 184, 73, 56)
    )
    # Deep soft drop shadow (offset_y = +18px, blur = 24px, 45% black)
    s_draw.rounded_rectangle(
        [card_x1, card_y1 + 18, card_x2, card_y2 + 18],
        radius=16,
        fill=(0, 0, 0, 115)
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow_layer)
    draw = ImageDraw.Draw(canvas)

    # 5b. White Architectural Spec Card
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=16, fill=white)

    # 5c. Signature Lexnis Status Accent Bar (10px Tech Green + 3px Lime Green piping)
    bar_w = 10
    pipe_w = 3
    if is_ar:
        draw.rectangle([card_x2 - bar_w, card_y1, card_x2, card_y2], fill=tech_green)
        draw.rectangle([card_x2 - bar_w - pipe_w, card_y1, card_x2 - bar_w, card_y2], fill=lime_green)
        content_margin_x = 44
    else:
        draw.rectangle([card_x1, card_y1, card_x1 + bar_w, card_y2], fill=tech_green)
        draw.rectangle([card_x1 + bar_w, card_y1, card_x1 + bar_w + pipe_w, card_y2], fill=lime_green)
        content_margin_x = 44

    # 5d. Tier 1: Category Status Label ("OPEN POSITION  //  AI ENGINEERING")
    sec_label = "الوظيفة الشاغرة  //  هندسة الذكاء الاصطناعي" if is_ar else "OPEN POSITION  //  AI & VISION ENGINEERING"
    f_lbl_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-SemiBold.ttf")
    lbl_size = 19 if is_ar else 17
    f_lbl = ImageFont.truetype(str(f_lbl_path), lbl_size) if f_lbl_path.exists() else ImageFont.load_default()
    disp_lbl = prepare_bidi_text(sec_label) if is_ar else sec_label
    lbl_bbox = draw.textbbox((0, 0), disp_lbl, font=f_lbl)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    lbl_y = card_y1 + 26
    if is_ar:
        draw.text((card_x2 - content_margin_x - lbl_w, lbl_y), disp_lbl, font=f_lbl, fill=tech_green)
    else:
        draw.text((card_x1 + content_margin_x, lbl_y), disp_lbl, font=f_lbl, fill=tech_green)

    # 5e. Tier 2: Role Title (Placed ONLY inside the White Card!)
    import re
    clean_role = role_title or "Senior Machine Learning &\nVision Systems Engineer"
    if brand_name:
        clean_role = re.sub(rf"^\s*{re.escape(brand_name)}\s*", "", clean_role, flags=re.IGNORECASE).strip()
    clean_role = re.sub(r"^\s*lexnis(?:\s+technologies)?\s*", "", clean_role, flags=re.IGNORECASE).strip()
    clean_role = re.sub(r"^(?:a|an)\s+", "", clean_role, flags=re.IGNORECASE).strip()

    from visual_engine import ARABIC_TITLES_MAP
    if is_ar:
        rl_lower = clean_role.lower().strip()
        if rl_lower in ARABIC_TITLES_MAP:
            clean_role = ARABIC_TITLES_MAP[rl_lower]
        elif not re.search(r"[\u0600-\u06FF]", clean_role):
            clean_role = "مهندس أول تعلم الآلة وأنظمة الرؤية الحاسوبية"

    role_lines = balance_lines(clean_role, max_chars_per_line=28)[:2]

    f_role_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-Bold.ttf")
    role_font_size = 42 if is_ar else 40
    f_role = ImageFont.truetype(str(f_role_path), role_font_size) if f_role_path.exists() else ImageFont.load_default()

    role_y = card_y1 + 64
    role_step = int(round(role_font_size * 1.22))
    for rline in role_lines:
        disp_rline = prepare_bidi_text(rline) if is_ar else rline
        rb_bbox = draw.textbbox((0, 0), disp_rline, font=f_role)
        rw = rb_bbox[2] - rb_bbox[0]
        rx = (card_x2 - content_margin_x - rw) if is_ar else (card_x1 + content_margin_x)
        draw.text((rx, role_y), disp_rline, font=f_role, fill=dark_navy)
        role_y += role_step

    # 5f. Tier 3: Hairline Divider Line
    divider_y = card_y1 + 218
    div_x1 = card_x1 + 36
    div_x2 = card_x2 - 36
    draw.line([(div_x1, divider_y), (div_x2, divider_y)], fill=slate_border, width=1)

    # 5g. Tier 4: Bottom Structured Metadata Chips Row (No dead space!)
    # 3 Soft-tinted metadata pills: [ Location ] [ Type ] [ Lab/Team ]
    chip_h = 44
    chip_y = card_y1 + 242
    total_avail_w = card_w - 72 # 864px
    chip_w = (total_avail_w - 2 * 16) // 3 # 277px each

    if is_ar:
        chips_data = [
            ("مختبر الذكاء الاصطناعي", "lab"),
            ("دوام كامل • هجين", "type"),
            ("المنامة، البحرين", "loc")
        ]
    else:
        chips_data = [
            ("Manama, Bahrain", "loc"),
            ("Full-Time / Hybrid", "type"),
            ("Core AI Lab", "lab")
        ]

    f_chip_path = (FONTS_DIR / "Cairo-SemiBold.ttf") if is_ar else (FONTS_DIR / "Poppins-Medium.ttf")
    f_chip = ImageFont.truetype(str(f_chip_path), 18) if f_chip_path.exists() else ImageFont.load_default()

    for c_idx, (c_text, c_type) in enumerate(chips_data):
        cx1 = card_x1 + 36 + c_idx * (chip_w + 16)
        cx2 = cx1 + chip_w
        cy1 = chip_y
        cy2 = cy1 + chip_h

        # Draw chip rounded rect
        draw.rounded_rectangle([cx1, cy1, cx2, cy2], radius=8, fill=chip_bg, outline=slate_border, width=1)

        disp_ctext = prepare_bidi_text(c_text) if is_ar else c_text
        c_bbox = draw.textbbox((0, 0), disp_ctext, font=f_chip)
        cw = c_bbox[2] - c_bbox[0]
        ch = c_bbox[3] - c_bbox[1]

        bullet_r = 4
        bullet_gap = 10
        content_w = bullet_r * 2 + bullet_gap + cw

        if is_ar:
            # Bullet dot on the right side of the text in RTL
            start_x = cx1 + (chip_w - content_w) / 2.0
            # Text on left
            tx = start_x - c_bbox[0]
            ty = cy1 + (chip_h - ch) / 2.0 - c_bbox[1]
            draw.text((tx, ty), disp_ctext, font=f_chip, fill=dark_navy)
            # Dot on right
            bx = start_x + cw + bullet_gap + bullet_r
            by = cy1 + chip_h / 2.0
            draw.ellipse([bx - bullet_r, by - bullet_r, bx + bullet_r, by + bullet_r], fill=tech_green)
        else:
            # Bullet dot on the left side of the text in LTR
            start_x = cx1 + (chip_w - content_w) / 2.0
            # Dot on left
            bx = start_x + bullet_r
            by = cy1 + chip_h / 2.0
            draw.ellipse([bx - bullet_r, by - bullet_r, bx + bullet_r, by + bullet_r], fill=tech_green)
            # Text on right
            tx = start_x + bullet_r * 2 + bullet_gap - c_bbox[0]
            ty = cy1 + (chip_h - ch) / 2.0 - c_bbox[1]
            draw.text((tx, ty), disp_ctext, font=f_chip, fill=dark_navy)

    # 6. Layer 4: Engineering Value Proposition Subcopy (y = 1030)
    sub_str = subcopy
    if not sub_str:
        if is_ar:
            sub_str = "انتقل بنماذجك من التجربة إلى حافة الإنجاز الفوري.\nابنِ أنظمة ذكية وتأسيسية من قلب المنامة."
        else:
            sub_str = "Stop maintaining someone else's API. Build foundational\nvision systems from scratch in Manama."

    sub_lines = balance_lines(sub_str, max_chars_per_line=50)[:2]
    f_sub_path = (FONTS_DIR / "Tajawal-Medium.ttf") if is_ar else (FONTS_DIR / "Poppins-Medium.ttf")
    f_sub = ImageFont.truetype(str(f_sub_path), 23) if f_sub_path.exists() else ImageFont.load_default()

    sub_y = 1035
    for sline in sub_lines:
        disp_sline = prepare_bidi_text(sline) if is_ar else sline
        sb_bbox = draw.textbbox((0, 0), disp_sline, font=f_sub)
        sw = sb_bbox[2] - sb_bbox[0]
        sx = (1008 - sw) if is_ar else 72
        draw.text((sx, sub_y), disp_sline, font=f_sub, fill=soft_white)
        sub_y += 34

    # 7. Layer 5: High-Contrast Executive CTA Button (y = 1145, height = 68px, Lime Green #BCD755)
    btn_h = 68
    btn_w = 540
    btn_y = 1145
    btn_x = (1008 - btn_w) if is_ar else 72

    # Draw Lime Green CTA Pill (Contrast > 11:1 against Dark Navy text!)
    draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=btn_h // 2, fill=lime_green)

    f_btn_bold_path = (FONTS_DIR / "Cairo-Bold.ttf") if is_ar else (FONTS_DIR / "Poppins-Bold.ttf")
    f_btn_bold = ImageFont.truetype(str(f_btn_bold_path), 22) if f_btn_bold_path.exists() else ImageFont.load_default()

    f_btn_med_path = (FONTS_DIR / "Cairo-SemiBold.ttf") if is_ar else (FONTS_DIR / "Poppins-Medium.ttf")
    f_btn_med = ImageFont.truetype(str(f_btn_med_path), 21) if f_btn_med_path.exists() else ImageFont.load_default()

    # Structure inside button: [ APPLY NOW ]  (>)  [ lexnis.com/careers ]
    left_lbl = "قدّم الآن" if is_ar else "APPLY NOW"
    right_url = "lexnis.com/careers"

    disp_llbl = prepare_bidi_text(left_lbl) if is_ar else left_lbl
    disp_rurl = right_url

    l_bbox = draw.textbbox((0, 0), disp_llbl, font=f_btn_bold)
    lw = l_bbox[2] - l_bbox[0]
    lh = l_bbox[3] - l_bbox[1]

    r_bbox = draw.textbbox((0, 0), disp_rurl, font=f_btn_med)
    rw = r_bbox[2] - r_bbox[0]
    rh = r_bbox[3] - r_bbox[1]

    badge_d = 34
    spacing = 18
    total_inner_w = lw + spacing + badge_d + spacing + rw
    inner_start_x = btn_x + (btn_w - total_inner_w) / 2.0

    if is_ar:
        # Right to left: [قدّم الآن] (badge) [lexnis.com/careers]
        # Text 1 on right
        t1_x = inner_start_x + rw + spacing + badge_d + spacing - l_bbox[0]
        t1_y = btn_y + (btn_h - lh) / 2.0 - l_bbox[1]
        draw.text((t1_x, t1_y), disp_llbl, font=f_btn_bold, fill=dark_navy)

        # Dark Navy circular badge in middle
        bx = inner_start_x + rw + spacing
        by = btn_y + (btn_h - badge_d) / 2.0
        draw.ellipse([bx, by, bx + badge_d, by + badge_d], fill=dark_navy)
        # Chevron symbol pointing in reading direction
        f_chev = ImageFont.truetype(str(FONTS_DIR / "Cairo-Bold.ttf"), 18)
        c_char = prepare_bidi_text("«")
        cb = draw.textbbox((0, 0), c_char, font=f_chev)
        draw.text((bx + (badge_d - (cb[2]-cb[0]))/2.0 - cb[0], by + (badge_d - (cb[3]-cb[1]))/2.0 - cb[1]), c_char, font=f_chev, fill=lime_green)

        # URL on left
        t2_x = inner_start_x - r_bbox[0]
        t2_y = btn_y + (btn_h - rh) / 2.0 - r_bbox[1]
        draw.text((t2_x, t2_y), disp_rurl, font=f_btn_med, fill=dark_navy)

    else:
        # Left to right: [APPLY NOW] (badge) [lexnis.com/careers]
        t1_x = inner_start_x - l_bbox[0]
        t1_y = btn_y + (btn_h - lh) / 2.0 - l_bbox[1]
        draw.text((t1_x, t1_y), disp_llbl, font=f_btn_bold, fill=dark_navy)

        bx = inner_start_x + lw + spacing
        by = btn_y + (btn_h - badge_d) / 2.0
        draw.ellipse([bx, by, bx + badge_d, by + badge_d], fill=dark_navy)
        f_chev = ImageFont.truetype(str(FONTS_DIR / "Poppins-Bold.ttf"), 16)
        c_char = ">"
        cb = draw.textbbox((0, 0), c_char, font=f_chev)
        draw.text((bx + (badge_d - (cb[2]-cb[0]))/2.0 - cb[0] + 1, by + (badge_d - (cb[3]-cb[1]))/2.0 - cb[1]), c_char, font=f_chev, fill=lime_green)

        t2_x = bx + badge_d + spacing - r_bbox[0]
        t2_y = btn_y + (btn_h - rh) / 2.0 - r_bbox[1]
        draw.text((t2_x, t2_y), disp_rurl, font=f_btn_med, fill=dark_navy)

    return canvas.convert("RGB")

if __name__ == "__main__":
    out_dir = BASE_DIR / "output" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Generating Agency Art Director EN Master...")
    en_img = render_agency_hiring_card(
        role_title="Senior Machine Learning &\nVision Systems Engineer",
        team_location="Manama, Bahrain  •  Full-Time  •  On-Site",
        hook_headline="ARCHITECT THE\nNEXT ERA OF AI.",
        subcopy="Stop maintaining someone else's API. Build foundational\nvision models from scratch in Manama.",
        language="en"
    )
    en_path = out_dir / "agency_hiring_en_test.jpg"
    en_img.save(en_path, quality=95)
    print(f"Saved EN to {en_path}")

    print("Generating Agency Art Director AR Master...")
    ar_img = render_agency_hiring_card(
        role_title="مهندس أول تعلم الآلة\nوأنظمة الرؤية الحاسوبية",
        team_location="المنامة، البحرين  •  دوام كامل  •  حضوري",
        hook_headline="اصنع مستقبل الذكاء\nالاصطناعي والرؤية",
        subcopy="انتقل بنماذجك من التجربة إلى حافة الإنجاز الفوري.\nابنِ أنظمة ذكية وتأسيسية من قلب المنامة.",
        language="ar"
    )
    ar_path = out_dir / "agency_hiring_ar_test.jpg"
    ar_img.save(ar_path, quality=95)
    print(f"Saved AR to {ar_path}")

