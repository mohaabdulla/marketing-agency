"""Local-only model registry and adapter architecture. Availability never implies a successful smoke test."""
import json
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from video_storage import ROOT

CACHE = ROOT / '.model-cache/video'
PYTHON = ROOT / '.venv-video' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


class ModelState(str, Enum):
    NOT_INSTALLED = 'not_installed'
    INSTALLED = 'installed'
    ENVIRONMENT_READY = 'environment_ready'
    HARDWARE_COMPATIBLE = 'hardware_compatible'
    SMOKE_VERIFIED = 'smoke_verified'
    PRODUCTION_VERIFIED = 'production_verified'


class VideoModelAdapter(ABC):
    """Abstract adapter defining the full lifecycle contract for local video models."""

    def __init__(self, model_id: str, config: dict):
        self.model_id = model_id
        self.config = config

    def metadata(self) -> dict:
        return dict(id=self.model_id, **self.config)

    def validate_environment(self, hw: dict, runtime: dict) -> list[str]:
        reasons = []
        if not hw.get('runtime_installed'):
            reasons.append('Video environment is not installed')
        elif not runtime.get('cuda'):
            reasons.append(runtime.get('error', 'CUDA unavailable in the video environment'))
        if not hw.get('gpu') or hw['gpu']['total_gb'] < self.config['vram_gb']:
            reasons.append(f"Requires at least {self.config['vram_gb']} GB NVIDIA VRAM")
        if hw.get('ram_gb', 0) < self.config['ram_gb']:
            reasons.append(f"Requires at least {self.config['ram_gb']} GB system RAM for this offload configuration")
        if hw.get('disk_free_gb', 0) < 2:
            reasons.append('Requires at least 2 GB free working disk')
        return reasons

    def validate_request(self, request: dict) -> None:
        mode = request.get('mode', 'text-to-video')
        if mode not in self.config.get('modes', []):
            raise ValueError(f"Model '{self.model_id}' does not support mode '{mode}'")

    @abstractmethod
    def build_pipeline(self, request: dict, torch_module, diffusers_module):
        """Construct isolated Diffusers pipeline with appropriate offloading and precision."""
        pass

    def unload(self, pipeline):
        """Cleanly tear down pipeline and release GPU/host memory."""
        try:
            import gc
            del pipeline
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except ImportError:
                pass
        except Exception:
            pass


class CogVideoXAdapter(VideoModelAdapter):
    """Adapter for CogVideoX-2B text-to-video diffusion."""

    def validate_request(self, request: dict) -> None:
        super().validate_request(request)
        if request.get('mode') != 'text-to-video':
            raise ValueError('CogVideoX-2B is text-only')

    def build_pipeline(self, request: dict, torch_module, diffusers_module):
        self.validate_request(request)
        model_path = request.get('model_path', str(CACHE / self.model_id))
        pipe = diffusers_module.CogVideoXPipeline.from_pretrained(
            model_path,
            torch_dtype=torch_module.float16,
            local_files_only=True,
            use_safetensors=True
        )
        pipe.enable_sequential_cpu_offload()
        if hasattr(pipe, 'vae') and hasattr(pipe.vae, 'enable_slicing'):
            pipe.vae.enable_slicing()
        if hasattr(pipe, 'vae') and hasattr(pipe.vae, 'enable_tiling'):
            pipe.vae.enable_tiling()
        return pipe


class Wan21I2VAdapter(VideoModelAdapter):
    """Adapter for Wan2.1-I2V-14B-480P image-to-video diffusion."""

    def validate_environment(self, hw: dict, runtime: dict) -> list[str]:
        reasons = super().validate_environment(hw, runtime)
        if runtime.get('cuda') and not runtime.get('bf16'):
            reasons.append('Wan adapter requires CUDA bfloat16 support')
        return reasons

    def validate_request(self, request: dict) -> None:
        super().validate_request(request)
        if request.get('mode') != 'image-to-video' or not request.get('image') and not request.get('asset_id'):
            raise ValueError('Wan I2V requires a starting image')

    def build_pipeline(self, request: dict, torch_module, diffusers_module):
        if request.get('mode') != 'image-to-video' or not request.get('image'):
            raise ValueError('Wan I2V requires a starting image')
        model_path = request.get('model_path', str(CACHE / self.model_id))
        vae = diffusers_module.AutoencoderKLWan.from_pretrained(
            model_path, subfolder='vae', torch_dtype=torch_module.float32, local_files_only=True
        )
        pipe = diffusers_module.WanImageToVideoPipeline.from_pretrained(
            model_path,
            vae=vae,
            torch_dtype=torch_module.bfloat16,
            local_files_only=True,
            use_safetensors=True
        )
        pipe.enable_sequential_cpu_offload()
        if hasattr(pipe, 'vae') and hasattr(pipe.vae, 'enable_slicing'):
            pipe.vae.enable_slicing()
        if hasattr(pipe, 'vae') and hasattr(pipe.vae, 'enable_tiling'):
            pipe.vae.enable_tiling()
        return pipe


class Wan21T2VAdapter(VideoModelAdapter):
    """Adapter for Wan2.1-T2V-14B-480P text-to-video diffusion."""

    def validate_environment(self, hw: dict, runtime: dict) -> list[str]:
        reasons = super().validate_environment(hw, runtime)
        if runtime.get('cuda') and not runtime.get('bf16'):
            reasons.append('Wan adapter requires CUDA bfloat16 support')
        return reasons

    def build_pipeline(self, request: dict, torch_module, diffusers_module):
        self.validate_request(request)
        model_path = request.get('model_path', str(CACHE / self.model_id))
        pipe = diffusers_module.WanPipeline.from_pretrained(
            model_path,
            torch_dtype=torch_module.bfloat16,
            local_files_only=True,
            use_safetensors=True
        )
        pipe.enable_sequential_cpu_offload()
        return pipe


class Wan22TI2VAdapter(VideoModelAdapter):
    """Adapter for Wan2.2-TI2V-5B dual-mode text and image video diffusion."""

    def validate_environment(self, hw: dict, runtime: dict) -> list[str]:
        reasons = super().validate_environment(hw, runtime)
        if runtime.get('cuda') and not runtime.get('bf16'):
            reasons.append('Wan adapter requires CUDA bfloat16 support')
        return reasons

    def build_pipeline(self, request: dict, torch_module, diffusers_module):
        self.validate_request(request)
        model_path = request.get('model_path', str(CACHE / self.model_id))
        if request.get('mode') == 'image-to-video':
            pipe = diffusers_module.WanImageToVideoPipeline.from_pretrained(
                model_path,
                torch_dtype=torch_module.bfloat16,
                local_files_only=True,
                use_safetensors=True
            )
        else:
            pipe = diffusers_module.WanPipeline.from_pretrained(
                model_path,
                torch_dtype=torch_module.bfloat16,
                local_files_only=True,
                use_safetensors=True
            )
        pipe.enable_sequential_cpu_offload()
        return pipe


MODELS = {
    'cogvideox-2b': dict(
        repo='zai-org/CogVideoX-2b',
        modes=['text-to-video'],
        license='Apache-2.0',
        width=720,
        height=480,
        frames=49,
        fps=8,
        vram_gb=6,
        ram_gb=24,
        disk_gb=30,
        note='FP16 sequential CPU offload, VAE slicing/tiling. 6.125 seconds. Laptop memory use unverified.'
    ),
    'wan21-i2v-480p': dict(
        repo='Wan-AI/Wan2.1-I2V-14B-480P-Diffusers',
        modes=['image-to-video'],
        license='Apache-2.0',
        width=832,
        height=480,
        frames=81,
        fps=16,
        vram_gb=24,
        ram_gb=48,
        disk_gb=110,
        note='Separate image-conditioned model. Conservative hardware gates; not suitable for an 8 GB GPU.'
    ),
    'wan21-t2v-480p': dict(
        repo='Wan-AI/Wan2.1-T2V-14B-480P-Diffusers',
        modes=['text-to-video'],
        license='Apache-2.0',
        width=832,
        height=480,
        frames=81,
        fps=16,
        vram_gb=24,
        ram_gb=48,
        disk_gb=110,
        note='Local Wan2.1 text-to-video 14B model with temporal cross-attention.'
    ),
    'wan22-ti2v-5b': dict(
        repo='Wan-AI/Wan2.2-TI2V-5B-Diffusers',
        modes=['text-to-video', 'image-to-video'],
        license='Apache-2.0',
        width=832,
        height=480,
        frames=81,
        fps=16,
        vram_gb=16,
        ram_gb=32,
        disk_gb=60,
        note='Dual-mode text and image conditioned 5B model for agile deployment.'
    ),
}

ADAPTERS = {
    'cogvideox-2b': CogVideoXAdapter('cogvideox-2b', MODELS['cogvideox-2b']),
    'wan21-i2v-480p': Wan21I2VAdapter('wan21-i2v-480p', MODELS['wan21-i2v-480p']),
    'wan21-t2v-480p': Wan21T2VAdapter('wan21-t2v-480p', MODELS['wan21-t2v-480p']),
    'wan22-ti2v-5b': Wan22TI2VAdapter('wan22-ti2v-5b', MODELS['wan22-ti2v-5b']),
}


def get_adapter(model_id: str) -> VideoModelAdapter | None:
    return ADAPTERS.get(model_id)


_runtime_cache = (0, {})


def runtime_status():
    global _runtime_cache
    if not PYTHON.is_file():
        return dict(cuda=False, error='Video environment is not installed')
    if time.monotonic() - _runtime_cache[0] < 60:
        return _runtime_cache[1]
    code = (
        "import json,torch,diffusers;"
        "print(json.dumps(dict("
        "cuda=torch.cuda.is_available(),"
        "bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,"
        "torch=torch.__version__,"
        "diffusers=diffusers.__version__"
        ")))"
    )
    try:
        process = subprocess.run(
            [str(PYTHON), '-c', code],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        value = (
            json.loads(process.stdout.strip().splitlines()[-1])
            if process.returncode == 0
            else dict(cuda=False, error='Video runtime dependencies failed to load')
        )
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        value = dict(cuda=False, error='Video runtime inspection failed')
    _runtime_cache = (time.monotonic(), value)
    return value


def hardware():
    gpu = None
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        row = result.stdout.strip().splitlines()[0].split(',')
        gpu = dict(name=row[0].strip(), total_gb=round(float(row[1]) / 1024, 2), free_gb=round(float(row[2]) / 1024, 2))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        pass
    try:
        import psutil
        ram = psutil.virtual_memory().total / 1024**3
    except ImportError:
        ram = 0
    return dict(
        gpu=gpu,
        ram_gb=round(ram, 1),
        disk_free_gb=round(shutil.disk_usage(ROOT).free / 1024**3, 1),
        runtime_installed=PYTHON.is_file()
    )


def statuses():
    hw = hardware()
    runtime = runtime_status()
    results = []
    for key, config in MODELS.items():
        adapter = ADAPTERS.get(key)
        installed = (CACHE / key / 'model_index.json').is_file() and (CACHE / key / 'installation.json').is_file()
        reasons = []

        if adapter:
            reasons.extend(adapter.validate_environment(hw, runtime))
        else:
            if not hw['runtime_installed']:
                reasons.append('Video environment is not installed')
            elif not runtime.get('cuda'):
                reasons.append(runtime.get('error', 'CUDA unavailable in the video environment'))
            if not hw['gpu'] or hw['gpu']['total_gb'] < config['vram_gb']:
                reasons.append(f"Requires at least {config['vram_gb']} GB NVIDIA VRAM")
            if hw['ram_gb'] < config['ram_gb']:
                reasons.append(f"Requires at least {config['ram_gb']} GB system RAM for this offload configuration")
            if hw['disk_free_gb'] < 2:
                reasons.append('Requires at least 2 GB free working disk')

        if not installed:
            reasons.append('Model weights are not installed')

        verified = False
        try:
            marker = json.loads((CACHE / key / 'smoke-test.json').read_text(encoding='utf-8'))
            manifest = json.loads((CACHE / key / 'installation.json').read_text(encoding='utf-8'))
            verified = marker.get('revision') == manifest.get('revision') and marker.get('model') == key
        except (OSError, ValueError, KeyError):
            pass

        # Determine explicit lifecycle state
        if not installed:
            state = ModelState.NOT_INSTALLED
        elif not hw['runtime_installed'] or not runtime.get('cuda'):
            state = ModelState.INSTALLED
        elif not hw.get('gpu') or hw['gpu']['total_gb'] < config['vram_gb'] or hw['ram_gb'] < config['ram_gb']:
            state = ModelState.ENVIRONMENT_READY
        elif not verified:
            state = ModelState.HARDWARE_COMPATIBLE
        else:
            state = ModelState.SMOKE_VERIFIED

        results.append(dict(
            id=key,
            **config,
            installed=installed,
            available=not reasons,
            reasons=reasons,
            verified=verified,
            state=state.value
        ))
    return results
