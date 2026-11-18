"""Fixed local font registry; callers never supply filesystem font paths."""
from pathlib import Path

FONT_ROOT=Path(__file__).resolve().parents[1]/'static/fonts'

FONTS = {
    'Arial': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf'],
    'Inter': [str(FONT_ROOT/'Inter-Regular.ttf'),'C:/Windows/Fonts/Inter-Regular.ttf', '/usr/share/fonts/truetype/inter/Inter-Regular.ttf'],
    'Montserrat': [str(FONT_ROOT/'Montserrat-Regular.ttf'),'C:/Windows/Fonts/Montserrat-Regular.ttf', '/usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf'],
    'Cairo': [str(FONT_ROOT/'Cairo-Regular.ttf'),'C:/Windows/Fonts/Cairo-Regular.ttf', '/usr/share/fonts/truetype/cairo/Cairo-Regular.ttf'],
    'Almarai': [str(FONT_ROOT/'Almarai-Regular.ttf'),'C:/Windows/Fonts/Almarai-Regular.ttf', '/usr/share/fonts/truetype/almarai/Almarai-Regular.ttf'],
    'DejaVu Sans': ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
    'Times New Roman': ['C:/Windows/Fonts/times.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'],
}


def path(name, weight='regular'):
    regular = next((p for key, values in FONTS.items() if key.casefold() == (name or '').casefold()
                    for p in values if Path(p).is_file()), None)
    if regular and weight == 'bold':
        bold = regular.replace('arial.ttf', 'arialbd.ttf').replace('times.ttf', 'timesbd.ttf').replace('-Regular.ttf', '-Bold.ttf').replace('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
        if Path(bold).is_file():
            return bold
    return regular


def choose(preferences):
    for name in preferences:
        if path(name):
            return name, []
    fallback = next((name for name in ('Arial', 'DejaVu Sans') if path(name)), '')
    return fallback, ([f'Preferred fonts unavailable: {", ".join(preferences)}. Actual fallback: {fallback or "none"}.'] if preferences else [])
