"""Local Text-to-Speech (TTS) and Voiceover Engine for LEXNIS Marketing Agency.

The catalogue below keeps the licence gate per model. Speech itself is recorded by the engines
installed on this computer (see video.voice: Piper voices when configured, otherwise the Windows
speech voices). The response reports which installed voice actually spoke; when none is installed
for the language the request fails instead of returning a placeholder tone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .model_registry import registry as model_registry


@dataclass
class VoiceProfile:
    voice_id: str
    display_name: str
    gender: str
    language: str
    engine: str
    model_id: str
    license_id: str
    commercial_allowed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


VOICE_CATALOG: List[VoiceProfile] = [
    VoiceProfile(
        voice_id="af_sarah",
        display_name="Sarah (US English - Executive Clear)",
        gender="female",
        language="en",
        engine="kokoro",
        model_id="kokoro-82m",
        license_id="Apache-2.0",
        commercial_allowed=True,
    ),
    VoiceProfile(
        voice_id="am_adam",
        display_name="Adam (US English - Deep Narrative)",
        gender="male",
        language="en",
        engine="kokoro",
        model_id="kokoro-82m",
        license_id="Apache-2.0",
        commercial_allowed=True,
    ),
    VoiceProfile(
        voice_id="piper_en_ryan",
        display_name="Ryan (UK English - Technical Authoritative)",
        gender="male",
        language="en",
        engine="piper",
        model_id="piper-tts",
        license_id="MIT",
        commercial_allowed=True,
    ),
    VoiceProfile(
        voice_id="piper_ar_kareem",
        display_name="Kareem (Arabic Modern Standard - Formal)",
        gender="male",
        language="ar",
        engine="piper",
        model_id="piper-tts",
        license_id="Voice-Reviewed",
        commercial_allowed=True,
    ),
    VoiceProfile(
        voice_id="xtts_noncommercial",
        display_name="XTTS Multi-Speaker [NON-COMMERCIAL / CPML GATED]",
        gender="neutral",
        language="multilingual",
        engine="coqui",
        model_id="coqui-xtts-v2",
        license_id="CPML-1.0",
        commercial_allowed=False,
    ),
]


class TTSEngine:
    """Voiceover synthesis engine with commercial license gating and broadcast normalization."""

    def __init__(self, output_dir: Optional[Path] = None):
        from core.public_access import scoped
        self.output_dir = output_dir or scoped(Path(__file__).resolve().parents[1] / "output/agency/audio/tts",'renders')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def list_voices(self, language: Optional[str] = None, commercial_only: bool = True) -> List[Dict[str, Any]]:
        voices = []
        for v in VOICE_CATALOG:
            if language and v.language != language and v.language != "multilingual":
                continue
            if commercial_only and not v.commercial_allowed:
                continue
            voices.append(v.to_dict())
        return voices

    def generate_voiceover(
        self,
        text: str,
        voice_id: str = "af_sarah",
        speed: float = 1.0,
        commercial_mode: bool = True
    ) -> Dict[str, Any]:
        """Synthesize voiceover audio, enforcing license gates and returning asset path."""
        voice = next((v for v in VOICE_CATALOG if v.voice_id == voice_id), None)
        if not voice:
            raise ValueError(f"Unknown voice ID '{voice_id}'")

        # 1. Enforce licensing gate
        gate = model_registry.check_license_gate(
            voice.model_id,
            campaign_mode="commercial" if commercial_mode else "internal_draft"
        )
        if not gate["allowed"]:
            raise PermissionError(gate["reason"])

        # 2. Text preprocessing & pronunciation normalization
        clean_text = self._preprocess_text(text)

        # 3. Audio generation with a real local speech engine (never a placeholder tone)
        audio_bytes, duration_sec, spoken_by = self._synthesize_audio(clean_text, voice, speed)

        # 4. Save WAV asset
        filename = f"voice_{voice.voice_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        dest_path = self.output_dir / filename
        dest_path.write_bytes(audio_bytes)

        return {
            "success": True,
            "filename": filename,
            "file_path": str(dest_path),
            "voice_id": voice.voice_id,
            "model_id": voice.model_id,
            "license_id": voice.license_id,
            "duration_seconds": round(duration_sec, 2),
            "sample_rate": 48000,
            "channels": 1,
            # The catalogue names the requested voice; this is the installed engine that actually spoke.
            "engine_used": spoken_by["engine"],
            "voice_used": spoken_by["name"],
            "voice_licence": spoken_by["licence"],
            "substituted": spoken_by["engine"] != voice.engine,
            "char_count": len(text),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _preprocess_text(self, text: str) -> str:
        # Normalize acronyms and whitespace
        clean = re.sub(r"\bAI\b", "A.I.", text)
        clean = re.sub(r"\bML\b", "M.L.", clean)
        clean = re.sub(r"\bAPI\b", "A.P.I.", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @staticmethod
    def _local_voice(voice: VoiceProfile) -> Dict[str, Any]:
        """Pick the installed speech voice that best matches a catalogue voice: same language, same
        engine family when available (Piper), then same gender."""
        from video import voice as video_voice
        language = "en" if voice.language == "multilingual" else voice.language
        candidates = video_voice.voices(language)
        if not candidates:
            names = {"ar": "Arabic", "en": "English"}
            raise ValueError(f"No {names.get(language, language)} speech voice is installed on this computer. "
                             "Install a Piper voice (set PIPER_BIN and PIPER_VOICES) to record voiceovers.")
        return sorted(candidates, key=lambda c: (c["engine"] != voice.engine, c["gender"] != voice.gender))[0]

    def _synthesize_audio(self, text: str, voice: VoiceProfile, speed: float) -> Tuple[bytes, float, Dict[str, Any]]:
        """Record the line with a real local speech engine, then apply the requested speed."""
        import tempfile
        from video import voice as video_voice
        from video.ffmpeg import ffmpeg
        local = self._local_voice(voice)
        with tempfile.TemporaryDirectory(prefix="agency-tts-") as work:
            raw = video_voice.speak(text, local, Path(work) / "line.wav", language=local["language"])
            out = Path(work) / "voice.wav"
            tempo = min(2.0, max(0.5, float(speed or 1)))
            chain = f"atempo={tempo:.3f}," if abs(tempo - 1) > .01 else ""
            ffmpeg(["-i", str(raw), "-af", chain + "aresample=48000", "-ac", "1", "-c:a", "pcm_s16le", str(out)], timeout=120)
            return out.read_bytes(), video_voice.wav_seconds(out), local


tts_engine = TTSEngine()
