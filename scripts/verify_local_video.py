"""Opt-in REAL inference smoke test. A marker is written only after FFprobe validation."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_models import statuses, CACHE
from video_engine import Generate, generate, check_generate
from video_assets import ingest, path_for
from video_storage import uid
from video_ffmpeg import probe


class SmokeProgress:
    """CLI progress must not initialize/recover the running server's persistent queue."""
    def __init__(self):
        self.id=uid()

    def cancelled(self):
        return False

    def update(self,**status):
        print(json.dumps(status),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['cogvideox-2b','wan21-i2v-480p'])
    parser.add_argument('--image', type=Path, help='Local operator-controlled image for the Wan I2V smoke test')
    parser.add_argument('--run-inference', action='store_true')
    args=parser.parse_args()
    print(json.dumps(statuses(),indent=2))
    if not args.run_inference:
        print('No inference run. Pass --model and --run-inference to opt in.')
        return
    if not args.model:
        parser.error('--model is required for real inference')
    source=ingest(args.image,args.image.name)['id'] if args.image else None
    request=Generate(model=args.model,mode='image-to-video' if args.model.startswith('wan') else 'text-to-video',
                     prompt='A small toy robot waves its arm, realistic studio lighting, slow camera motion.',asset_id=source)
    check_generate(request)
    result=generate(request, SmokeProgress())
    metadata=probe(path_for(result['id']))
    assert metadata['video_codec']=='h264' and metadata['duration']>1
    manifest=json.loads((CACHE/args.model/'installation.json').read_text())
    marker=dict(model=args.model,revision=manifest['revision'],verified_at=time.time(),asset_id=result['id'],metadata=metadata)
    (CACHE/args.model/'smoke-test.json').write_text(json.dumps(marker,indent=2),encoding='utf-8')
    print(json.dumps(marker,indent=2))


if __name__=='__main__':
    main()
