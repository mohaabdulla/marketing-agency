"""Explicit, one-time install of the optional subject-matting checkpoint for Video Studio.

    python scripts/setup_video_matting.py                  # U-2-Net human segmentation, about 168 MB
    python scripts/setup_video_matting.py --model u2netp   # small model, about 5 MB

Downloads one ONNX checkpoint with rembg's own downloader (which verifies its checksum) into
.model-cache/video-matting, then runs a real inference to confirm it works. Nothing in the
application downloads a model by itself.

Licences: rembg is MIT; the U-2-Net checkpoints are published under Apache-2.0 by their
authors (github.com/xuebinqin/U-2-Net). Review them for your own use before installing.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from video_segmentation import MODEL_DIR, MODELS, model_file
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', choices=sorted(k for k in MODELS if k.startswith('u2net')), default='u2net_human_seg')
    args = parser.parse_args()
    try:
        import rembg
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise SystemExit(f'Install the runtime first: python -m pip install rembg onnxruntime  ({exc})')
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    os.environ['U2NET_HOME'] = str(MODEL_DIR)
    print(f'Model: {MODELS[args.model]["label"]} · {MODELS[args.model]["license"]} · about {MODELS[args.model]["disk_mb"]} MB')
    print('Destination folder:', MODEL_DIR)
    session = rembg.new_session(args.model)          # downloads and checksum-verifies only if the file is absent
    target = model_file(args.model)
    if not target:
        raise SystemExit('The checkpoint was not written to the expected location.')
    # Real inference on a synthetic figure: a dark "person" shape on a bright background.
    image = Image.new('RGB', (320, 480), (225, 225, 215))
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 60, 200, 150), fill=(150, 110, 90))
    draw.rectangle((90, 150, 230, 470), fill=(40, 50, 80))
    started = time.time()
    mask = np.array(rembg.remove(image, session=session, only_mask=True))
    seconds = time.time() - started
    if mask.shape != (480, 320):
        raise SystemExit('Unexpected mask shape from the matting model.')
    marker = dict(model=args.model, file=target.name, size_bytes=target.stat().st_size, license=MODELS[args.model]['license'],
                  runtime=f'rembg {getattr(rembg, "__version__", "?")}', verified_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                  inference_seconds=round(seconds, 2), verification='One real CPU inference on a synthetic test image succeeded.')
    (MODEL_DIR / (args.model + '.verified.json')).write_text(json.dumps(marker, indent=2), encoding='utf-8')
    print(json.dumps(marker, indent=2))
    print('Subject-aware background treatment is now available in Video Studio (restart is not required).')


if __name__ == '__main__':
    main()
