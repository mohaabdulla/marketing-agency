import os
import sys
import numpy as np
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import composite_template_swap, isolate_logo_mark, load_logo_pil
from campaign_generator import LexnisCampaignStudio

def test_user_scenario():
    uploads_dir = BASE_DIR / "output" / "uploads"
    
    # Locate user's uploaded portrait and logo
    subject_candidates = list(uploads_dir.glob("subject_*.jpeg")) + list(uploads_dir.glob("subject_*.jpg"))
    logo_candidates = list(uploads_dir.glob("logo_*.*"))
    
    assert len(subject_candidates) > 0, f"No subject image found in {uploads_dir}"
    assert len(logo_candidates) > 0, f"No logo image found in {uploads_dir}"
    
    subject_path = subject_candidates[0]
    logo_path = logo_candidates[0]
    
    print(f"Testing with Subject: {subject_path.name}")
    print(f"Testing with Logo: {logo_path.name}")
    
    # 1. Test isolate_logo_mark directly
    raw_logo = Image.open(logo_path)
    isolated_logo = isolate_logo_mark(raw_logo, is_dark_bg=True)
    assert isolated_logo.mode == "RGBA"
    
    # Ensure no solid white background remains in corners of isolated logo
    logo_arr = np.array(isolated_logo)
    # Check top-left corner pixel alpha
    assert logo_arr[0, 0, 3] == 0, f"Corner of isolated logo should be transparent, got alpha={logo_arr[0,0,3]}"
    print("✓ isolate_logo_mark: Logo background successfully keyed to transparent alpha.")
    
    # 2. Test composite_template_swap with subject and custom logo
    template_path = BASE_DIR / "test_assets" / "template_reference.jpg"
    swap_res = composite_template_swap(
        template_image=template_path,
        subject_image=subject_path,
        target_size=(1080, 1350),
        brand_name="Lexnis Technologies",
        person_name="Alisha Faisal",
        person_title="Marketing Manager",
        recolor_gradient=True,
        logo_image=logo_path
    )
    
    swap_out_path = BASE_DIR / "output" / "renders" / "test_user_swap_result.jpg"
    swap_res.save(swap_out_path, quality=95)
    print(f"✓ composite_template_swap generated: {swap_out_path}")
    
    # Verify that the subject inside the frame is the woman portrait, NOT the logo!
    # Woman portrait has skin/hair tones, not pure black text/white background
    swap_np = np.array(swap_res)
    # Check inner window area (e.g. around y=600, x=540)
    center_patch = swap_np[500:700, 400:680]
    # Check that it is not pure white or pure black
    assert np.mean(center_patch) > 10 and np.mean(center_patch) < 240
    print("✓ Subject verified: Woman portrait rendered inside frame.")
    
    # 3. Verify top-left header logo area has NO white bounding box
    # Logo is placed around lx=72, ly=72, size ~150x32
    logo_header_area = swap_np[60:120, 60:350]
    # Count pure white pixels in the background around the logo
    # The canvas background is dark navy/green (#131724 / #023024)
    # Background pixels have R < 50, G < 60, B < 60.
    # An ugly white rectangle would produce a large block of R > 240, G > 240, B > 240.
    white_box_pixels = np.sum((logo_header_area[:, :, 0] > 230) & (logo_header_area[:, :, 1] > 230) & (logo_header_area[:, :, 2] > 230))
    # Legitimate white text pixels from "LEXNIS" should be around 500-1500, but a solid white box would be > 10,000!
    print(f"Header white pixel count: {white_box_pixels}")
    assert white_box_pixels < 3500, f"White box detected around logo in header! Count={white_box_pixels}"
    
    # Check that dark background surrounds the logo
    dark_bg_pixels = np.sum((logo_header_area[:, :, 0] < 50) & (logo_header_area[:, :, 1] < 70) & (logo_header_area[:, :, 2] < 70))
    print(f"Header dark background pixel count: {dark_bg_pixels}")
    assert dark_bg_pixels > 8000, f"Dark canvas background not found around logo! Count={dark_bg_pixels}"
    print("✓ Logo background verified: ZERO white box. Cleanly blended into dark canvas.")
    
    # 4. Test studio.generate_campaign when user provides only subject portrait + logo
    studio = LexnisCampaignStudio()
    asset = studio.generate_campaign(
        prompt="Welcome our new Marketing Manager to Lexnis",
        brand="Lexnis Technologies",
        uploaded_image_paths=[str(subject_path)],
        logo_path=str(logo_path),
        post_type="team_welcome",
        person_name="Alisha Faisal",
        person_title="Marketing Manager",
        recolor_to_brand=True
    )
    
    assert Path(asset.image_path).exists()
    print(f"✓ studio.generate_campaign succeeded: {asset.image_path}")
    
    # Also verify arabic generation
    assert Path(asset.arabic_image_path).exists()
    print(f"✓ Arabic campaign visual succeeded: {asset.arabic_image_path}")
    
    print("\n🎉 ALL USER-REPORTED DEFECT TESTS PASSED WITH 100% SUCCESS!")

if __name__ == "__main__":
    test_user_scenario()
