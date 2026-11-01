"""Download the free RealVisXL checkpoint into the isolated local image engine."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-image' / 'Scripts' / 'python.exe'

if __name__ == '__main__':
    code = '''
from huggingface_hub import HfApi, snapshot_download
repo = 'SG161222/RealVisXL_V5.0'
api = HfApi()
info = api.model_info(repo, files_metadata=True)
files = [f.rfilename for f in info.siblings]
revision = 'main'
variant = any('.fp16.safetensors' in name for name in files)
if not variant:
    refs = api.list_repo_refs(repo)
    if any(branch.name == 'fp16' for branch in refs.branches):
        revision = 'fp16'
        info = api.model_info(repo, revision=revision, files_metadata=True)
        files = [f.rfilename for f in info.siblings]
        variant = any('.fp16.safetensors' in name for name in files)
suffix = '.fp16.safetensors' if variant else '.safetensors'
selected = [name for name in files if name.endswith(('.json', '.txt', '.model', '.md'))
    or ('/' in name and name.endswith(suffix))]
print('Checkpoint revision:', revision, 'fp16 variant:', variant, flush=True)
print('Weight download GB:', round(sum(f.size or 0 for f in info.siblings if f.rfilename in selected)/1e9, 2), flush=True)
snapshot_download(repo, revision=revision, local_dir='.model-cache/realvisxl-v5', allow_patterns=selected)
import json
from pathlib import Path
Path('.model-cache/realvisxl-v5/.download.json').write_text(json.dumps({'repo': repo, 'revision': info.sha, 'variant': 'fp16' if variant else None}), encoding='utf-8')
print('RealVisXL model downloaded.', flush=True)
'''
    environment = dict(os.environ, HF_XET_CACHE=str(ROOT / '.model-cache' / 'xet-cache'))
    subprocess.run([str(PYTHON), '-c', code], cwd=ROOT, env=environment, check=True)
    import sys
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'shard_local_checkpoint.py')], cwd=ROOT, check=True)
