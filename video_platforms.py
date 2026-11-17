"""Platform safe-zone profiles (versioned configuration) and style profiles.

Safe zones come from video_safe_zones.json. They are product defaults, labelled as such
everywhere they are reported; they are not official platform specifications.
Style profiles turn subjective words into explicit, editable editing parameters.
"""
import json
import re
from pathlib import Path

CONFIG = Path(__file__).with_name('video_safe_zones.json')


def config():
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def profile(name):
    data = config()
    key = name if name in data['profiles'] else 'generic-vertical'
    entry = data['profiles'][key]
    notice = entry.get('source') or data['notice']
    return dict(entry, id=key, basis=entry.get('basis', data['basis']), version=data['version'], notice=notice)


def choose(instruction, width, height, language='en'):
    """Pick a profile from the platform named in the brief, else a generic one for the aspect."""
    text = (instruction or '').lower()
    vertical = height >= width
    if 'tiktok' in text and vertical:
        return 'tiktok-rtl' if language.startswith('ar') else 'tiktok-ltr'
    paid = re.search(r'\b(?:ads?|advert\w*|paid|sponsored|boosted|promoted)\b', text)
    if paid and vertical and re.search(r'instagram|facebook|\bmeta\b|reels?\b', text):
        return 'meta-reels-ads'
    if re.search(r'\bstor(y|ies)\b', text) and vertical:
        return 'instagram-stories'
    if re.search(r'instagram|reels?\b', text) and vertical:
        return 'instagram-reels'
    if 'shorts' in text and vertical:
        return 'youtube-shorts'
    if 'youtube' in text:
        return 'youtube-shorts' if vertical else 'youtube-standard'
    return 'generic-vertical' if vertical else 'generic-horizontal'


def safe_area(spec, width, height):
    """(left, top, right, bottom) in pixels of the area the app interface does not cover."""
    return (round(width * spec['left']), round(height * spec['top']), round(width * (1 - spec['right'])), round(height * (1 - spec['bottom'])))


def outside_share(box, spec, width, height):
    """Share of an element's area that falls outside the profile's safe area (0..1)."""
    left, top, right, bottom = safe_area(spec, width, height)
    x0, y0, x1, y1 = box
    area = max(1, (x1 - x0) * (y1 - y0))
    inside = max(0, min(x1, right) - max(x0, left)) * max(0, min(y1, bottom) - max(y0, top))
    return round(1 - inside / area, 4)


def caption_center(spec, block_height_share=0.13):
    """Vertical centre (fraction of height) that keeps a caption block just above the bottom obstruction."""
    return round(max(0.5, 1 - spec['bottom'] - block_height_share / 2 - 0.015), 4)


def public():
    data = config()
    return dict(version=data['version'], basis=data['basis'], notice=data['notice'], reviewed=data['reviewed'],
                profiles=[dict(id=key, **value) for key, value in data['profiles'].items()])


# ---------------------------------------------------------------- style profiles
STYLES = {
    'organic': dict(label='Organic', pause_threshold=0.9, max_emphasis=1, punch_in=1.04, grade_strength=0.6, summary=[
        'natural pacing: only long dead pauses are tightened', 'at most one emphasis punch-in', 'gentle lighting correction', 'clean captions, small logo']),
    'polished-organic': dict(label='Polished organic', pause_threshold=0.65, max_emphasis=2, punch_in=1.06, grade_strength=1.0, summary=[
        'natural pacing with dead pauses tightened', 'up to two emphasis punch-ins', 'measured lighting correction', 'clean captions, small logo, no flashy transitions']),
    'high-energy': dict(label='High-energy social', pause_threshold=0.45, max_emphasis=4, punch_in=1.1, grade_strength=1.0, summary=[
        'shorter pauses', 'up to four emphasis punch-ins at a larger scale', 'measured lighting correction', 'clean cuts, no dissolves']),
    'brand-forward': dict(label='Brand forward', pause_threshold=0.65, max_emphasis=2, punch_in=1.06, grade_strength=1.0, summary=[
        'natural pacing with dead pauses tightened', 'up to two emphasis punch-ins', 'measured lighting correction', 'brand logo and call to action kept prominent']),
}


def interpret_style(text):
    """Map subjective words to a style profile. The result is an interpretation, shown and editable."""
    lowered = (text or '').lower()
    words = lambda *options: [w for w in options if re.search(r'\b' + w, lowered)]
    energetic = words('energetic', 'high energy', 'high-energy', 'fast', 'dynamic', 'punchy')
    brand = words('brand forward', 'brand-forward', 'corporate', 'promotional')
    polished = words('professional', 'polished', 'premium', 'clean', 'editorial')
    organic = words('organic', 'casual', 'natural', 'authentic', 'candid')
    if energetic:
        return 'high-energy', energetic
    if brand:
        return 'brand-forward', brand
    if organic and not polished:
        return 'organic', organic
    return 'polished-organic', polished + organic
