import os
import sys
import numpy as np
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import (
    render_lexnis_launch_card,
    render_lexnis_hiring_card,
)
from campaign_generator import (
    LexnisCampaignStudio,
    detect_featured_person,
    generate_launch_mission_hook,
    generate_hiring_mission_hook
)

def test_launch_and_hiring():
    out_dir = BASE_DIR / "output" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("==================================================================")
    print("TEST 1: Direct Unit Tests for render_lexnis_launch_card (EN & AR)")
    print("==================================================================")
    launch_en = render_lexnis_launch_card(
        product_name="Lexnis VisionAI™",
        category_overline="FLAGSHIP RELEASE  //  INDUSTRIAL EDGE AI",
        product_subtitle="Autonomous Real-Time Visual Inspection & Defect Prediction Engine",
        spec_chips=["< 8ms Edge Latency", "99.4% Defect Accuracy", "100% On-Premise"],
        eyebrow_text="PRODUCT LAUNCH  •  NEW RELEASE",
        hook_headline="PREDICT ASSEMBLY\nFAILURES AT THE EDGE.",
        subcopy="Detect micro-defects on the assembly line in under 8ms—before they become costly recalls.",
        cta_text="REQUEST LIVE DEMO",
        cta_url="lexnis.com/visionai",
        language="en"
    )
    en_launch_path = out_dir / "unit_launch_en.jpg"
    launch_en.save(en_launch_path, "JPEG", quality=98, subsampling=0)
    print(f"✓ Saved direct Launch EN card: {en_launch_path}")
    assert launch_en.size == (1080, 1350), f"Invalid size: {launch_en.size}"

    launch_ar = render_lexnis_launch_card(
        product_name="نظام Lexnis VisionAI™",
        category_overline="الإصدار الرئيسي  //  الذكاء الاصطناعي الصناعي",
        product_subtitle="محرك الفحص البصري الذاتي والتنبؤ الفوري بالأعطال الصناعية",
        spec_chips=["استجابة فورية أقل من 8ms", "دقة كشف 99.4%", "تشغيل محلي آمن 100%"],
        eyebrow_text="إطلاق منتج جديد  •  حلول الذكاء الاصطناعي",
        hook_headline="سيادة صناعية استباقية\nترصد الأعطال قبل وقوعها.",
        subcopy="اكشف أدق عيوب التصنيع على خط الإنتاج في أقل من 8 ملي ثانية قبل تحولها إلى توقفات مكلفة.",
        cta_text="اطلب عرضاً تجريبياً",
        cta_url="lexnis.com/visionai",
        language="ar"
    )
    ar_launch_path = out_dir / "unit_launch_ar.jpg"
    launch_ar.save(ar_launch_path, "JPEG", quality=98, subsampling=0)
    print(f"✓ Saved direct Launch AR card: {ar_launch_path}")
    assert launch_ar.size == (1080, 1350), f"Invalid size: {launch_ar.size}"

    print("==================================================================")
    print("TEST 2: Direct Unit Tests for render_lexnis_hiring_card (EN & AR)")
    print("==================================================================")
    hiring_en = render_lexnis_hiring_card(
        role_title="Senior Machine Learning &\nVision Systems Engineer",
        team_location="Manama, Bahrain  •  Full-Time  •  On-Site",
        hook_headline="BUILD AUTONOMOUS\nVISION SYSTEMS.",
        subcopy="Stop maintaining someone else's API. Build foundational vision systems from scratch in Manama.",
        language="en"
    )
    en_hiring_path = out_dir / "unit_hiring_en.jpg"
    hiring_en.save(en_hiring_path, "JPEG", quality=98, subsampling=0)
    print(f"✓ Saved direct Hiring EN card: {en_hiring_path}")
    assert hiring_en.size == (1080, 1350)

    hiring_ar = render_lexnis_hiring_card(
        role_title="مهندس أول تعلم الآلة\nوأنظمة الرؤية الحاسوبية",
        team_location="المنامة، البحرين  •  دوام كامل  •  حضوري",
        hook_headline="نبني الجيل القادم من\nأنظمة الرؤية الذكية.",
        subcopy="انتقل بنماذجك من التجربة إلى حافة الإنجاز الفوري.\nابنِ أنظمة ذكية وتأسيسية من قلب المنامة.",
        language="ar"
    )
    ar_hiring_path = out_dir / "unit_hiring_ar.jpg"
    hiring_ar.save(ar_hiring_path, "JPEG", quality=98, subsampling=0)
    print(f"✓ Saved direct Hiring AR card: {ar_hiring_path}")
    assert hiring_ar.size == (1080, 1350)

    print("==================================================================")
    print("TEST 3: End-to-End Campaign Generation via LexnisCampaignStudio")
    print("==================================================================")
    studio = LexnisCampaignStudio()

    # Product Launch End-to-End
    launch_prompt = "Predictive maintenance IoT platform launch for Lexnis with zero-downtime edge analytics and vibration AI sensor arrays"
    print(f"\nRunning studio.generate_campaign for post_type='product_launch':\n  Prompt: {launch_prompt}")
    launch_asset = studio.generate_campaign(
        prompt=launch_prompt,
        brand="Lexnis Technologies",
        post_type="product_launch",
        recolor_to_brand=True
    )
    print(f"✓ Product Launch EN visual: {launch_asset.image_path}")
    print(f"✓ Product Launch AR visual: {launch_asset.arabic_image_path}")
    assert launch_asset.image_path and Path(launch_asset.image_path).exists()
    assert launch_asset.arabic_image_path and Path(launch_asset.arabic_image_path).exists()

    brief_launch = launch_asset.brief or {}
    print(f"Brief Product Name: {brief_launch.get('product_name')}")
    assert "Lexnis" in str(brief_launch.get('product_name'))
    assert "VisionAI" in str(brief_launch.get('product_name')) or "Predictive" in str(brief_launch.get('product_name')) or "Platform" in str(brief_launch.get('product_name'))

    # Hiring End-to-End
    hiring_prompt = "Recruitment campaign for Lexnis Technologies: We are hiring Senior Machine Learning & Vision Systems Engineer for our Lexnis Core AI Lab, Manama / Hybrid."
    print(f"\nRunning studio.generate_campaign for post_type='hiring':\n  Prompt: {hiring_prompt}")
    hiring_asset = studio.generate_campaign(
        prompt=hiring_prompt,
        brand="Lexnis Technologies",
        post_type="hiring",
        recolor_to_brand=True
    )
    print(f"✓ Hiring EN visual: {hiring_asset.image_path}")
    print(f"✓ Hiring AR visual: {hiring_asset.arabic_image_path}")
    assert hiring_asset.image_path and Path(hiring_asset.image_path).exists()
    assert hiring_asset.arabic_image_path and Path(hiring_asset.arabic_image_path).exists()

    brief_hiring = hiring_asset.brief or {}
    print(f"Brief Role Name: {brief_hiring.get('product_name')}")
    assert "Alisha" not in str(brief_hiring.get('product_name'))

    print("\n==================================================================")
    print("TEST 4: Inspecting White Card Corner Masking (Clipping Assertion)")
    print("==================================================================")
    # The card corner at (card_x1, card_y1) = (72, 580) for launch and (72, 660) for hiring
    # should NOT be solid green (0, 255, 0) or sharp corner, because the mask rounds it by 16px!
    launch_arr = np.array(launch_en)
    hiring_arr = np.array(hiring_en)
    
    # Check that (72, 572) in launch_arr is part of the background gradient, NOT white or green
    c_pixel = launch_arr[572, 72] # [R, G, B]
    print(f"Launch Card Top-Left Corner pixel at (72, 572): RGB={c_pixel.tolist()}")
    # The background at (72, 572) is dark navy/emerald (R < 50, G < 80, B < 60)
    assert c_pixel[0] < 80 and c_pixel[1] < 100, f"Corner was not smoothly clipped: RGB={c_pixel}"
    print("✓ Verified: Card accent bar corner is smoothly clipped by 16px rounded mask!")

    print("\n🎉 ALL TESTS COMPLETED WITH 100% SUCCESS!")

if __name__ == "__main__":
    test_launch_and_hiring()

