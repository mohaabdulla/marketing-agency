"""A review contact sheet; source model outputs remain untouched."""
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campaign_generator import _load_font

if __name__ == '__main__':
    figures = [
        ('BEFORE: VEGA', ROOT / 'output/renders/e1ef17adf5c8ca31_post_5157c86a.jpg'),
        ('AFTER: REALVISXL + DETAIL PASS', ROOT / 'output/tesla_realism_ad.jpg'),
    ]
    sheet = Image.new('RGB', (1920, 600), '#0c1017')
    draw = ImageDraw.Draw(sheet)
    for index, (title, path) in enumerate(figures):
        with Image.open(path) as source:
            image = ImageOps.contain(source.convert('RGB'), (948, 534), method=Image.Resampling.LANCZOS)
        x = index * 960 + 6
        draw.text((x + 14, 13), title, fill='white', font=_load_font(25))
        sheet.paste(image, (x, 58))
    target = ROOT / 'output/tesla_realism_comparison.jpg'
    sheet.save(target, quality=95)
    print(target)
