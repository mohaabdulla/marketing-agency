"""Explicit single-model download; never imported or run during application startup."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agency.local_text import MODEL,CACHE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true')
    parser.add_argument('--accept-license',action='store_true')
    args=parser.parse_args()
    if not args.download:
        parser.print_help();return
    if not args.accept_license:
        raise SystemExit('Review the Qwen3-4B-GGUF Apache-2.0 model license and pass --accept-license')
    CACHE.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(CACHE).free<4*1024**3:
        raise SystemExit('Free at least 4 GiB before this explicit 2.5 GB model download')
    from huggingface_hub import HfApi,hf_hub_download
    info=HfApi().model_info(MODEL['source'],files_metadata=True)
    entry=next(x for x in info.siblings if x.rfilename==MODEL['filename'])
    path=Path(hf_hub_download(MODEL['source'],MODEL['filename'],revision=info.sha,local_dir=CACHE))
    if path.stat().st_size!=entry.size:
        raise SystemExit('Downloaded weight size does not match repository metadata')
    digest=hashlib.sha256()
    with path.open('rb') as f:
        if f.read(4)!=b'GGUF':raise SystemExit('Downloaded file is not GGUF')
        f.seek(0)
        while chunk:=f.read(1024**2):digest.update(chunk)
    for name in ['README.md','LICENSE']:
        if any(x.rfilename==name for x in info.siblings):
            hf_hub_download(MODEL['source'],name,revision=info.sha,local_dir=CACHE)
    manifest=dict(model_id=MODEL['id'],source=MODEL['source'],revision=info.sha,filename=MODEL['filename'],
                  size=path.stat().st_size,sha256=digest.hexdigest(),license=MODEL['license'])
    temp=CACHE/'installation.tmp'
    temp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    temp.replace(CACHE/'installation.json')
    (CACHE/'verification.json').unlink(missing_ok=True)
    print('Weights installed; inference is NOT yet verified. Start a CPU llama.cpp server, then run verify_local_text.py.')


if __name__=='__main__':main()
