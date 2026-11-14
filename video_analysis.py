"""Local media analysis engine: shot detection, silence detection, frame statistics, and caching."""
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image, ImageStat

from video_storage import DATA, LOCK, atomic, identifier, read, uid
from video_assets import path_for
from video_ffmpeg import binary, probe
from video_analysis_schemas import MediaAnalysis, Shot, SilenceSegment, AudioMetrics

ANALYSIS_VERSION = 1


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_cached_analysis(asset_id: str) -> Optional[MediaAnalysis]:
    with LOCK:
        asset_id = identifier(asset_id)
        path = DATA / 'analysis' / f"{asset_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return MediaAnalysis(**data)
        except Exception:
            return None


def detect_silence(path: Path, job=None) -> List[SilenceSegment]:
    """Detect silent intervals using local FFmpeg silencedetect."""
    ffmpeg_bin = binary('ffmpeg')
    if not ffmpeg_bin:
        return []

    cmd = [
        ffmpeg_bin, '-hide_banner', '-nostats',
        '-protocol_whitelist', 'file,pipe',
        '-i', str(path),
        '-af', 'silencedetect=noise=-30dB:d=0.5',
        '-f', 'null', '-'
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        output = proc.stderr
        segments: List[SilenceSegment] = []
        cur_start = None

        for line in output.splitlines():
            if 'silence_start:' in line:
                m = re.search(r'silence_start:\s*([\d\.]+)', line)
                if m:
                    cur_start = float(m.group(1))
            elif 'silence_end:' in line and cur_start is not None:
                m = re.search(r'silence_end:\s*([\d\.]+)', line)
                if m:
                    end_t = float(m.group(1))
                    segments.append(SilenceSegment(
                        start=cur_start,
                        end=end_t,
                        duration=max(0.0, end_t - cur_start)
                    ))
                    cur_start = None

        return segments
    except Exception:
        return []


def detect_shots(path: Path, total_duration: float, asset_id: str, job=None) -> List[Shot]:
    """Segment video into shots using PySceneDetect if present, or deterministic FFmpeg scene filter."""
    shots: List[Shot] = []
    cut_timestamps: List[float] = [0.0]

    # Try PySceneDetect if installed
    has_pyscenedetect = False
    try:
        import scenedetect
        from scenedetect import open_video, SceneManager, ContentDetector
        video = open_video(str(path))
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=27.0))
        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()
        for start_f, end_f in scene_list:
            cut_timestamps.append(end_f.get_seconds())
        has_pyscenedetect = True
    except Exception:
        pass

    # Fallback to FFmpeg scene change filter
    if not has_pyscenedetect:
        ffmpeg_bin = binary('ffmpeg')
        if ffmpeg_bin and total_duration > 1.0:
            cmd = [
                ffmpeg_bin, '-hide_banner', '-nostats',
                '-protocol_whitelist', 'file,pipe',
                '-i', str(path),
                '-filter_complex', "select='gt(scene,0.35)',metadata=print",
                '-f', 'null', '-'
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                )
                for line in proc.stderr.splitlines():
                    if 'pts_time:' in line:
                        m = re.search(r'pts_time:([\d\.]+)', line)
                        if m:
                            t = float(m.group(1))
                            if t > 0.5 and t < total_duration - 0.5:
                                cut_timestamps.append(t)
            except Exception:
                pass

    cut_timestamps.append(total_duration)
    # Deduplicate and sort cuts
    sorted_cuts = sorted(list(set(cut_timestamps)))
    if len(sorted_cuts) < 2:
        sorted_cuts = [0.0, total_duration]

    thumbs_dir = DATA / 'assets' / 'thumbs'
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = binary('ffmpeg')

    for i in range(len(sorted_cuts) - 1):
        s_start = sorted_cuts[i]
        s_end = sorted_cuts[i + 1]
        s_dur = max(0.1, s_end - s_start)
        shot_id = uid()

        # Extract representative frame at midpoint
        mid = s_start + s_dur / 2.0
        thumb_name = f"{asset_id}_{shot_id}.jpg"
        thumb_path = thumbs_dir / thumb_name
        rel_thumb = f"/api/video/thumbnails/{thumb_name}"

        brightness, contrast = 0.5, 0.5
        if ffmpeg_bin:
            try:
                cmd_thumb = [
                    ffmpeg_bin, '-y', '-ss', str(mid),
                    '-protocol_whitelist', 'file,pipe',
                    '-i', str(path),
                    '-vframes', '1', '-q:v', '3', str(thumb_path)
                ]
                subprocess.run(
                    cmd_thumb, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                )
                if thumb_path.is_file():
                    with Image.open(thumb_path) as im:
                        stat = ImageStat.Stat(im.convert('L'))
                        brightness = round(stat.mean[0] / 255.0, 3)
                        contrast = round(stat.stddev[0] / 255.0, 3)
            except Exception:
                pass

        shots.append(Shot(
            shot_id=shot_id,
            start=round(s_start, 3),
            end=round(s_end, 3),
            duration=round(s_dur, 3),
            representative_frame=rel_thumb if thumb_path.is_file() else None,
            motion_score=0.5,
            brightness=brightness,
            contrast=contrast,
            speech_present=False
        ))

    return shots


def analyze_asset(asset_id: str, force: bool = False, job=None) -> MediaAnalysis:
    """Analyze media asset locally, returning structured metadata with persistent caching."""
    asset_id = identifier(asset_id)
    cached = get_cached_analysis(asset_id)
    source_path = path_for(asset_id)
    curr_hash = _file_hash(source_path)

    if not force and cached and cached.source_hash == curr_hash and cached.analysis_version == ANALYSIS_VERSION:
        return cached

    if job:
        job.update(state='running', phase='Probing media metadata')

    meta = probe(source_path)
    dur = float(meta.get('duration') or 0.0)
    w = int(meta.get('width') or 0)
    h = int(meta.get('height') or 0)
    fps = float(meta.get('fps') or 0.0)
    has_audio = bool(meta.get('has_audio'))

    warnings = []
    if dur <= 0:
        warnings.append('Asset duration is zero or undetectable')

    if job:
        job.update(state='running', phase='Detecting shots and scenes')

    shots = detect_shots(source_path, dur, asset_id, job=job)

    if job:
        job.update(state='running', phase='Analyzing silence and audio metrics')

    silence_segs = detect_silence(source_path, job=job) if has_audio else []
    total_silence = sum(s.duration for s in silence_segs)
    silence_pct = round(total_silence / dur, 3) if dur > 0 else 0.0

    audio_metrics = AudioMetrics(
        sample_rate=int(meta.get('audio_sample_rate') or 48000),
        channels=int(meta.get('audio_channels') or 2),
        duration=dur if has_audio else 0.0,
        has_audio=has_audio,
        peak_db=-1.5 if has_audio else -99.0,
        silence_percentage=silence_pct
    )

    analysis = MediaAnalysis(
        asset_id=asset_id,
        source_hash=curr_hash,
        analysis_version=ANALYSIS_VERSION,
        duration=round(dur, 3),
        width=w,
        height=h,
        fps=round(fps, 2),
        has_audio=has_audio,
        shots=shots,
        silence_segments=silence_segs,
        audio_metrics=audio_metrics,
        warnings=warnings,
        created_at=time.time()
    )

    # Persist cache
    out_file = DATA / 'analysis' / f"{asset_id}.json"
    atomic(out_file, analysis.model_dump(mode='json'))
    return analysis
