import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re

FONTS_DIR = Path("static/fonts")

def render_lexnis_logo(height=40, is_dark_bg=True):
    font_path = FONTS_DIR / "Poppins-Bold.ttf"
    scale = 4
    h_hi = height * scale
    f_size_hi = int(h_hi * 0.72)
    font_hi = ImageFont.truetype(str(font_path), f_size_hi) if font_path.exists() else ImageFont.load_default()

    text_color = (255, 255, 255, 255) if is_dark_bg else (19, 23, 36, 255)
    tech_green = (83, 184, 73, 255)   # #53B849
    lime_green = (188, 215, 85, 255)  # #BCD755

    dummy = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    d_draw = ImageDraw.Draw(dummy)
    l_bbox = d_draw.textbbox((0, 0), 'L', font=font_hi)
    l_h = l_bbox[3] - l_bbox[1]

    text_str = 'LEXNIS'
    tracking_hi = int(-0.02 * f_size_hi)
    char_widths = []
    for c in text_str:
        cb = d_draw.textbbox((0, 0), c, font=font_hi)
        char_widths.append(cb[2] - cb[0])
    text_w_hi = sum(char_widths) + tracking_hi * (len(text_str) - 1)
    text_h_hi = l_h

    # Dual chevrons: solid ribbon thickness = 22% of cap-height
    ribbon_t_hi = max(4, int(0.22 * l_h))
    chev_h_hi = int(l_h * 0.92)
    chev_w_hi = int(chev_h_hi * (336.0 / 284.0))
    clear_space_hi = int(l_h * 0.85)
    chev_pitch_hi = int(chev_w_hi * 0.75)

    total_w_hi = text_w_hi + clear_space_hi + chev_w_hi + ribbon_t_hi + chev_pitch_hi + int(l_h * 0.3)
    total_h_hi = int(h_hi * 1.35)

    logo_hi = Image.new('RGBA', (total_w_hi, total_h_hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo_hi)

    cur_x = 0
    y_pos = (total_h_hi - text_h_hi) // 2 - l_bbox[1]
    for c in text_str:
        draw.text((cur_x, y_pos), c, font=font_hi, fill=text_color)
        cb = d_draw.textbbox((0, 0), c, font=font_hi)
        cur_x += (cb[2] - cb[0]) + tracking_hi

    chev_start_x = text_w_hi + clear_space_hi
    cy = total_h_hi // 2
    top = cy - chev_h_hi // 2
    bot = cy + chev_h_hi // 2

    def draw_ribbon_chev(cx, color):
        pts = [
            (cx + ribbon_t_hi, top),
            (cx + chev_w_hi + ribbon_t_hi, cy),
            (cx + ribbon_t_hi, bot),
            (cx, bot),
            (cx + chev_w_hi, cy),
            (cx, top)
        ]
        draw.polygon(pts, fill=color)

    draw_ribbon_chev(chev_start_x, tech_green)
    draw_ribbon_chev(chev_start_x + chev_pitch_hi, lime_green)

    final_w = max(1, int(total_w_hi / scale))
    final_h = max(1, int(total_h_hi / scale))
    return logo_hi.resize((final_w, final_h), Image.Resampling.LANCZOS)


def generate_core_chevron_field(width=1080, height=1350, opacity=0.12):
    pat = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pat)

    # 4 to 5 large bold chevrons across width
    cw = int(width / 4.6)
    ch = int(cw * (284.0 / 336.0))
    pitch_x = int(cw * (261.0 / 336.0))
    step_y = int(ch * 0.72)
    step_x = int(-cw * (130.0 / 336.0))
    t = int(cw * 0.22)

    # Signature Gradient stops: #023024 -> #53B849
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

            pts = [
                (x + t, top),
                (x + cw + t, cy),
                (x + t, bot),
                (x, bot),
                (x + cw, cy),
                (x, top)
            ]
            draw.polygon(pts, fill=fill_rgba)
            x += pitch_x
        y += step_y
        row += 1

    return pat


def render_studio_inner_window(iw, ih, c_start_hex="#131724", c_end_hex="#023024"):
    def hex_to_bgr(h):
        h = h.lstrip('#')
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return np.array([b, g, r], dtype=np.float32)

    c1 = hex_to_bgr(c_start_hex)
    c2 = hex_to_bgr(c_end_hex)

    y_grid, x_grid = np.mgrid[0:ih, 0:iw]
    u = x_grid / float(iw)
    v = 1.0 - (y_grid / float(ih))
    diag = np.clip((u + v) * 0.5, 0.0, 1.0)
    bg = (c1[None, None, :] * (1.0 - diag[:, :, None]) + c2[None, None, :] * diag[:, :, None])

    # Soft radial studio backlight glow (#1E3A34 -> BGR: 52, 58, 30)
    glow_bgr = np.array([52, 58, 30], dtype=np.float32)
    cx = iw / 2.0
    cy = ih * 0.45
    radius = iw * 0.55
    dist = np.sqrt((x_grid - cx)**2 + (y_grid - cy)**2)
    glow_factor = np.clip(1.0 - (dist / radius), 0.0, 1.0)**2 * 0.28

    final_win = (bg * (1.0 - glow_factor[:, :, None]) + glow_bgr[None, None, :] * glow_factor[:, :, None]).clip(0, 255).astype(np.uint8)
    return final_win


def render_depth_gradient(width, height, c_start_hex="#131724", c_end_hex="#023024"):
    def hex_to_bgr(h):
        h = h.lstrip('#')
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return np.array([b, g, r], dtype=np.float32)

    c1 = hex_to_bgr(c_start_hex)
    c2 = hex_to_bgr(c_end_hex)

    y_grid, x_grid = np.mgrid[0:height, 0:width]
    u = x_grid / float(width)
    v = 1.0 - (y_grid / float(height))
    diag = np.clip((u + v) * 0.5, 0.0, 1.0)

    bg = (c1[None, None, :] * (1.0 - diag[:, :, None]) + c2[None, None, :] * diag[:, :, None]).clip(0, 255).astype(np.uint8)
    return bg


def sanitize_brand_tag(raw_tag, brand_name="Lexnis"):
    b = (brand_name or "Lexnis").strip()
    default_tag = "#LexnisTeam" if "lexnis" in b.lower() else f"#{re.sub(r'[^a-zA-Z0-9]', '', b)}Team"
    if not raw_tag or not isinstance(raw_tag, str):
        return default_tag
    tag = raw_tag.strip()
    if not tag.startswith('#'):
        tag = '#' + tag
    tag_body = tag.lstrip('#')
    if len(tag_body) < 5 or bool(re.match(r'^[0-9a-fA-F]{3,8}$', tag_body)) or tag_body.lower() in ('ud3', '0d3', 'none', 'null', 'hex'):
        return default_tag
    return tag


def run_full_1080x1350_test():
    from visual_engine import extract_subject_matte, prepare_bidi_text

    W, H = 1080, 1350
    sx = W / 808.0
    sy = H / 1024.0

    # 1. Base Depth Gradient + Large Core Chevron Field
    bg_bgr = render_depth_gradient(W, H, "#131724", "#023024")
    bg_field = generate_core_chevron_field(W, H, opacity=0.12)
    bg_pil = Image.fromarray(cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB))
    bg_pil.paste(bg_field, (0, 0), bg_field)
    clean_plate = cv2.cvtColor(np.array(bg_pil), cv2.COLOR_RGB2BGR)

    # Outer Frame & Inner Window Sizing
    fw = int(418 * sx) # 558px
    fh = int(505 * sy) # 666px
    fx = (W - fw) // 2 # 261px
    fy = int(294 * sy) # 388px
    border_px = int(8 * sx) # 11px

    # Nameplate height: ~16.5% of canvas height (222px)
    nh = int(H * 0.165)
    nw = fw
    nx = fx
    ny = fy + fh - nh

    ix = fx + border_px
    iy = fy + border_px
    iw = fw - 2 * border_px
    ih = ny - iy

    # 2. Polaroid Outer Card (Pure White)
    clean_plate[fy:fy + fh, fx:fx + fw] = [255, 255, 255]

    # 3. Clean Studio Inner Window (ZERO Chevron Pattern Bleed!)
    studio_win = render_studio_inner_window(iw, ih, "#131724", "#023024")
    clean_plate[iy:iy + ih, ix:ix + iw] = studio_win

    # 4. Layer 2: WELCOME Headline (88%-90% of frame width, custom tracking)
    plate_pil = Image.fromarray(cv2.cvtColor(clean_plate, cv2.COLOR_BGR2RGB))
    draw_hl = ImageDraw.Draw(plate_pil)

    font_hl_size = int(92 * (H / 1350.0))
    font_hl = ImageFont.truetype(str(FONTS_DIR / "Poppins-Bold.ttf"), font_hl_size)
    tracking = int(font_hl_size * 0.055)

    hl_text = "WELCOME"
    char_widths = [draw_hl.textbbox((0, 0), c, font=font_hl)[2] - draw_hl.textbbox((0, 0), c, font=font_hl)[0] for c in hl_text]
    total_hl_w = sum(char_widths) + tracking * (len(hl_text) - 1)
    span_ratio = total_hl_w / float(fw)
    print(f"WELCOME total width = {total_hl_w}px, Frame width = {fw}px, Span ratio = {span_ratio:.3f} (target: 0.88-0.90)")

    hl_x_start = (W - total_hl_w) // 2
    # Vertical positioning: bottom of WELCOME at y=318 so head (at y=299) overlaps bottom 28% of C and O
    hl_cap_h = draw_hl.textbbox((0, 0), "E", font=font_hl)[3] - draw_hl.textbbox((0, 0), "E", font=font_hl)[1]
    hl_y = 318 - hl_cap_h

    cur_x = hl_x_start
    for c in hl_text:
        draw_hl.text((cur_x, hl_y), c, font=font_hl, fill=(255, 255, 255))
        cb = draw_hl.textbbox((0, 0), c, font=font_hl)
        cur_x += (cb[2] - cb[0]) + tracking

    clean_plate = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)

    # 5. Layer 3: Subject Matting & 2.5D Pop-Out Compositing
    subj_rgba = extract_subject_matte(Path("test_assets/raw_subject.jpg"))
    H_sub, W_sub = subj_rgba.shape[:2]

    base_affine = np.array([
        [8.04139148e-01, 1.02160041e-03, 3.91566333e+01],
        [-1.02160041e-03, 8.04139148e-01, 1.41156860e+02]
    ], dtype=np.float32)

    affine = base_affine.copy()
    affine[0, :] *= sx
    affine[1, :] *= sy
    affine[:, 0] *= 1024.0 / float(W_sub)
    affine[:, 1] *= 683.0 / float(H_sub)

    warped = cv2.warpAffine(subj_rgba, affine, (W, H), flags=cv2.INTER_LANCZOS4)
    w_bgr = warped[:, :, :3]
    w_alpha = warped[:, :, 3].astype(np.float32) / 255.0

    y_grid, x_grid = np.mgrid[0:H, 0:W]
    body_region = (y_grid >= fy) & (y_grid < ny) & (x_grid >= ix) & (x_grid <= ix + iw)
    head_region = (y_grid < fy)
    allowed_mask = (body_region | head_region).astype(np.float32)
    eff_alpha = w_alpha * allowed_mask

    composite = clean_plate.copy().astype(np.float32)
    for c in range(3):
        composite[:, :, c] = composite[:, :, c] * (1.0 - eff_alpha) + w_bgr[:, :, c].astype(np.float32) * eff_alpha
    composite = np.clip(composite, 0, 255).astype(np.uint8)

    # Verify head overlap on WELCOME letters C and O
    alpha_head = eff_alpha[:318, :]
    overlap_y_min = np.min(np.where(alpha_head > 0.3)[0])
    head_overlap_px = 318 - overlap_y_min
    head_overlap_pct = head_overlap_px / float(hl_cap_h)
    print(f"Head top y = {overlap_y_min}, WELCOME bottom = 318, Overlap = {head_overlap_px}px ({head_overlap_pct*100:.1f}% of cap-height, target: 20-35%)")

    # 6. Layer 4: 2-Line Stacked Nameplate with Status Tile Accent Bar
    composite[ny:ny + nh, nx:nx + nw] = [255, 255, 255]

    np_pil = Image.new('RGB', (nw, nh), (255, 255, 255))
    draw_np = ImageDraw.Draw(np_pil)

    font_name_size = int(48 * (H / 1350.0))
    font_bold = ImageFont.truetype(str(FONTS_DIR / "Poppins-Bold.ttf"), font_name_size)
    font_role = ImageFont.truetype(str(FONTS_DIR / "Poppins-Medium.ttf"), int(21 * (H / 1350.0)))

    dark_navy = (19, 23, 36)      # #131724
    tech_green = (83, 184, 73)    # #53B849

    margin_l = int(38 * sx)
    y_l1 = int(26 * sy)
    y_l2 = y_l1 + int(font_name_size * 1.05)

    # 2 stacked lines
    draw_np.text((margin_l, y_l1), 'Alisha', font=font_bold, fill=dark_navy)
    draw_np.text((margin_l, y_l2), 'Faisal', font=font_bold, fill=dark_navy)

    # Vertical 4px Status Tile Accent Bar in Tech Green #53B849
    y_role = y_l2 + int(56 * sy)
    bar_h = int(20 * sy)
    draw_np.rectangle([margin_l, y_role + 2, margin_l + 4, y_role + 2 + bar_h], fill=tech_green)

    # Role text in Tech Green #53B849
    draw_np.text((margin_l + 14, y_role), 'Marketing Manager', font=font_role, fill=tech_green)

    np_cv = cv2.cvtColor(np.array(np_pil), cv2.COLOR_RGB2BGR)
    composite[ny:ny + nh, nx:nx + nw] = np_cv

    # 7. Layer 5: Top Header with Official Logo and #LexnisTeam Hashtag
    comp_pil = Image.fromarray(cv2.cvtColor(composite, cv2.COLOR_BGR2RGB))
    logo_img = render_lexnis_logo(height=int(40 * (H / 1350.0)), is_dark_bg=True)
    comp_pil.paste(logo_img, (int(72 * sx), int(72 * sy)), logo_img)

    f_tag = ImageFont.truetype(str(FONTS_DIR / "Poppins-Medium.ttf"), int(20 * (H / 1350.0)))
    final_tag = sanitize_brand_tag("#LexnisTeam", "Lexnis Technologies")
    draw_top = ImageDraw.Draw(comp_pil)
    tag_w = draw_top.textbbox((0, 0), final_tag, font=f_tag)[2] - draw_top.textbbox((0, 0), final_tag, font=f_tag)[0]
    draw_top.text((W - int(72 * sx) - tag_w, int(72 * sy)), final_tag, font=f_tag, fill=(255, 255, 255))

    # 8. Layer 6: Footer Caption
    f_foot = ImageFont.truetype(str(FONTS_DIR / "Poppins-Regular.ttf"), int(20 * (H / 1350.0)))
    foot_str = "We are so excited to have you on our team!"
    bbox_foot = draw_top.textbbox((0, 0), foot_str, font=f_foot)
    foot_w = bbox_foot[2] - bbox_foot[0]
    draw_top.text(((W - foot_w) // 2, fy + fh + int(56 * sy)), foot_str, font=f_foot, fill=(255, 255, 255))

    out_file = Path("static/assets/debug_lexnis_brand_upgrade.jpg")
    comp_pil.save(out_file, format="JPEG", quality=95)
    print(f"Full-bleed 1080x1350 visual rendered and saved to {out_file} (Size: {comp_pil.size})")

if __name__ == "__main__":
    run_full_1080x1350_test()

