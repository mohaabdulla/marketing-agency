"""Atomic, validated local client-brand storage."""
import json
import threading
from pathlib import Path

from public_access import scoped
STORE = scoped(Path(__file__).resolve().parent / "static/assets/brand_kits.json", 'brands.json')
LOCK = threading.RLock()


def list_brands():
    with LOCK:
        return json.loads(STORE.read_text(encoding="utf-8")) if STORE.is_file() else []


def get_brand(brand_id):
    return next((item for item in list_brands() if item["id"] == brand_id), None)


def write_brands(brands):
    with LOCK:
        STORE.parent.mkdir(parents=True,exist_ok=True)
        temporary = STORE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(brands, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STORE)


def profile_for(brand):
    return dict(source="client_brand_kit", brand_name=brand["brand_name"], brand_name_ar=brand.get("brand_name_ar", ""),
                brand_colors={"primary": brand["primary_hex"], "accent": brand["accent_hex"]},
                brand_tag=brand.get("hashtag", ""), tagline=brand.get("tagline", ""),tagline_ar=brand.get('tagline_ar',''))
