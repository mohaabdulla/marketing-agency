"""Explicit, opt-in downloads. No invocation from application startup."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_models import MODELS, CACHE, PYTHON
from video_storage import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', action='store_true', help='Create .venv-video and install CUDA 12.4 PyTorch (multi-GB)')
    parser.add_argument('--model', choices=MODELS)
    parser.add_argument('--accept-license', action='store_true')
    args = parser.parse_args()
    if args.runtime:
        if shutil.disk_usage(ROOT).free < 8*1024**3:
            raise SystemExit('Free at least 8 GB before installing the isolated runtime')
        venv.create(ROOT/'.venv-video', with_pip=True)
        subprocess.run([str(PYTHON),'-m','pip','install','torch==2.6.0','torchvision==0.21.0',
                        '--index-url','https://download.pytorch.org/whl/cu124'],check=True)
        subprocess.run([str(PYTHON),'-m','pip','install','-r',str(ROOT/'requirements-video.txt')],check=True)
    if args.model:
        if not args.accept_license:
            raise SystemExit('Review the model card and Apache-2.0 license, then pass --accept-license explicitly')
        if not PYTHON.is_file():
            raise SystemExit('Install --runtime first')
        config = MODELS[args.model]
        if shutil.disk_usage(ROOT).free < config['disk_gb']*1024**3:
            raise SystemExit(f"Free at least {config['disk_gb']} GB before this model download")
        # Resolve a specific commit, record exact downloaded sizes and retain the model license.
        from huggingface_hub import HfApi, snapshot_download
        info = HfApi().model_info(config['repo'], files_metadata=True)
        target = CACHE/args.model
        (target/'smoke-test.json').unlink(missing_ok=True)
        snapshot_download(config['repo'], revision=info.sha, local_dir=target,
                          allow_patterns=['model_index.json','scheduler/*','tokenizer/*','text_encoder/*','transformer/*','vae/*',
                                          'image_encoder/*','image_processor/*','README.md','LICENSE*','*.license.txt'],
                          ignore_patterns=['*.bin','*.onnx','*.msgpack'])
        manifest = dict(repo=config['repo'],revision=info.sha,license=config['license'],
                        files={str(p.relative_to(target)):p.stat().st_size for p in target.rglob('*') if p.is_file() and '.cache' not in p.parts})
        (target/'installation.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print('Installed weights. Run the opt-in verification script before production use.')
    if not args.runtime and not args.model:
        parser.print_help()


if __name__ == '__main__':
    main()
