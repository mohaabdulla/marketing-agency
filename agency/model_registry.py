"""Authoritative Model, License, and Capability Registry for LEXNIS Marketing Agency.

Enforces commercial licensing gates, tracks hardware requirements, and reports system capabilities.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class TaskType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO_ASR = "audio_asr"
    AUDIO_TTS = "audio_tts"
    AUDIO_MUSIC = "audio_music"


class InstallState(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFIED = "VERIFIED"


class CommercialStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMMERCIAL_ALLOWED = "COMMERCIAL_ALLOWED"
    NON_COMMERCIAL = "NON_COMMERCIAL"
    CONDITIONAL = "CONDITIONAL"


@dataclass
class ModelManifest:
    model_id: str
    display_name: str
    task: TaskType
    provider: str = "local"
    source_type: str = "huggingface"
    source_repository: str = ""
    revision: str = "main"
    runtime: str = "transformers"
    adapter: str = ""
    license_id: str = ""
    license_url: str = ""
    license_text_hash: str = ""
    commercial_use_status: CommercialStatus = CommercialStatus.UNKNOWN
    commercial_use_notes: str = ""
    upstream_license_notes: str = ""
    estimated_download_bytes: int = 0
    estimated_vram_mb: int = 0
    estimated_ram_mb: int = 0
    recommended_vram_mb: int = 0
    supported_modes: List[str] = field(default_factory=lambda: ["commercial", "internal_draft"])
    supported_languages: List[str] = field(default_factory=lambda: ["en", "ar"])
    native_resolutions: List[str] = field(default_factory=list)
    native_fps: List[int] = field(default_factory=list)
    native_duration_limits: Dict[str, float] = field(default_factory=dict)
    requires_gpu: bool = False
    supports_cpu_offload: bool = True
    install_state: InstallState = InstallState.NOT_INSTALLED
    verification_state: str = "UNVERIFIED"
    verified_at: Optional[str] = None
    verified_hardware: Optional[str] = None
    measured_peak_vram_mb: Optional[int] = None
    measured_peak_ram_mb: Optional[int] = None
    measured_generation_seconds: Optional[float] = None
    output_validation: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["task"] = self.task.value
        d["commercial_use_status"] = self.commercial_use_status.value
        d["install_state"] = self.install_state.value
        return d


# Pinned authoritative registry
REGISTRY_CATALOG: Dict[str, ModelManifest] = {
    # TEXT MODELS
    "qwen3-4b-gguf": ModelManifest(
        model_id="qwen3-4b-gguf",
        display_name="Qwen3-4B-GGUF (Strategic Text Copilot)",
        task=TaskType.TEXT,
        source_repository="Qwen/Qwen3-4B-GGUF",
        revision="main",
        runtime="llama-cpp-python",
        adapter="agency.local_text",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0 permissive license. Commercial marketing copy and strategy allowed.",
        estimated_download_bytes=2_600_000_000,
        estimated_vram_mb=3500,
        estimated_ram_mb=6000,
        recommended_vram_mb=6000,
        supported_languages=["en", "ar", "fr", "de", "es", "zh"],
        requires_gpu=False,
        supports_cpu_offload=True,
    ),
    "qwen2.5-coder-7b": ModelManifest(
        model_id="qwen2.5-coder-7b",
        display_name="Qwen2.5-Coder-7B (Copy & Strategy)",
        task=TaskType.TEXT,
        source_repository="Qwen/Qwen2.5-Coder-7B-Instruct",
        revision="main",
        runtime="transformers",
        adapter="agency.local_text",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0 permissive license. Commercial marketing copy generation permitted.",
        estimated_download_bytes=15_000_000_000,
        estimated_vram_mb=8000,
        estimated_ram_mb=16000,
        recommended_vram_mb=12000,
        supported_languages=["en", "ar", "zh"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "llama-3.1-8b-instruct": ModelManifest(
        model_id="llama-3.1-8b-instruct",
        display_name="Llama 3.1 8B Instruct",
        task=TaskType.TEXT,
        source_repository="meta-llama/Meta-Llama-3.1-8B-Instruct",
        revision="main",
        runtime="transformers",
        adapter="agency.local_text",
        license_id="Llama-3.1-Community",
        license_url="https://www.llama.com/llama3/license/",
        commercial_use_status=CommercialStatus.CONDITIONAL,
        commercial_use_notes="Permitted for commercial use up to 700M monthly active users. Attribution required.",
        estimated_download_bytes=16_000_000_000,
        estimated_vram_mb=9000,
        estimated_ram_mb=18000,
        recommended_vram_mb=16000,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "hi"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),

    # IMAGE MODELS
    "flux.1-schnell": ModelManifest(
        model_id="flux.1-schnell",
        display_name="FLUX.1-schnell (Photorealistic Visuals)",
        task=TaskType.IMAGE,
        source_repository="black-forest-labs/FLUX.1-schnell",
        revision="main",
        runtime="diffusers",
        adapter="visual_engine",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0 permissive license explicitly permits commercial advertising imagery.",
        estimated_download_bytes=24_000_000_000,
        estimated_vram_mb=12000,
        estimated_ram_mb=24000,
        recommended_vram_mb=16000,
        native_resolutions=["1024x1024", "1536x864", "864x1536", "1200x630"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "realvisxl-v5.0": ModelManifest(
        model_id="realvisxl-v5.0",
        display_name="RealVisXL V5.0 (B2B Corporate Photography)",
        task=TaskType.IMAGE,
        source_repository="SG161222/RealVisXL_V5.0",
        revision="main",
        runtime="diffusers",
        adapter="visual_engine",
        license_id="CreativeML-OpenRAIL-M",
        license_url="https://huggingface.co/spaces/CompVis/stable-diffusion-license",
        commercial_use_status=CommercialStatus.REVIEW_REQUIRED,
        commercial_use_notes="OpenRAIL-M allows commercial use subject to use restrictions (no deceptive generation, defamatory, illegal).",
        estimated_download_bytes=6_900_000_000,
        estimated_vram_mb=6500,
        estimated_ram_mb=12000,
        recommended_vram_mb=8000,
        native_resolutions=["1024x1024", "1536x864", "864x1536", "1080x1350"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "sdxl-base-1.0": ModelManifest(
        model_id="sdxl-base-1.0",
        display_name="Stable Diffusion XL Base 1.0",
        task=TaskType.IMAGE,
        source_repository="stabilityai/stable-diffusion-xl-base-1.0",
        revision="main",
        runtime="diffusers",
        adapter="visual_engine",
        license_id="OpenRAIL++-M",
        license_url="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
        commercial_use_status=CommercialStatus.REVIEW_REQUIRED,
        commercial_use_notes="OpenRAIL++ allows commercial use with standard acceptable use restrictions.",
        estimated_download_bytes=6_900_000_000,
        estimated_vram_mb=6500,
        estimated_ram_mb=12000,
        recommended_vram_mb=8000,
        native_resolutions=["1024x1024", "1152x896", "896x1152"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),

    # VIDEO MODELS
    "wan2.1-t2v-1.3b": ModelManifest(
        model_id="wan2.1-t2v-1.3b",
        display_name="Wan2.1 T2V-1.3B (Local Video)",
        task=TaskType.VIDEO,
        source_repository="Wan-AI/Wan2.1-T2V-1.3B",
        revision="main",
        runtime="diffusers",
        adapter="video_models",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0. Commercial video production allowed.",
        estimated_download_bytes=3_500_000_000,
        estimated_vram_mb=8192,
        estimated_ram_mb=16000,
        recommended_vram_mb=12000,
        native_resolutions=["832x480", "480x832"],
        native_fps=[16],
        native_duration_limits={"min": 2.0, "max": 5.0, "default": 3.0},
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "wan2.2-ti2v-5b": ModelManifest(
        model_id="wan2.2-ti2v-5b",
        display_name="Wan2.2 TI2V-5B (HQ Text & Image to Video)",
        task=TaskType.VIDEO,
        source_repository="Wan-AI/Wan2.2-TI2V-5B",
        revision="main",
        runtime="diffusers",
        adapter="video_models",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0. High-quality image-to-video and text-to-video.",
        estimated_download_bytes=10_500_000_000,
        estimated_vram_mb=12000,
        estimated_ram_mb=24000,
        recommended_vram_mb=16000,
        native_resolutions=["1280x720", "720x1280"],
        native_fps=[24],
        native_duration_limits={"min": 2.0, "max": 6.0, "default": 4.0},
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "cogvideox-2b": ModelManifest(
        model_id="cogvideox-2b",
        display_name="CogVideoX-2B (Fast Video Prototype)",
        task=TaskType.VIDEO,
        source_repository="THUDM/CogVideoX-2b",
        revision="main",
        runtime="diffusers",
        adapter="video_models",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0. Fast commercial motion generation.",
        estimated_download_bytes=5_000_000_000,
        estimated_vram_mb=8000,
        estimated_ram_mb=16000,
        recommended_vram_mb=12000,
        native_resolutions=["720x480"],
        native_fps=[8],
        native_duration_limits={"min": 2.0, "max": 6.0, "default": 4.0},
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "wan2.1-i2v-14b": ModelManifest(
        model_id="wan2.1-i2v-14b",
        display_name="Wan2.1 I2V-14B (Studio Cinematic Animation)",
        task=TaskType.VIDEO,
        source_repository="Wan-AI/Wan2.1-I2V-14B-720P",
        revision="main",
        runtime="diffusers",
        adapter="video_models",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0. Production-grade image-to-video for 24GB+ VRAM workstations.",
        estimated_download_bytes=28_000_000_000,
        estimated_vram_mb=22000,
        estimated_ram_mb=48000,
        recommended_vram_mb=24000,
        native_resolutions=["1280x720", "960x544"],
        native_fps=[24],
        native_duration_limits={"min": 3.0, "max": 8.0, "default": 5.0},
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "ltx-video": ModelManifest(
        model_id="ltx-video",
        display_name="LTX-Video (0.9.1)",
        task=TaskType.VIDEO,
        source_repository="Lightricks/LTX-Video",
        revision="main",
        runtime="diffusers",
        adapter="video_models",
        license_id="Lightricks-OpenRAIL",
        license_url="https://huggingface.co/Lightricks/LTX-Video/blob/main/LICENSE.md",
        commercial_use_status=CommercialStatus.REVIEW_REQUIRED,
        commercial_use_notes="Review required: check specific version terms before commercial deployment.",
        estimated_download_bytes=5_500_000_000,
        estimated_vram_mb=10000,
        estimated_ram_mb=20000,
        recommended_vram_mb=16000,
        native_resolutions=["768x512", "512x768"],
        native_fps=[24],
        native_duration_limits={"min": 2.0, "max": 5.0, "default": 3.0},
        requires_gpu=True,
        supports_cpu_offload=True,
    ),

    # AUDIO ASR (SPEECH-TO-TEXT)
    "whisper-large-v3": ModelManifest(
        model_id="whisper-large-v3",
        display_name="OpenAI Whisper Large v3 (Multilingual Subtitles)",
        task=TaskType.AUDIO_ASR,
        source_repository="openai/whisper-large-v3",
        revision="main",
        runtime="faster-whisper",
        adapter="agency.audio",
        license_id="MIT",
        license_url="https://opensource.org/licenses/MIT",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="MIT License. Commercial transcription and subtitle generation fully allowed.",
        estimated_download_bytes=3_100_000_000,
        estimated_vram_mb=4500,
        estimated_ram_mb=6000,
        recommended_vram_mb=6000,
        supported_languages=["en", "ar", "es", "fr", "de", "zh", "ja"],
        requires_gpu=False,
        supports_cpu_offload=True,
    ),
    "whisper-base": ModelManifest(
        model_id="whisper-base",
        display_name="OpenAI Whisper Base (Lightweight CPU Subtitles)",
        task=TaskType.AUDIO_ASR,
        source_repository="openai/whisper-base",
        revision="main",
        runtime="faster-whisper",
        adapter="agency.audio",
        license_id="MIT",
        license_url="https://opensource.org/licenses/MIT",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="MIT License. Fast CPU transcription.",
        estimated_download_bytes=150_000_000,
        estimated_vram_mb=800,
        estimated_ram_mb=1500,
        recommended_vram_mb=1000,
        supported_languages=["en", "ar", "es", "fr", "de", "zh"],
        requires_gpu=False,
        supports_cpu_offload=True,
    ),

    # AUDIO TTS (VOICEOVER)
    "kokoro-82m": ModelManifest(
        model_id="kokoro-82m",
        display_name="Kokoro-82M (Executive Voiceover)",
        task=TaskType.AUDIO_TTS,
        source_repository="hexgrad/Kokoro-82M",
        revision="main",
        runtime="kokoro",
        adapter="agency.tts",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0 license. High quality studio voiceover for commercial campaigns.",
        estimated_download_bytes=350_000_000,
        estimated_vram_mb=1000,
        estimated_ram_mb=2000,
        recommended_vram_mb=2000,
        supported_languages=["en"],
        requires_gpu=False,
        supports_cpu_offload=True,
    ),
    "piper-tts": ModelManifest(
        model_id="piper-tts",
        display_name="Piper TTS (CPU-Optimized Multilingual)",
        task=TaskType.AUDIO_TTS,
        source_repository="rhasspy/piper",
        revision="main",
        runtime="piper-tts",
        adapter="agency.tts",
        license_id="MIT/VoiceSpecific",
        license_url="https://github.com/rhasspy/piper/blob/master/LICENSE.md",
        commercial_use_status=CommercialStatus.CONDITIONAL,
        commercial_use_notes="Piper code is MIT. Individual voice checkpoints must be reviewed for commercial usage.",
        estimated_download_bytes=120_000_000,
        estimated_vram_mb=0,
        estimated_ram_mb=1000,
        recommended_vram_mb=0,
        supported_languages=["en", "ar", "es", "fr", "de"],
        requires_gpu=False,
        supports_cpu_offload=True,
    ),
    "coqui-xtts-v2": ModelManifest(
        model_id="coqui-xtts-v2",
        display_name="Coqui XTTS-v2 [NON-COMMERCIAL / GATED]",
        task=TaskType.AUDIO_TTS,
        source_repository="coqui/XTTS-v2",
        revision="main",
        runtime="TTS",
        adapter="agency.tts",
        license_id="CPML-1.0",
        license_url="https://coqui.ai/cpml",
        commercial_use_status=CommercialStatus.NON_COMMERCIAL,
        commercial_use_notes="CPML (Coqui Public Model License) strictly prohibits commercial use. Blocked from commercial campaigns.",
        estimated_download_bytes=1_800_000_000,
        estimated_vram_mb=3500,
        estimated_ram_mb=6000,
        recommended_vram_mb=4000,
        supported_languages=["en", "ar", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "zh", "ja", "ko", "hu"],
        requires_gpu=True,
        supports_cpu_offload=True,
    ),

    # AUDIO MUSIC
    "ace-step-v1": ModelManifest(
        model_id="ace-step-v1",
        display_name="ACE-Step-v1-3.5B (Commercial Background Music)",
        task=TaskType.AUDIO_MUSIC,
        source_repository="ACE-Studio/ACE-Step-v1-3.5B",
        revision="main",
        runtime="transformers",
        adapter="agency.music",
        license_id="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        commercial_use_status=CommercialStatus.COMMERCIAL_ALLOWED,
        commercial_use_notes="Apache 2.0 license. Permitted for commercial background track synthesis.",
        estimated_download_bytes=7_000_000_000,
        estimated_vram_mb=8000,
        estimated_ram_mb=16000,
        recommended_vram_mb=12000,
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "musicgen-small": ModelManifest(
        model_id="musicgen-small",
        display_name="MusicGen Small [NON-COMMERCIAL / GATED]",
        task=TaskType.AUDIO_MUSIC,
        source_repository="facebook/musicgen-small",
        revision="main",
        runtime="audiocraft",
        adapter="agency.music",
        license_id="CC-BY-NC-4.0",
        license_url="https://creativecommons.org/licenses/by-nc/4.0/",
        commercial_use_status=CommercialStatus.NON_COMMERCIAL,
        commercial_use_notes="Weights are released under Creative Commons Non-Commercial 4.0. Cannot be used in commercial marketing.",
        estimated_download_bytes=2_300_000_000,
        estimated_vram_mb=5000,
        estimated_ram_mb=8000,
        recommended_vram_mb=8000,
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
    "stable-audio-open-1.0": ModelManifest(
        model_id="stable-audio-open-1.0",
        display_name="Stable Audio Open 1.0 (Sound Effects & Ambience)",
        task=TaskType.AUDIO_MUSIC,
        source_repository="stabilityai/stable-audio-open-1.0",
        revision="main",
        runtime="diffusers",
        adapter="agency.music",
        license_id="StabilityAI-Community",
        license_url="https://huggingface.co/stabilityai/stable-audio-open-1.0/blob/main/LICENSE",
        commercial_use_status=CommercialStatus.REVIEW_REQUIRED,
        commercial_use_notes="Stability Community License permits commercial use under revenue thresholds. Review required.",
        estimated_download_bytes=3_200_000_000,
        estimated_vram_mb=6000,
        estimated_ram_mb=12000,
        recommended_vram_mb=8000,
        requires_gpu=True,
        supports_cpu_offload=True,
    ),
}


class ModelRegistry:
    """Manages model catalog, licensing gates, verification, and hardware discovery."""

    def __init__(self, catalog: Optional[Dict[str, ModelManifest]] = None):
        self._catalog = catalog or dict(REGISTRY_CATALOG)

    def list_models(self, task: Optional[str] = None, commercial_only: bool = False) -> List[Dict[str, Any]]:
        results = []
        for manifest in self._catalog.values():
            if task and manifest.task.value != task:
                continue
            if commercial_only and manifest.commercial_use_status == CommercialStatus.NON_COMMERCIAL:
                continue
            results.append(manifest.to_dict())
        return results

    def get_manifest(self, model_id: str) -> Optional[ModelManifest]:
        return self._catalog.get(model_id)

    def check_license_gate(self, model_id: str, campaign_mode: str = "commercial") -> Dict[str, Any]:
        """Check whether a model can be legally executed for a given campaign mode.

        In 'commercial' mode (the agency default):
        - NON_COMMERCIAL models are BLOCKED.
        - CONDITIONAL and REVIEW_REQUIRED models trigger explicit warnings.
        - COMMERCIAL_ALLOWED models pass unconditionally.
        """
        manifest = self.get_manifest(model_id)
        if not manifest:
            return {
                "allowed": False,
                "reason": f"Model '{model_id}' is not registered in the authoritative model registry.",
                "status": CommercialStatus.UNKNOWN.value,
                "warnings": ["Unknown model identifier"],
            }

        dev_override = os.environ.get("AGENCY_ALLOW_NONCOMMERCIAL_DEV", "0") == "1"

        if campaign_mode == "commercial" and not dev_override:
            if manifest.commercial_use_status == CommercialStatus.NON_COMMERCIAL:
                return {
                    "allowed": False,
                    "reason": (
                        f"Model '{manifest.display_name}' has a {manifest.license_id} license "
                        f"({manifest.commercial_use_notes}) which PROHIBITS commercial marketing use."
                    ),
                    "status": manifest.commercial_use_status.value,
                    "warnings": [manifest.commercial_use_notes],
                }

        warnings = []
        if manifest.commercial_use_status in {CommercialStatus.CONDITIONAL, CommercialStatus.REVIEW_REQUIRED}:
            warnings.append(manifest.commercial_use_notes)

        return {
            "allowed": True,
            "status": manifest.commercial_use_status.value,
            "license_id": manifest.license_id,
            "license_url": manifest.license_url,
            "notes": manifest.commercial_use_notes,
            "warnings": warnings,
        }

    def inspect_install_states(self) -> Dict[str, InstallState]:
        """Check filesystem/cache to see if model checkpoints actually exist."""
        states = {}
        for mid, manifest in self._catalog.items():
            # Check for common local model files or weights
            installed = False
            # Look in standard local directories
            candidate_paths = [
                Path(f"models/{mid}"),
                Path(f"models/{manifest.source_repository}"),
                Path(f"weights/{mid}"),
            ]
            for cp in candidate_paths:
                if cp.exists() and any(cp.iterdir()):
                    installed = True
                    break
            states[mid] = InstallState.INSTALLED if installed else InstallState.NOT_INSTALLED
            manifest.install_state = states[mid]
        return states

    def probe_system_capabilities(self) -> Dict[str, Any]:
        """Deterministic system hardware, CUDA, FFmpeg, and capability inspection."""
        import platform

        cpu_count = os.cpu_count() or 1
        ram_gb = 8.0
        try:
            import psutil
            ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        except Exception:
            pass

        # Check CUDA
        cuda_available = False
        gpu_device_name = "None"
        gpu_vram_mb = 0
        try:
            import torch
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                gpu_device_name = torch.cuda.get_device_name(0)
                gpu_vram_mb = int(torch.cuda.get_device_properties(0).total_memory / (1024 ** 2))
        except Exception:
            pass

        # Check FFmpeg
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            local_ff = Path("output/video-tools/ffmpeg.exe")
            if local_ff.exists():
                ffmpeg_path = str(local_ff.resolve())
            else:
                local_ff_nix = Path("output/video-tools/ffmpeg")
                if local_ff_nix.exists():
                    ffmpeg_path = str(local_ff_nix.resolve())
        ffmpeg_available = ffmpeg_path is not None
        ffmpeg_version = "Unknown"
        if ffmpeg_available:
            try:
                res = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
                first_line = res.stdout.splitlines()[0] if res.stdout else ""
                ffmpeg_version = first_line.split(" ")[2] if len(first_line.split(" ")) > 2 else "installed"
            except Exception:
                ffmpeg_version = "detected"

        # Determine feasible tiers
        tiers = []
        if ram_gb >= 16:
            tiers.append("cpu_high_memory")
        if cuda_available and gpu_vram_mb >= 6000:
            tiers.append("gpu_sdxl_feasible")
        if cuda_available and gpu_vram_mb >= 12000:
            tiers.append("gpu_flux_feasible")
            tiers.append("gpu_video_feasible")
        if cuda_available and gpu_vram_mb >= 24000:
            tiers.append("gpu_wan14b_feasible")

        return {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": cpu_count,
            "ram_total_gb": ram_gb,
            "cuda_available": cuda_available,
            "gpu_device_name": gpu_device_name,
            "gpu_vram_mb": gpu_vram_mb,
            "ffmpeg_available": ffmpeg_available,
            "ffmpeg_path": ffmpeg_path,
            "ffmpeg_version": ffmpeg_version,
            "feasible_tiers": tiers,
            "commercial_mode_enforced": os.environ.get("AGENCY_ALLOW_NONCOMMERCIAL_DEV", "0") != "1",
            "total_registered_models": len(self._catalog),
        }


# Global singleton
registry = ModelRegistry()
