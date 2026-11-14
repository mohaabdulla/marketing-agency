"""Fixed local font registry; callers never supply filesystem font paths."""
from pathlib import Path

FONTS = {
    'Arial': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf'],
    'Inter': ['C:/Windows/Fonts/Inter-Regular.ttf', '/usr/share/fonts/truetype/inter/Inter-Regular.ttf'],
    'Montserrat': ['C:/Windows/Fonts/Montserrat-Regular.ttf', '/usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf'],
    'Cairo': ['C:/Windows/Fonts/Cairo-Regular.ttf', '/usr/share/fonts/truetype/cairo/Cairo-Regular.ttf'],
    'DejaVu Sans': ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
    'Times New Roman': ['C:/Windows/Fonts/times.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'],
}


def path(name):
    return next((p for key, values in FONTS.items() if key.casefold() == (name or '').casefold()
                 for p in values if Path(p).is_file()), None)


def choose(preferences):
    for name in preferences:
        if path(name):
            return name, []
    fallback = next((name for name in ('Arial', 'DejaVu Sans') if path(name)), '')
    return fallback, ([f'Preferred fonts unavailable: {", ".join(preferences)}. Actual fallback: {fallback or "none"}.'] if preferences else [])
