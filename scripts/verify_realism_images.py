"""Generate an inspectable photographic sample without activating an untested model."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    from PIL import Image, ImageStat
    from visual_engine import local_image, REALISM_MODEL, compose_ad

    prompt = ('Advertising photograph of a deep blue Tesla Model 3 sedan on a winding coastal '
              'road at golden sunset, ocean cliffs, low front three quarter tracking shot, '
              'realistic reflections, entire car visible, 35mm lens, no text, no watermark')
    print('Testing the photographic model and gentle detail pass on the RTX 4060...', flush=True)
    data, _ = local_image(prompt, 42, 1536, 864, require_ready=False, model=REALISM_MODEL)
    image = Image.open(io.BytesIO(data)).convert('RGB')
    assert image.size == (1536, 864), image.size
    assert max(ImageStat.Stat(image).stddev) > 8, 'Unexpected blank output'
    image.save(ROOT / 'output' / 'tesla_realism_clean.jpg', quality=95)
    compose_ad(image, 'TESLA MODEL 3', 'TESLA', 'ACCELERATE THE FUTURE.').save(ROOT / 'output' / 'tesla_realism_ad.jpg', quality=95)
    metadata = json.loads((ROOT / 'output' / 'latest-local-render.json').read_text(encoding='utf-8'))
    (ROOT / 'output' / 'tesla_realism_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('Sample ready for inspection: output/tesla_realism_ad.jpg', flush=True)
    if '--activate' in sys.argv:
        from visual_engine import RENDER_VERSION
        metadata.update(render_version=RENDER_VERSION, verified_image='output/tesla_realism_ad.jpg')
        (ROOT / '.model-cache' / 'realvisxl-v5' / '.ready').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print('Verified photographic engine activated as the automatic default.', flush=True)
