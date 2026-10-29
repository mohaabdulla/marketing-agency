"""Verify a real local render before marking the engine ready for the dashboard."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    from PIL import Image, ImageStat
    from visual_engine import local_image, LOCAL_WEIGHTS, compose_ad

    prompt = ('Advertising photograph of a deep blue Tesla Model 3 sedan driving on a winding '
              'California coastal road, ocean and cliffs, warm golden sunset, front three quarter '
              'tracking shot, entire car visible, realistic reflections, wheels on asphalt, '
              'natural light, 35mm lens, sharp focus, quiet sky and foreground for typography.')
    print('Generating a real Tesla campaign image on the local GPU...', flush=True)
    data, _ = local_image(prompt, 42, 1536, 864, require_ready=False)
    image = Image.open(io.BytesIO(data)).convert('RGB')
    assert image.width >= 768 and max(ImageStat.Stat(image).stddev) > 8, 'Unexpected blank/invalid output'
    clean = ROOT / 'output' / 'tesla_local_clean.jpg'
    image.save(clean, quality=95)
    post = ROOT / 'output' / 'tesla_local_ad.jpg'
    compose_ad(image, 'TESLA MODEL 3', 'TESLA', 'ACCELERATE THE FUTURE.').save(post, quality=95)
    (LOCAL_WEIGHTS / '.ready').write_text(json.dumps({'model': 'segmind/Segmind-Vega', 'verified_image': str(post)}), encoding='utf-8')
    print('Verified local engine. Sample:', post, flush=True)
