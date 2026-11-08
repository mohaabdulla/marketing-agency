import os
import sys
from pathlib import Path
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import composite_template_swap
from campaign_generator import LexnisCampaignStudio, detect_featured_person

def test_hiring_post_type():
    print("Testing 'We\\'re Hiring' post type adaptation...")

    # 1. Test detect_featured_person on hiring prompt
    hiring_prompt = "Recruitment campaign for Lexnis Technologies: We are hiring Senior Machine Learning & Vision Systems Engineer for our Lexnis Core AI Lab, Manama / Hybrid."
    detected_role, detected_team = detect_featured_person(hiring_prompt, post_type="hiring")
    print(f"Detected Role: {detected_role}")
    print(f"Detected Team: {detected_team}")
    assert "Machine Learning" in detected_role
    assert "Lexnis Core AI Lab" in detected_team
    print("✓ detect_featured_person correctly extracted open role and team.")

    # 2. Test composite_template_swap with post_type='hiring'
    template_path = BASE_DIR / "test_assets" / "template_reference.jpg"
    subject_path = BASE_DIR / "test_assets" / "raw_subject.jpg"
    uploads_dir = BASE_DIR / "output" / "uploads"
    logo_candidates = list(uploads_dir.glob("logo_*.*"))
    logo_path = logo_candidates[0] if logo_candidates else None

    swap_hiring = composite_template_swap(
        template_image=template_path,
        subject_image=subject_path,
        target_size=(1080, 1350),
        person_name=detected_role,
        person_title=detected_team,
        brand_name="Lexnis Technologies",
        post_type="hiring",
        recolor_gradient=True,
        logo_image=logo_path
    )
    
    out_dir = BASE_DIR / "output" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    hiring_out_path = out_dir / "test_hiring_swap_result.jpg"
    swap_hiring.save(hiring_out_path, quality=95)
    print(f"✓ Saved hiring swap result to {hiring_out_path}")

    # 3. Test composite_template_swap in Arabic for hiring
    swap_hiring_ar = composite_template_swap(
        template_image=template_path,
        subject_image=subject_path,
        target_size=(1080, 1350),
        person_name="مهندس تعلم الآلة والرؤية الحاسوبية",
        person_title="مختبر لكسنس للذكاء الاصطناعي · دوام هجين",
        brand_name="Lexnis Technologies",
        post_type="hiring",
        language="ar",
        recolor_gradient=True,
        logo_image=logo_path
    )
    hiring_ar_out_path = out_dir / "test_hiring_swap_ar_result.jpg"
    swap_hiring_ar.save(hiring_ar_out_path, quality=95)
    print(f"✓ Saved Arabic hiring swap result to {hiring_ar_out_path}")

    # 4. End-to-end studio campaign generation for 'hiring'
    studio = LexnisCampaignStudio()
    asset = studio.generate_campaign(
        prompt=hiring_prompt,
        brand="Lexnis Technologies",
        post_type="hiring",
        person_name=detected_role,
        person_title=detected_team,
        recolor_to_brand=True
    )
    print(f"✓ Campaign generated: {asset.image_path}")
    print(f"✓ Arabic visual generated: {asset.arabic_image_path}")

    # Assert that the prompt enhancement and brief recognize hiring, not welcome Alisha
    brief = asset.brief or {}
    product_name = brief.get("product_name", "")
    print(f"Brief Product Name: {product_name}")
    assert "Alisha" not in product_name
    assert "Hiring" in product_name or "Careers" in product_name or "Machine Learning" in product_name or "Senior" in product_name

    print("\n🎉 ALL 'WE\\'RE HIRING' TESTS PASSED WITH 100% SUCCESS!")

if __name__ == "__main__":
    test_hiring_post_type()

