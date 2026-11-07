import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import re
from visual_engine import extract_subject_matte, prepare_bidi_text

FONTS_DIR = Path("static/fonts")

def render_lexnis_logo(height=34, is_dark_bg=True):
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
    t_bbox = d_draw.textbbox((0, 0), text_str, font=font_hi)
    text_w = t_bbox[2] - t_bbox[0]
    text_h = t_bbox[3] - t_bbox[1]
    
    chev_h = int(text_h * 0.88)
    chev_w = int(chev_h * (336.0 / 284.0))
    chev_t = max(2, int(chev_w * 0.28))
    clear_space = int(l_h * 0.65)
    chev_pitch = int(chev_w * 0.70)
    
    total_w_hi = text_w + clear_space + chev_w + chev_pitch + int(l_h * 0.4)
    total_h_hi = int(h_hi * 1.25)
    
    logo_hi = Image.new('RGBA', (total_w_hi, total_h_hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo_hi)
    
    text_y = (total_h_hi - text_h) // 2 - t_bbox[1]
    draw.text((0, text_y), text_str, font=font_hi, fill=text_color)
    
    chev_start_x = text_w + clear_space
    cy = total_h_hi // 2
    top = cy - chev_h // 2
    bot = cy + chev_h // 2
    
    def draw_chev(cx, color):
        pts = [
            (cx, top),
            (cx + chev_w, cy),
            (cx, bot),
            (cx - chev_t, bot),
            (cx + chev_w - chev_t, cy),
            (cx - chev_t, top)
        ]
        draw.polygon(pts, fill=color)
        
    draw_chev(chev_start_x, tech_green)
    draw_chev(chev_start_x + chev_pitch, lime_green)
    
    final_w = int(total_w_hi / scale)
    final_h = int(total_h_hi / scale)
    return logo_hi.resize((final_w, final_h), Image.Resampling.LANCZOS)

def generate_chevron_field(width, height, opacity=0.12, stroke_color=(83, 184, 73)):
    pat = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pat)
    
    target_ch = int(height * 0.045)
    scale = target_ch / 284.0
    cw = int(336.0 * scale)
    ch = target_ch
    pitch_x = int(261.0 * scale)
    step_y = int(ch * 0.90)
    step_x = int(-130.0 * scale)
    t = max(2, int(cw * 0.28))
    
    fill_rgba = (stroke_color[0], stroke_color[1], stroke_color[2], int(255 * opacity))
    
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
            pts = [
                (x, top),
                (x + cw, cy),
                (x, bot),
                (x - t, bot),
                (x + cw - t, cy),
                (x - t, top)
            ]
            draw.polygon(pts, fill=fill_rgba)
            x += pitch_x
        y += step_y
        row += 1
        
    return pat

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

def run_test_upgrade():
    template_path = Path("test_assets/template_reference.jpg")
    subject_path = Path("test_assets/raw_subject.jpg")
    
    t_bgr = cv2.imread(str(template_path))
    W, H = 808, 1024
    
    # 1. Base Depth Gradient + Chevron Field Substrate
    bg_bgr = render_depth_gradient(W, H, "#131724", "#023024")
    bg_field = generate_chevron_field(W, H, opacity=0.12, stroke_color=(83, 184, 73))
    
    # Composite chevron pattern onto background
    bg_rgb = cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB)
    bg_pil = Image.fromarray(bg_rgb)
    bg_pil.paste(bg_field, (0, 0), bg_field)
    clean_plate = cv2.cvtColor(np.array(bg_pil), cv2.COLOR_RGB2BGR)
    
    # Frame geometry (benchmark 808x1024)
    fx, fy, fw, fh = 195, 294, 418, 505
    ix, iy, iw, ih = 203, 302, 402, 366
    border_px = 8
    nx, ny, nw, nh = 195, 668, 418, 131
    margin_left_px = 28
    
    # Draw white Polaroid outer card
    clean_plate[fy:fy + fh, fx:fx + fw] = [255, 255, 255]
    # Re-fill inner photo window with substrate
    clean_plate[iy:iy + ih, ix:ix + iw] = cv2.cvtColor(np.array(bg_pil), cv2.COLOR_RGB2BGR)[iy:iy + ih, ix:ix + iw]
    
    # Layer 2: Render crisp vector anti-aliased WELCOME headline
    plate_pil = Image.fromarray(cv2.cvtColor(clean_plate, cv2.COLOR_BGR2RGB))
    draw_p = ImageDraw.Draw(plate_pil)
    
    font_bold_path = FONTS_DIR / "Poppins-Bold.ttf"
    font_hl = ImageFont.truetype(str(font_bold_path), 56)
    
    hl_text = "WELCOME"
    bbox_hl = draw_p.textbbox((0, 0), hl_text, font=font_hl)
    hl_w = bbox_hl[2] - bbox_hl[0]
    draw_p.text(((W - hl_w) // 2, 196), hl_text, font=font_hl, fill=(255, 255, 255))
    clean_plate = cv2.cvtColor(np.array(plate_pil), cv2.COLOR_RGB2BGR)
    
    # Layer 3: Subject Matting and 2.5D Pop-Out Compositing
    subj_rgba = extract_subject_matte(subject_path)
    H_sub, W_sub = subj_rgba.shape[:2]
    
    base_affine = np.array([
        [8.04139148e-01, 1.02160041e-03, 3.91566333e+01],
        [-1.02160041e-03, 8.04139148e-01, 1.41156860e+02]
    ], dtype=np.float32)
    sx = 1024.0 / float(W_sub)
    sy = 683.0 / float(H_sub)
    affine = base_affine.copy()
    affine[:, 0] *= sx
    affine[:, 1] *= sy
    
    warped = cv2.warpAffine(subj_rgba, affine, (W, H), flags=cv2.INTER_LANCZOS4)
    w_bgr = warped[:, :, :3]
    w_alpha = warped[:, :, 3].astype(np.float32) / 255.0
    
    y_grid, x_grid = np.mgrid[0:H, 0:W]
    body_region = (y_grid >= fy) & (y_grid < ny) & (x_grid >= fx) & (x_grid <= fx + fw)
    head_region = (y_grid < fy)
    allowed_mask = (body_region | head_region).astype(np.float32)
    eff_alpha = w_alpha * allowed_mask
    
    composite = clean_plate.copy().astype(np.float32)
    for c in range(3):
        composite[:, :, c] = composite[:, :, c] * (1.0 - eff_alpha) + w_bgr[:, :, c].astype(np.float32) * eff_alpha
    composite = np.clip(composite, 0, 255).astype(np.uint8)
    
    # Layer 4: Nameplate Box with Lexnis Brand Cues
    composite[ny:ny + nh, nx:nx + nw] = [255, 255, 255]
    
    np_pil = Image.new('RGB', (nw, nh), (255, 255, 255))
    draw_np = ImageDraw.Draw(np_pil)
    
    f_name = ImageFont.truetype(str(font_bold_path), 28)
    font_med_path = FONTS_DIR / "Poppins-Medium.ttf"
    f_role = ImageFont.truetype(str(font_med_path), 14)
    
    dark_navy = (19, 23, 36)      # #131724
    tech_green = (83, 184, 73)    # #53B849
    div_marketing = (255, 92, 138)# #FF5C8A (Tier 3 Digital Marketing)
    
    # Draw Name in Dark Navy #131724
    person_name = "Alisha Faisal"
    draw_np.text((margin_left_px, 18), person_name, font=f_name, fill=dark_navy)
    
    # Brand Divider Rule: 2px Tech Green #53B849
    draw_np.line([(margin_left_px, 58), (nw - margin_left_px, 58)], fill=tech_green, width=2)
    
    # Draw Role in Tech Green #53B849
    person_title = "Marketing Manager"
    draw_np.text((margin_left_px, 68), person_title, font=f_role, fill=tech_green)
    
    np_cv = cv2.cvtColor(np.array(np_pil), cv2.COLOR_RGB2BGR)
    composite[ny:ny + nh, nx:nx + nw] = np_cv
    
    # Layer 5: Top Logo & Hashtag
    comp_pil = Image.fromarray(cv2.cvtColor(composite, cv2.COLOR_BGR2RGB))
    draw_top = ImageDraw.Draw(comp_pil)
    
    # Render official Lexnis vector logo
    logo_img = render_lexnis_logo(height=34, is_dark_bg=True)
    lx, ly = 52, 58
    comp_pil.paste(logo_img, (lx, ly), logo_img)
    
    # Render corporate hashtag #LexnisTeam
    f_tag = ImageFont.truetype(str(font_med_path), 16)
    tag_str = "#LexnisTeam"
    draw_top = ImageDraw.Draw(comp_pil)
    draw_top.text((596, 68), tag_str, font=f_tag, fill=(255, 255, 255))
    
    # Layer 6: Footer Caption
    f_foot = ImageFont.truetype(str(FONTS_DIR / "Poppins-Regular.ttf"), 16)
    foot_str = "We are so excited to have you on our team!"
    bbox_foot = draw_top.textbbox((0, 0), foot_str, font=f_foot)
    foot_w = bbox_foot[2] - bbox_foot[0]
    draw_top.text(((W - foot_w) // 2, 846), foot_str, font=f_foot, fill=(255, 255, 255))
    
    out_dir = Path("static/assets")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "debug_lexnis_brand_upgrade.jpg"
    comp_pil.save(out_file, format="JPEG", quality=95)
    print(f"Upgrade test rendered successfully to {out_file}!")

if __name__ == "__main__":
    run_test_upgrade()
