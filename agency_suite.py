"""Copywriting, format adaptations and complete, local campaign packaging."""
import io
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from visual_engine import (ROOT, BrandTheme, resolve_brand_theme, get_font, prepare_bidi_text,
                           draw_brand_header, _companion_text, render_depth_gradient)


def theme_for(data, theme=None):
    if isinstance(theme, BrandTheme):
        return theme
    return resolve_brand_theme(brand_profile=theme or {}, brand_name=data.get("brand_name", "Lexnis Technologies"),
                               post_type=data.get("post_type", "general"))


def generate_campaign_copy(req_data, brand_theme=None):
    theme = theme_for(req_data, brand_theme)
    ar = req_data.get("language") == "ar"
    kind = str(req_data.get("post_type", "general"))
    kind = "welcome" if "welcome" in kind else "launch" if "launch" in kind else "hiring" if "hiring" in kind else "general"
    brand = theme.brand_name
    brand_ar = req_data.get("brand_name_ar") or ("لكسنس تكنولوجيز" if theme.is_lexnis else brand)
    subject = " ".join(str(req_data.get("role_title") or req_data.get("topic") or req_data.get("prompt") or brand).split())[:180]
    if ar:
        from visual_engine import ARABIC_TITLES_MAP, transliterate_to_arabic
        subject = req_data.get("topic_ar") or ARABIC_TITLES_MAP.get(subject.lower(), subject)
        name = transliterate_to_arabic(req_data.get("person_name", ""))
        hooks = {"hiring": f"خطوتك المهنية القادمة تبدأ مع {brand_ar}.", "launch": f"من الفكرة إلى الواقع: جديد {brand_ar}.",
                 "welcome": f"أهلاً {name or 'بعضونا الجديد'} في فريق {brand_ar}!", "general": f"رؤية تتحول إلى أثر مع {brand_ar}."}
        defaults = {"hiring": ["اعمل على تحديات حقيقية ضمن فريق متعاون", "طوّر خبرتك من خلال التعلم وتبادل المعرفة", "ساهم في تحويل الأفكار إلى نتائج ملموسة"],
                    "launch": ["تعرّف إلى فكرة الإصدار وما يقدمه", "اكتشف الاستخدامات المناسبة لاحتياجات فريقك", "ناقش التفاصيل وخيارات التطبيق معنا"],
                    "welcome": ["خبرات جديدة تثري عمل الفريق", "تعاون يفتح المجال للتعلم والابتكار", "مهمة مشتركة نبنيها معاً"],
                    "general": ["نضع احتياجات العملاء في قلب العمل", "نحوّل التحديات إلى فرص للتطوير", "نبني شراكات قائمة على التعاون والوضوح"]}
        body = {"hiring": f"نبحث عن مواهب تنضم إلى رحلة {brand_ar}. مجال الفرصة: {subject}.",
                "launch": f"نشارككم الخطوة الجديدة في رحلتنا: {subject}. اكتشفوا القصة والتفاصيل مع فريقنا.",
                "welcome": f"يسعدنا انضمام {name or 'عضونا الجديد'} في مجال {subject}. نتطلع إلى الأفكار والإنجازات التي سنبنيها معاً.",
                "general": f"نشارككم رؤيتنا حول {subject}، وكيف نعمل معاً لصناعة قيمة مستدامة."}[kind]
        culture = "نؤمن بأن العمل المميز يبدأ بفريق يشارك المعرفة ويصنع الأثر معاً."
        cta = req_data.get("cta_ar") or {"hiring": "أرسل سيرتك الذاتية وتعرّف إلى الفرصة معنا.", "launch": "تواصل معنا لاكتشاف التفاصيل وطلب عرض توضيحي.",
                                         "welcome": "شاركونا الترحيب بعضونا الجديد!", "general": "شاركنا رأيك أو تواصل مع فريقنا."}[kind]
        industry = ["#تقنية", "#ابتكار", "#تطوير", "#فريق_العمل", "#تقنية_البحرين" if theme.is_lexnis else "#ريادة_الأعمال", "#حلول_رقمية", "#تعاون"]
        industry.append({"hiring": "#فرص_عمل", "launch": "#إطلاق_جديد", "welcome": "#ترحيب_بالفريق", "general": "#تسويق"}[kind])
        recommendation = "نافذة اختبار مقترحة: الثلاثاء الساعة 10 صباحاً بتوقيت الجمهور المحلي؛ قارن النتائج مع تحليلات حسابك. اجعل البطاقة الرئيسية الغلاف، ثم فيديو MP4 أو GIF، ثم البطاقة التفصيلية. انشر الفيديو منفصلاً إذا كانت المنصة لا تدعم مزج الصيغ."
    else:
        name = req_data.get("person_name", "")
        hooks = {"hiring": f"Your next chapter starts at {brand}.", "launch": f"From an idea to what's next. Meet the latest from {brand}.",
                 "welcome": f"Welcome {name or 'our newest teammate'} to {brand}!", "general": f"Ideas into impact, with {brand}."}
        defaults = {"hiring": ["Work on meaningful challenges with a collaborative team", "Develop your craft through shared learning", "Help turn strong ideas into practical outcomes"],
                    "launch": ["Explore the idea behind the release", "Discover how it fits your team's needs", "Discuss implementation and next steps with us"],
                    "welcome": ["Fresh perspectives that strengthen our team", "Room to learn, collaborate and contribute", "A shared mission we build together"],
                    "general": ["Start with real customer needs", "Turn challenges into opportunities to improve", "Build partnerships through collaboration and clarity"]}
        body = {"hiring": f"We're growing our team in {subject}. Bring your perspective, curiosity and experience to the work ahead.",
                "launch": f"Introducing {subject}. Discover the thinking behind the release and explore the details with our team.",
                "welcome": f"We're excited to welcome {name or 'our newest teammate'} in {subject}. Here's to the ideas and work we'll build together.",
                "general": f"A closer look at {subject}, and the work turning our shared ambition into practical progress."}[kind]
        culture = "Great work grows from people who share knowledge, take ownership and build together."
        cta = req_data.get("cta") or {"hiring": "Send your CV and explore the opportunity with us.", "launch": "Get in touch to explore the details or request a demo.",
                                     "welcome": "Join us in welcoming our newest teammate!", "general": "Share your perspective or start a conversation with our team."}[kind]
        industry = ["#Technology", "#Innovation", "#Engineering", "#Teamwork", "#BahrainTech" if theme.is_lexnis else "#Business", "#DigitalTransformation", "#Collaboration"]
        industry.append({"hiring": "#HiringBahrain" if theme.is_lexnis else "#Hiring", "launch": "#ProductLaunch", "welcome": "#TeamWelcome", "general": "#Marketing"}[kind])
        recommendation = "Suggested test window: Tuesday at 10:00 in your audience's local timezone; refine with your account analytics. Use the primary card as cover, motion as the second asset, and the detail card third. Publish video separately if the platform cannot mix these formats."
    focus = subject + " " + brand
    if re.search(r"\bai\b|vision|ذكاء|رؤية", subject, re.I):
        industry[:3] = ["#ذكاء_اصطناعي", "#رؤية_حاسوبية", "#ذكاء_طرفي"] if ar else ["#ArtificialIntelligence", "#ComputerVision", "#EdgeAI"]
    elif re.search(r"solar|renewable|شمس|طاقة", focus, re.I):
        industry[:3] = ["#طاقة_شمسية", "#طاقة_متجددة", "#تقنية_نظيفة"] if ar else ["#SolarEnergy", "#RenewableEnergy", "#CleanTech"]
    elif re.search(r"marketing|تسويق", subject, re.I):
        industry[:3] = ["#تسويق", "#استراتيجية_العلامة", "#تسويق_رقمي"] if ar else ["#Marketing", "#BrandStrategy", "#DigitalMarketing"]
    if theme.domain and kind != "welcome":
        cta += " https://" + theme.domain.rstrip("/") + ("/careers" if kind == "hiring" else "")
    supplied = req_data.get("key_points_ar" if ar else "key_points") or []
    if ar and not supplied:
        supplied = [p for p in req_data.get("key_points", []) if re.search(r"[\u0600-\u06ff]", str(p))]
    if isinstance(supplied, str):
        supplied = [p.strip(" •-") for p in supplied.splitlines() if p.strip()]
    points = [str(p) for p in supplied[:3]] + defaults[kind][len(supplied[:3]):]
    brand_tag = "#" + (re.sub(r"\W+", "", brand_ar if ar else brand, flags=re.UNICODE) or "Brand")
    configured_tag = theme.hashtag_ar if ar else theme.hashtag_en
    tags = list(dict.fromkeys([brand_tag, *([configured_tag] if configured_tag else []), *industry]))[:10]
    hook = hooks[kind]
    instagram = f"{hook}\n\n{body}\n\n{cta}\n\n" + "\n".join(tags)
    x = f"{hook} {subject}. {cta} {brand_tag}"
    if len(x) >= 280:
        x = x[:276].rstrip() + "…"
    return dict(language="ar" if ar else "en", hook=hook, linkedin_post=f"{hook}\n\n{body}\n\n" + "\n".join(f"• {p}" for p in points) + f"\n\n{culture}\n\n{cta}",
                instagram_caption=instagram, x_post=x, hashtags=tags, cta=cta,
                posting_recommendation=recommendation,
                strategy_source="https://www.linkedin.com/business/marketing/blog/linkedin-ads/whats-the-best-time-to-post-on-linkedin")


def _wrapped(draw, text, bounds, lang, size=42, max_lines=3):
    x, y, width, height = bounds
    for sz in range(size, 15, -1):
        font = get_font("Cairo" if lang == "ar" else "Montserrat", sz, weight="bold")
        lines, current = [], ""
        for word in str(text).split():
            test = (current + " " + word).strip()
            if draw.textlength(prepare_bidi_text(test), font=font) <= width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= max_lines and len(lines)*sz*1.5 <= height:
            break
    for index, line in enumerate(lines[:max_lines]):
        _companion_text(draw, line, (x, y+index*sz*1.5, width, sz*1.5), size=sz, lang=lang, weight="bold")


def render_omnichannel_variants(primary_card_path, req_data, brand_theme=None):
    theme = theme_for(req_data, brand_theme)
    lang = req_data.get("language", "en")
    primary = Path(primary_card_path)
    with Image.open(primary) as source:
        card = ImageOps.fit(source.convert("RGB"), (1080, 1350))
    from visual_engine import rgb_to_hex
    import cv2
    story = Image.fromarray(cv2.cvtColor(render_depth_gradient(1080, 1920, rgb_to_hex(theme.bg_dark_start), rgb_to_hex(theme.bg_dark_end)), cv2.COLOR_BGR2RGB)).convert("RGBA")
    header = Image.new("RGBA", (1080, 180))
    draw_brand_header(header, theme, is_ar=lang == "ar", custom_logo=req_data.get("logo_image"))
    story.alpha_composite(header, (0, 72))
    # Remove the repeated header and kit badge, preserving the whole employee/card.
    story.paste(card.crop((0, 130, 1080, 1305)), (0, 330))
    sd = ImageDraw.Draw(story)
    sd.rounded_rectangle((170, 1740, 910, 1820), radius=40, fill=theme.primary_accent)
    _companion_text(sd, "اسحب للأعلى / الرابط في النبذة" if lang == "ar" else "SWIPE UP / LINK IN BIO",
                    (210, 1756, 660, 48), lang=lang, size=28, weight="semibold", fill=theme.bg_dark_start)
    story_path = primary.with_name(primary.stem + "_story.jpg")
    story.convert("RGB").save(story_path, quality=95, subsampling=0)

    banner = Image.new("RGB", (1200, 628), theme.bg_dark_start)
    banner.paste(header.crop((72, 55, 410, 125)), (60, 55), header.crop((72, 55, 410, 125)))
    bd = ImageDraw.Draw(banner)
    title = (req_data.get("headline_ar") or generate_campaign_copy(req_data, theme)["hook"]) if lang == "ar" else req_data.get("headline") or req_data.get("role_title") or req_data.get("topic") or theme.brand_name
    _wrapped(bd, title, (60, 180, 570, 205), lang)
    _wrapped(bd, req_data.get("tagline") or ("من الرؤية إلى أثر ملموس" if lang == "ar" else "From vision to meaningful impact."), (60, 396, 570, 65), lang, 22, 2)
    bd.rounded_rectangle((60, 490, 630, 560), radius=20, fill=theme.primary_accent)
    kind = str(req_data.get("post_type", "general"))
    default_cta = ("قدّم طلبك" if lang == "ar" else "APPLY NOW") if "hiring" in kind else ("اطلب عرضاً توضيحياً" if lang == "ar" else "REQUEST A DEMO") if "launch" in kind else ("سعداء بانضمامك" if lang == "ar" else "WELCOME ABOARD") if "welcome" in kind else ("تواصل معنا" if lang == "ar" else "LET'S BUILD TOGETHER")
    cta = req_data.get("cta_ar" if lang == "ar" else "cta") or default_cta
    _companion_text(bd, cta, (84, 502, 522, 45), size=25, lang=lang, weight="semibold", fill=theme.bg_dark_start)
    if "welcome" in str(req_data.get("post_type", "")):
        visual = card.crop((180, 220, 900, 1118))
    else:
        companion = req_data.get("companion_image_path")
        if companion and Path(companion).is_file():
            with Image.open(companion) as image:
                visual = image.convert("RGB").crop((72, 230, 1008, 995))
        else:
            visual = card.crop((72, 240, 1008, 1000))
    visual = ImageOps.contain(visual, (460, 510), Image.Resampling.LANCZOS)
    banner.paste(visual, (680+(460-visual.width)//2, 59+(510-visual.height)//2))
    landscape_path = primary.with_name(primary.stem + "_landscape.jpg")
    banner.save(landscape_path, quality=95, subsampling=0)
    public_prefix = "/static/assets" if primary.resolve().parent == (ROOT/"static/assets").resolve() else "/renders"
    return dict(story_path=str(story_path), landscape_path=str(landscape_path),
                story_url=f"{public_prefix}/{story_path.name}", landscape_url=f"{public_prefix}/{landscape_path.name}")


def export_animation_mp4(gif_path):
    output = Path(gif_path).with_suffix(".mp4")
    executable = shutil.which("ffmpeg")
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            return ""
    try:
        result = subprocess.run([executable, "-y", "-loglevel", "error", "-i", str(gif_path), "-vf", "fps=24",
                                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                                 "-movflags", "+faststart", str(output)], capture_output=True, timeout=90,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            return str(output)
    except (OSError, subprocess.TimeoutExpired):
        pass
    output.unlink(missing_ok=True)
    return ""


def bundle_campaign(paths, copywriting, output_path):
    names = {"image_url": "01_primary_feed_1080x1350.jpg", "companion_image_url": "02_companion_feed_1080x1350.jpg",
             "animation_url": "03_animated_companion.gif", "animation_mp4_url": "03_animated_companion.mp4",
             "story_url": "04_story_9x16_1080x1920.jpg", "landscape_url": "05_landscape_1200x628.jpg"}
    required = set(names)-{"animation_mp4_url"}
    if any(not paths.get(k) or not Path(paths[k]).is_file() for k in required):
        raise ValueError("The campaign kit is missing one or more required deliverables.")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = "\n\n".join(f"{key.upper()}\n" + (" ".join(value) if isinstance(value, list) else str(value)) for key, value in copywriting.items())
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for key, name in names.items():
            if paths.get(key):
                archive.write(paths[key], name)
        archive.writestr("campaign_copy_and_strategy.txt", document.encode("utf-8"))
    return str(output)
