import os
import sys
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from visual_engine import render_lexnis_hiring_card

def run_agency_hiring_test():
    out_dir = BASE_DIR / "output" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Generating Agency Art Director EN Master via visual_engine.render_lexnis_hiring_card...")
    en_img = render_lexnis_hiring_card(
        role_title="Senior Machine Learning &\nVision Systems Engineer",
        team_location="Manama, Bahrain  •  Full-Time  •  On-Site",
        hook_headline="BUILD AUTONOMOUS\nVISION SYSTEMS.",
        subcopy="Stop building theoretical models that die in legacy corporate approval queues.",
        language="en"
    )
    en_path = out_dir / "agency_hiring_en_test.jpg"
    en_img.save(en_path, quality=95)
    print(f"✓ Saved EN to {en_path}")

    print("Generating Agency Art Director AR Master via visual_engine.render_lexnis_hiring_card...")
    ar_img = render_lexnis_hiring_card(
        role_title="مهندس أول تعلم الآلة\nوأنظمة الرؤية الحاسوبية",
        team_location="المنامة، البحرين  •  دوام كامل  •  حضوري",
        hook_headline="نبني الجيل القادم من\nأنظمة الرؤية الذكية.",
        subcopy="انتقل بنماذجك من التجربة إلى حافة الإنجاز الفوري.\nابنِ أنظمة ذكية وتأسيسية من قلب المنامة.",
        language="ar"
    )
    ar_path = out_dir / "agency_hiring_ar_test.jpg"
    ar_img.save(ar_path, quality=95)
    print(f"✓ Saved AR to {ar_path}")

    # Micro-refinement assertions
    # 1. Verify canvas sizes
    assert en_img.size == (1080, 1350), f"EN size mismatch: {en_img.size}"
    assert ar_img.size == (1080, 1350), f"AR size mismatch: {ar_img.size}"

    print("\n🎉 ALL AGENCY ART DIRECTOR TESTS PASSED!")

if __name__ == "__main__":
    run_agency_hiring_test()
