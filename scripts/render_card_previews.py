"""Regenerate the four bilingual card previews without campaign/network calls."""
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from visual_engine import render_lexnis_hiring_card, render_welcome_template_swap


def main():
    assets = ROOT / "static" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # Match the portrait crop used in the welcome regression suite.
    subject = Image.open(ROOT / "test_assets" / "raw_subject.jpg").convert("RGB")
    width = int(subject.height * 0.75)
    left = (subject.width - width) // 2
    subject = subject.crop((left, 0, left + width, subject.height))
    buf = io.BytesIO()
    subject.save(buf, "JPEG", quality=95)
    for lang in ("en", "ar"):
        welcome = render_welcome_template_swap(
            buf.getvalue(), name="Mohamed Redha", role="AI Engineer",
            headline="أهلاً بك في فريقنا" if lang == "ar" else "WELCOME TO THE TEAM",
            brand_name="Lexnis Technologies", lang=lang)
        welcome.convert("RGB").save(assets / f"api_swap_{lang}.jpg", quality=95, subsampling=0)
        hiring = render_lexnis_hiring_card(
            role_title="مهندس أول تعلم الآلة\nوأنظمة الرؤية الحاسوبية" if lang == "ar" else "Senior Machine Learning &\nVision Systems Engineer",
            hook_headline="نبني الجيل القادم من\nأنظمة الرؤية الذكية." if lang == "ar" else "BUILD AUTONOMOUS\nVISION SYSTEMS.",
            subcopy="ابنِ أنظمة الذكاء الاصطناعي الطرفية من قلب المنامة." if lang == "ar" else "Stop maintaining legacy pipelines. Build foundational edge-AI instead.",
            language=lang)
        hiring.save(assets / f"lexnis_hiring_{lang}.jpg", quality=95, subsampling=0)
        print(f"Rendered welcome and hiring previews: {lang}")


if __name__ == "__main__":
    main()
