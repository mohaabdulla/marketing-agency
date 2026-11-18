"""Data models for local media analysis, shot detection, and silence extraction."""
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from video.storage import uid


class StrictAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Shot(StrictAnalysis):
    shot_id: str = Field(default_factory=uid)
    start: float = Field(0.0, ge=0.0)
    end: float = Field(0.0, ge=0.0)
    duration: float = Field(0.0, ge=0.0)
    representative_frame: Optional[str] = None
    # Measured values. None means "not measured" (tool missing or frame unreadable), never a guess.
    motion_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    motion_mean_abs_diff: Optional[float] = Field(None, ge=0.0, le=1.0)
    sharpness_laplacian_var: Optional[float] = Field(None, ge=0.0)
    brightness: Optional[float] = Field(None, ge=0.0, le=1.0)
    contrast: Optional[float] = Field(None, ge=0.0, le=1.0)
    face: Optional[Dict[str, Any]] = None
    audio_activity_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    # True/False only when a transcript with word timings exists for this asset.
    speech_present: Optional[bool] = None
    scene_change_method: Optional[str] = None
    transcript_segment_ids: List[str] = Field(default_factory=list)


class SilenceSegment(StrictAnalysis):
    start: float = Field(0.0, ge=0.0)
    end: float = Field(0.0, ge=0.0)
    duration: float = Field(0.0, ge=0.0)


class AudioMetrics(StrictAnalysis):
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    codec: Optional[str] = None
    bitrate: Optional[int] = None
    duration: float = 0.0
    has_audio: bool = False
    # ITU-R BS.1770 measurements (FFmpeg ebur128). None when there is no audio or measuring failed.
    integrated_lufs: Optional[float] = None
    loudness_range_lu: Optional[float] = None
    true_peak_dbtp: Optional[float] = None
    true_peak_over_0dbtp: Optional[bool] = None
    measurement_method: Optional[str] = None
    silence_percentage: Optional[float] = None


class TechnicalMetadata(StrictAnalysis):
    """Stream facts read by ffprobe; a tag that the file does not carry stays None."""
    video_codec: Optional[str] = None
    video_profile: Optional[str] = None
    video_level: Optional[int] = None
    pix_fmt: Optional[str] = None
    bit_depth: Optional[int] = None
    field_order: Optional[str] = None
    fps_rational: Optional[str] = None
    nominal_fps: Optional[float] = None
    variable_frame_rate: Optional[bool] = None
    frame_count: Optional[int] = None
    video_bitrate: Optional[int] = None
    color_range: Optional[str] = None
    color_space: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    hdr: Optional[bool] = None
    sample_aspect_ratio: Optional[str] = None
    display_aspect_ratio: Optional[str] = None
    rotation: Optional[int] = None
    orientation: Optional[str] = None


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
    technical: TechnicalMetadata = Field(default_factory=TechnicalMetadata)
    black_intervals: Optional[List[Dict[str, float]]] = None
    frozen_intervals: Optional[List[Dict[str, float]]] = None
    not_measured: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)

