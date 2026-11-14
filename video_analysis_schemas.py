"""Data models for local media analysis, shot detection, and silence extraction."""
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from video_storage import uid


class StrictAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Shot(StrictAnalysis):
    shot_id: str = Field(default_factory=uid)
    start: float = Field(0.0, ge=0.0)
    end: float = Field(0.0, ge=0.0)
    duration: float = Field(0.0, ge=0.0)
    representative_frame: Optional[str] = None
    motion_score: float = Field(0.5, ge=0.0, le=1.0)
    brightness: float = Field(0.5, ge=0.0, le=1.0)
    contrast: float = Field(0.5, ge=0.0, le=1.0)
    speech_present: bool = False
    transcript_segment_ids: List[str] = Field(default_factory=list)


class SilenceSegment(StrictAnalysis):
    start: float = Field(0.0, ge=0.0)
    end: float = Field(0.0, ge=0.0)
    duration: float = Field(0.0, ge=0.0)


class AudioMetrics(StrictAnalysis):
    sample_rate: int = 48000
    channels: int = 2
    duration: float = 0.0
    has_audio: bool = False
    peak_db: float = 0.0
    silence_percentage: float = 0.0


class MediaAnalysis(StrictAnalysis):
    asset_id: str
    source_hash: str = ''
    analysis_version: int = 1
    duration: float = Field(0.0, ge=0.0)
    width: int = Field(0, ge=0)
    height: int = Field(0, ge=0)
    fps: float = Field(0.0, ge=0.0)
    has_audio: bool = False
    shots: List[Shot] = Field(default_factory=list)
    silence_segments: List[SilenceSegment] = Field(default_factory=list)
    audio_metrics: AudioMetrics = Field(default_factory=AudioMetrics)
    warnings: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)

