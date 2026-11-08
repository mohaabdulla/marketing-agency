import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import (
    render_depth_gradient,
    generate_chevron_field,
    render_lexnis_logo,
    load_logo_pil,
    prepare_bidi_text,
    ensure_brand_fonts,
    FONTS_DIR
)

def build_hiring_card_prototype(
    role_title: str = "Senior Machine Learning &\nVision Systems Engineer",
    team_location: str = "Manama, Bahrain  •  Full-Time  •  On-Site",
    hook_headline: str = "BUILD THE FUTURE OF AI",
    subcopy: str = "Stop maintaining someone else's API. Build foundational vision systems from scratch in Manama.",
    language: str = "en",
    brand_name: str = "Lexnis Technologies",
    brand_tag: str = "#LexnisCareers",
    logo_image = None,
    base_image = None,
    target_size = (1080, 1350)
) -> Image.Image:
    """
    Renders official Lexnis Brand System 1080x1350 (4:5) high-impact recruitment poster.
    """
    ensure_brand_fonts()
    W, H = target_size
    is_ar = (str(language).lower() in ["ar", "arabic"])

    # Colors per Brand Guidelines
    dark_navy = (19, 23, 36)      # #131724
    deep_forest = (2, 48, 36)     # #023024
    tech_green = (83, 184, 73)    # #53B849
    lime_green = (188, 215, 85)   # #BCD755
    white = (255, 255, 255)
    light_slate = (200, 215, 230)

    # 1. Canvas & Background (135° Depth Gradient + 75% blend if base image + Core Chevron Field)
    import cv2
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

    # Overlay Core Chevron Field at 12% opacity
    chev_field = generate_chevron_field(W, H, opacity=0.12, stroke_color=tech_green)
    canvas.alpha_composite(chev_field)

    draw = ImageDraw.Draw(canvas)

    # 2. Header Bar (y = 72px)
    # 2a. Top-Left Logo (Official Lexnis solid dual chevrons or custom logo)
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
    if is_ar:
        if not ("#" in tag_str or "لكسنس" in tag_str):
            tag_str = "#وظائف_لكسنس"
        f_tag_path = FONTS_DIR / "Cairo-Bold.ttf"
    else:
        f_tag_path = FONTS_DIR / "Poppins-Medium.ttf"
    f_tag = ImageFont.truetype(str(f_tag_path), 22) if f_tag_path.exists() else ImageFont.load_default()
    
    display_tag = prepare_bidi_text(tag_str) if is_ar else tag_str
    tag_bbox = draw.textbbox((0, 0), display_tag, font=f_tag)
    tag_w = tag_bbox[2] - tag_bbox[0]
    draw.text((1008 - tag_w, 78), display_tag, font=f_tag, fill=lime_green)

    # 3. Hero Recruitment Badge & Headline (Upper Zone)
    # 3a. Pill Badge
    pill_text = "نحن نوظف | انضم إلى فريقنا" if is_ar else "WE ARE HIRING"
    if is_ar:
        f_pill_path = FONTS_DIR / "Cairo-Bold.ttf"
        pill_font_size = 24
    else:
        f_pill_path = FONTS_DIR / "Poppins-Bold.ttf"
        pill_font_size = 22
    f_pill = ImageFont.truetype(str(f_pill_path), pill_font_size) if f_pill_path.exists() else ImageFont.load_default()

    display_pill = prepare_bidi_text(pill_text) if is_ar else pill_text
    p_bbox = draw.textbbox((0, 0), display_pill, font=f_pill)
    pw = p_bbox[2] - p_bbox[0]
    ph = p_bbox[3] - p_bbox[1]

    pill_pad_x = 24
    pill_pad_y = 10
    pill_w = pw + pill_pad_x * 2
    pill_h = ph + pill_pad_y * 2
    pill_y = 200

    if is_ar:
        pill_x = 1008 - pill_w
    else:
        pill_x = 72

    # Draw semi-transparent pill overlay
    pill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill_layer)
    # 20% Tech Green fill: (83, 184, 73, 51)
    pill_draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=pill_h // 2,
        fill=(83, 184, 73, 51),
        outline=tech_green + (255,),
        width=2
    )
    canvas.alpha_composite(pill_layer)
    draw = ImageDraw.Draw(canvas)

    # Text inside pill
    text_px = pill_x + pill_pad_x
    text_py = pill_y + pill_pad_y - 2
    draw.text((text_px, text_py), display_pill, font=f_pill, fill=lime_green)

    # 3b. Hero Hook Headline
    hook_str = hook_headline or ("ريادة الرؤية الحاسوبية" if is_ar else "BUILD THE FUTURE OF AI")
    # Sanitize: NEVER prepend company name
    hook_str = re_clean_hook(hook_str, brand_name)

    if is_ar:
        f_hook_path = FONTS_DIR / "Cairo-Bold.ttf"
        hook_size = 68
    else:
        f_hook_path = FONTS_DIR / "Poppins-Bold.ttf"
        hook_size = 72

    f_hook = ImageFont.truetype(str(f_hook_path), hook_size) if f_hook_path.exists() else ImageFont.load_default()
    
    # Wrap headline if longer than 936px
    hook_lines = wrap_text_to_width(draw, hook_str, f_hook, max_w=936, is_ar=is_ar)
    hook_y = pill_y + pill_h + 28
    for line in hook_lines:
        line_disp = prepare_bidi_text(line) if is_ar else line
        l_bbox = draw.textbbox((0, 0), line_disp, font=f_hook)
        lw = l_bbox[2] - l_bbox[0]
        lh = l_bbox[3] - l_bbox[1]
        lx = (1008 - lw) if is_ar else 72
        draw.text((lx, hook_y), line_disp, font=f_hook, fill=white)
        hook_y += int(round(hook_size * 1.18))

    # 4. White Structured Role Card / Status Tile (x = 72..1008, y = 750..1030)
    card_x1 = 72
    card_y1 = 750
    card_w = 936
    card_h = 280
    card_x2 = card_x1 + card_w
    card_y2 = card_y1 + card_h

    # Draw pure white rounded card
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=16, fill=white)

    # 6px solid Tech Green accent bar
    bar_w = 6
    if is_ar:
        draw.rectangle([card_x2 - bar_w, card_y1, card_x2, card_y2], fill=tech_green)
        content_margin_x = 42
    else:
        draw.rectangle([card_x1, card_y1, card_x1 + bar_w, card_y2], fill=tech_green)
        content_margin_x = 42

    # Card Content:
    # 4a. Section Label ("OPEN POSITION" / "الوظيفة الشاغرة")
    sec_label = "الوظيفة الشاغرة" if is_ar else "OPEN POSITION"
    if is_ar:
        f_lbl_path = FONTS_DIR / "Cairo-Bold.ttf"
        lbl_size = 20
    else:
        f_lbl_path = FONTS_DIR / "Poppins-SemiBold.ttf"
        lbl_size = 18
    f_lbl = ImageFont.truetype(str(f_lbl_path), lbl_size) if f_lbl_path.exists() else ImageFont.load_default()
    disp_lbl = prepare_bidi_text(sec_label) if is_ar else sec_label
    lbl_bbox = draw.textbbox((0, 0), disp_lbl, font=f_lbl)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    lbl_y = card_y1 + 32
    if is_ar:
        draw.text((card_x2 - content_margin_x - lbl_w, lbl_y), disp_lbl, font=f_lbl, fill=tech_green)
    else:
        draw.text((card_x1 + content_margin_x, lbl_y), disp_lbl, font=f_lbl, fill=tech_green)

    # 4b. Role Title (Cleanly wrapped to max 2 lines, Dark Navy #131724)
    clean_role = re_clean_role(role_title, brand_name)
    if is_ar:
        f_role_path = FONTS_DIR / "Cairo-Bold.ttf"
        role_font_size = 42
    else:
        f_role_path = FONTS_DIR / "Poppins-Bold.ttf"
        role_font_size = 40

    # Auto-adjust font size if title is long to guarantee 2-line fit
    role_max_w = card_w - content_margin_x * 2 - bar_w
    f_role = ImageFont.truetype(str(f_role_path), role_font_size) if f_role_path.exists() else ImageFont.load_default()
    role_lines = wrap_text_to_width(draw, clean_role, f_role, max_w=role_max_w, is_ar=is_ar)[:2]

    role_y = lbl_y + (lbl_bbox[3] - lbl_bbox[1]) + 16
    for rline in role_lines:
        disp_rline = prepare_bidi_text(rline) if is_ar else rline
        rb_bbox = draw.textbbox((0, 0), disp_rline, font=f_role)
        rw = rb_bbox[2] - rb_bbox[0]
        rh = rb_bbox[3] - rb_bbox[1]
        rx = (card_x2 - content_margin_x - rw) if is_ar else (card_x1 + content_margin_x)
        draw.text((rx, role_y), disp_rline, font=f_role, fill=dark_navy)
        role_y += int(round(role_font_size * 1.25))

    # 4c. Location & Type Row
    loc_str = team_location or ("المنامة، البحرين  •  دوام كامل  •  حضوري" if is_ar else "Manama, Bahrain  •  Full-Time  •  On-Site")
    if is_ar:
        f_loc_path = FONTS_DIR / "Cairo-Medium.ttf"
        if not f_loc_path.exists():
            f_loc_path = FONTS_DIR / "Tajawal-Medium.ttf"
        loc_size = 22
    else:
        f_loc_path = FONTS_DIR / "Poppins-Medium.ttf"
        loc_size = 22
    f_loc = ImageFont.truetype(str(f_loc_path), loc_size) if f_loc_path.exists() else ImageFont.load_default()
    disp_loc = prepare_bidi_text(loc_str) if is_ar else loc_str
    loc_bbox = draw.textbbox((0, 0), disp_loc, font=f_loc)
    loc_w = loc_bbox[2] - loc_bbox[0]
    loc_y = card_y2 - 38 - (loc_bbox[3] - loc_bbox[1])
    if is_ar:
        draw.text((card_x2 - content_margin_x - loc_w, loc_y), disp_loc, font=f_loc, fill=deep_forest)
    else:
        draw.text((card_x1 + content_margin_x, loc_y), disp_loc, font=f_loc, fill=deep_forest)

    # 5. Bottom Sub-Copy & CTA Bar (y = 1070..1250)
    # 5a. Sub-headline / Value Prop
    sub_str = subcopy or ("ابنِ أنظمة ذكية وتأسيسية بلا حدود من قلب المنامة." if is_ar else "Stop maintaining someone else's API. Build foundational vision systems from scratch in Manama.")
    if is_ar:
        f_sub_path = FONTS_DIR / "Tajawal-Medium.ttf"
        if not f_sub_path.exists():
            f_sub_path = FONTS_DIR / "Cairo-Regular.ttf"
        sub_size = 24
    else:
        f_sub_path = FONTS_DIR / "Poppins-Regular.ttf"
        sub_size = 22
    f_sub = ImageFont.truetype(str(f_sub_path), sub_size) if f_sub_path.exists() else ImageFont.load_default()

    sub_lines = wrap_text_to_width(draw, sub_str, f_sub, max_w=936, is_ar=is_ar)[:2]
    sub_y = 1075
    for sline in sub_lines:
        disp_sline = prepare_bidi_text(sline) if is_ar else sline
        sb_bbox = draw.textbbox((0, 0), disp_sline, font=f_sub)
        sw = sb_bbox[2] - sb_bbox[0]
        sx = (1008 - sw) if is_ar else 72
        draw.text((sx, sub_y), disp_sline, font=f_sub, fill=white)
        sub_y += int(round(sub_size * 1.35))

    # 5b. CTA Button Pill
    cta_text = "قدّم الآن  »  lexnis.com/careers" if is_ar else "Apply Now  »  lexnis.com/careers"
    if is_ar:
        f_cta_path = FONTS_DIR / "Cairo-Bold.ttf"
        cta_size = 20
    else:
        f_cta_path = FONTS_DIR / "Poppins-Bold.ttf"
        cta_size = 20
    f_cta = ImageFont.truetype(str(f_cta_path), cta_size) if f_cta_path.exists() else ImageFont.load_default()
    disp_cta = prepare_bidi_text(cta_text) if is_ar else cta_text

    cta_bbox = draw.textbbox((0, 0), disp_cta, font=f_cta)
    cta_tw = cta_bbox[2] - cta_bbox[0]
    cta_th = cta_bbox[3] - cta_bbox[1]

    cta_pad_x = 28
    cta_pad_y = 14
    btn_w = cta_tw + cta_pad_x * 2
    btn_h = cta_th + cta_pad_y * 2
    btn_y = 1180
    btn_x = (1008 - btn_w) if is_ar else 72

    # Draw solid Tech Green CTA button
    draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=btn_h // 2, fill=tech_green)
    # White text inside button
    btn_tx = btn_x + cta_pad_x
    btn_ty = btn_y + cta_pad_y - 2
    draw.text((btn_tx, btn_ty), disp_cta, font=f_cta, fill=white)

    return canvas.convert("RGB")

def re_clean_role(role: str, brand: str) -> str:
    import re
    r = (role or "").strip()
    if brand:
        r = re.sub(rf"^\s*{re.escape(brand)}\s*", "", r, flags=re.IGNORECASE).strip()
    r = re.sub(r"^\s*lexnis(?:\s+technologies)?\s*", "", r, flags=re.IGNORECASE).strip()
    r = re.sub(r"^(?:a|an)\s+", "", r, flags=re.IGNORECASE).strip()
    return r or "Senior Machine Learning &\nVision Systems Engineer"

def re_clean_hook(hook: str, brand: str) -> str:
    import re
    h = (hook or "").strip()
    if brand:
        h = re.sub(rf"^\s*{re.escape(brand)}\s*", "", h, flags=re.IGNORECASE).strip()
    h = re.sub(r"^\s*lexnis(?:\s+technologies)?\s*", "", h, flags=re.IGNORECASE).strip()
    return h or "BUILD THE FUTURE OF AI"

def wrap_text_to_width(draw, text: str, font, max_w: int, is_ar: bool = False):
    import re
    if "\n" in text:
        res = []
        for segment in text.split("\n"):
            res.extend(wrap_text_to_width(draw, segment, font, max_w, is_ar))
        return res

    words = text.split()
    if not words:
        return [""]

    lines = []
    curr = words[0]
    for w in words[1:]:
        cand = curr + " " + w
        disp = prepare_bidi_text(cand) if is_ar else cand
        bbox = draw.textbbox((0, 0), disp, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            curr = cand
        else:
            lines.append(curr)
            curr = w
    lines.append(curr)
    return lines

if __name__ == "__main__":
    out_dir = BASE_DIR / "output" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    en_img = build_hiring_card_prototype(
        role_title="Senior Machine Learning &\nVision Systems Engineer",
        team_location="Manama, Bahrain  •  Full-Time  •  On-Site",
        hook_headline="BUILD THE FUTURE OF AI",
        subcopy="Stop maintaining someone else's API. Build foundational vision systems from scratch in Manama.",
        language="en"
    )
    en_path = out_dir / "prototype_hiring_en.jpg"
    en_img.save(en_path, quality=95)
    print(f"Saved EN prototype to {en_path}")

    ar_img = build_hiring_card_prototype(
        role_title="مهندس أول تعلم الآلة\nوأنظمة الرؤية الحاسوبية",
        team_location="المنامة، البحرين  •  دوام كامل  •  حضوري",
        hook_headline="ريادة الرؤية الحاسوبية",
        subcopy="ابنِ أنظمة ذكية وتأسيسية بلا حدود من قلب المنامة.",
        language="ar"
    )
    ar_path = out_dir / "prototype_hiring_ar.jpg"
    ar_img.save(ar_path, quality=95)
    print(f"Saved AR prototype to {ar_path}")
