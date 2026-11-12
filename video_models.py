"""Local-only model registry. Availability never implies a successful smoke test."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from video_storage import ROOT

CACHE = ROOT / '.model-cache/video'
PYTHON = ROOT / '.venv-video' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
MODELS = {
    'cogvideox-2b': dict(repo='zai-org/CogVideoX-2b', modes=['text-to-video'], license='Apache-2.0',
        width=720, height=480, frames=49, fps=8, vram_gb=6, ram_gb=24, disk_gb=30,
        note='FP16 sequential CPU offload, VAE slicing/tiling. 6.125 seconds. Laptop memory use unverified.'),
    'wan21-i2v-480p': dict(repo='Wan-AI/Wan2.1-I2V-14B-480P-Diffusers', modes=['image-to-video'], license='Apache-2.0',
        width=832, height=480, frames=81, fps=16, vram_gb=24, ram_gb=48, disk_gb=110,
        note='Separate image-conditioned model. Conservative hardware gates; not suitable for an 8 GB GPU.'),
}
_runtime_cache = (0, {})


def runtime_status():
    global _runtime_cache
    if not PYTHON.is_file():
        return dict(cuda=False, error='Video environment is not installed')
    if time.monotonic() - _runtime_cache[0] < 60:
        return _runtime_cache[1]
    code = "import json,torch,diffusers;print(json.dumps(dict(cuda=torch.cuda.is_available(),bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,torch=torch.__version__,diffusers=diffusers.__version__)))"
    try:
        process = subprocess.run([str(PYTHON), '-c', code], capture_output=True, text=True, timeout=25,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        value = json.loads(process.stdout.strip().splitlines()[-1]) if process.returncode == 0 else dict(cuda=False,error='Video runtime dependencies failed to load')
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        value = dict(cuda=False,error='Video runtime inspection failed')
    _runtime_cache = (time.monotonic(), value)
    return value


def hardware():
    gpu = None
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        row = result.stdout.strip().splitlines()[0].split(',')
        gpu = dict(name=row[0].strip(), total_gb=round(float(row[1])/1024, 2), free_gb=round(float(row[2])/1024, 2))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        pass
    try:
        import psutil
        ram = psutil.virtual_memory().total / 1024**3
    except ImportError:
        ram = 0
    return dict(gpu=gpu, ram_gb=round(ram, 1), disk_free_gb=round(shutil.disk_usage(ROOT).free/1024**3, 1),
                runtime_installed=PYTHON.is_file())


def statuses():
    hw = hardware()
    runtime = runtime_status()
    results = []
    for key, config in MODELS.items():
        installed = (CACHE / key / 'model_index.json').is_file() and (CACHE / key / 'installation.json').is_file()
        reasons = []
        if not hw['runtime_installed']:
            reasons.append('Video environment is not installed')
        elif not runtime.get('cuda'):
            reasons.append(runtime.get('error', 'CUDA unavailable in the video environment'))
        if key.startswith('wan') and runtime.get('cuda') and not runtime.get('bf16'):
            reasons.append('Wan adapter requires CUDA bfloat16 support')
        if not installed:
            reasons.append('Model weights are not installed')
        if not hw['gpu'] or hw['gpu']['total_gb'] < config['vram_gb']:
            reasons.append(f"Requires at least {config['vram_gb']} GB NVIDIA VRAM")
        if hw['ram_gb'] < config['ram_gb']:
            reasons.append(f"Requires at least {config['ram_gb']} GB system RAM for this offload configuration")
        if hw['disk_free_gb'] < 2:
            reasons.append('Requires at least 2 GB free working disk')
        verified = False
        try:
            marker = json.loads((CACHE/key/'smoke-test.json').read_text())
            manifest = json.loads((CACHE/key/'installation.json').read_text())
            verified = marker['revision'] == manifest['revision'] and marker['model'] == key
        except (OSError, ValueError, KeyError):
            pass
        results.append(dict(id=key, **config, installed=installed, available=not reasons, reasons=reasons, verified=verified))
    return results
