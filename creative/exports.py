"""Export pipeline for still images, animated GIFs, direct MP4, and WebM rendering."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from PIL import Image

from .scene import SceneGraph
from .schemas import GenerationManifest, Scene
from .manifests import ManifestEngine
from .qa import qa_engine


def get_ffmpeg_binary() -> Optional[str]:
    """Discover FFmpeg executable path."""
    candidate_locations = [
        Path("output/video-tools/ffmpeg.exe"),
        Path(__file__).resolve().parents[1] / "output/video-tools/ffmpeg.exe",
    ]
    for c in candidate_locations:
        if c.exists():
            return str(c.resolve())
    try:
        from video_ffmpeg import binary
        return binary("ffmpeg")
    except Exception:
        pass
    candidate = shutil.which("ffmpeg")
    if candidate:
        return candidate
    return None


class ExportResult(dict):
    """Result dictionary with attribute-based access."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self.items():
            setattr(self, k, v)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _ensure_scene_graph(sg: Union[SceneGraph, Scene]) -> SceneGraph:
    if hasattr(sg, "render_frame"):
        return sg
    scene = sg
    cw = scene.canvas.width if scene.canvas else 1080
    ch = scene.canvas.height if scene.canvas else 1080
    return SceneGraph(scene, cw, ch)


class CreativeExporter:
    """Renders scene graphs directly into still image, looping GIF, MP4 video, or WebM."""

    @classmethod
    def render_still(
        cls,
        scene_graph: Union[SceneGraph, Scene],
        output_path: str,
        t: float = 0.0,
        format: str = "PNG",
        asset_loader: Optional[Callable] = None
    ) -> ExportResult:
        sg = _ensure_scene_graph(scene_graph)
        frame = sg.render_frame(t, asset_loader=asset_loader)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if format.upper() in {"JPG", "JPEG"}:
            rgb = frame.convert("RGB")
            rgb.save(str(p), format="JPEG", quality=95)
        else:
            frame.save(str(p), format="PNG")

        audit = qa_engine.audit_image_file(str(p))
        manifest = GenerationManifest(
            generator_type="creative-layered-still",
            model_id="lexnis-creative-engine",
            steps=1,
            native_width=frame.width,
            native_height=frame.height,
            native_fps=0,
            native_frames=1,
            timestamp=str(time.time()),
        )
        return ExportResult({
            "success": audit["passed"],
            "path": str(p),
            "format": format.upper(),
            "width": frame.width,
            "height": frame.height,
            "audit": audit,
            "manifest": manifest,
        })

    @classmethod
    def render_gif(
        cls,
        scene_graph: Union[SceneGraph, Scene],
        output_path: str,
        fps: int = 15,
        duration: Optional[float] = None,
        loop: int = 0,
        optimize_palette: bool = True,
        asset_loader: Optional[Callable] = None
    ) -> ExportResult:
        sg = _ensure_scene_graph(scene_graph)
        dur = duration or sg.scene.duration
        total_frames = max(1, int(dur * fps))
        step = dur / total_frames

        frames: List[Image.Image] = []
        for i in range(total_frames):
            t = i * step
            fr = sg.render_frame(t, asset_loader=asset_loader)
            frames.append(fr.convert("RGBA"))

        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if optimize_palette:
            quantized = [
                f.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                for f in frames
            ]
        else:
            quantized = [f.convert("RGB").convert("P") for f in frames]

        frame_duration_ms = int(1000.0 / fps)
        quantized[0].save(
            str(p),
            save_all=True,
            append_images=quantized[1:],
            duration=frame_duration_ms,
            loop=loop,
            optimize=True,
        )

        manifest = GenerationManifest(
            generator_type="creative-motion-gif",
            model_id="lexnis-motion-engine",
            steps=1,
            native_width=sg.canvas_w,
            native_height=sg.canvas_h,
            native_fps=fps,
            native_frames=len(frames),
            timestamp=str(time.time()),
        )
        return ExportResult({
            "success": p.exists() and p.stat().st_size > 0,
            "path": str(p),
            "format": "GIF",
            "frames_count": len(frames),
            "duration": dur,
            "fps": fps,
            "file_size_bytes": p.stat().st_size if p.exists() else 0,
            "manifest": manifest,
        })

    @classmethod
    def render_direct_mp4(
        cls,
        scene_graph: Union[SceneGraph, Scene],
        output_path: str,
        fps: int = 30,
        duration: Optional[float] = None,
        bitrate: str = "4M",
        crf: int = 18,
        asset_loader: Optional[Callable] = None
    ) -> ExportResult:
        """Directly renders full-rate MP4 from scene graph layers using FFmpeg without intermediate GIF."""
        ffmpeg_bin = get_ffmpeg_binary()
        if not ffmpeg_bin:
            raise RuntimeError("FFmpeg executable not found. Direct MP4 render requires local FFmpeg.")

        sg = _ensure_scene_graph(scene_graph)
        dur = duration or sg.scene.duration
        w = sg.canvas_w
        h = sg.canvas_h
        if w % 2 != 0: w -= 1
        if h % 2 != 0: h -= 1

        total_frames = max(1, int(dur * fps))
        step = dur / total_frames

        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{w}x{h}",
            "-pix_fmt", "rgba",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(crf),
            "-b:v", bitrate,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(p),
        ]

        err_log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        err_log.close()

        with open(err_log.name, "wb") as err_f:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=err_f,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            try:
                for i in range(total_frames):
                    t = i * step
                    fr = sg.render_frame(t, asset_loader=asset_loader)
                    if (fr.width, fr.height) != (w, h):
                        fr = fr.resize((w, h), Image.Resampling.BILINEAR)
                    proc.stdin.write(fr.tobytes())
                proc.stdin.close()
                proc.wait(timeout=120)
            except Exception as ex:
                proc.kill()
                raise RuntimeError(f"Direct MP4 encode failed: {str(ex)}")

        manifest = GenerationManifest(
            generator_type="creative-motion-mp4",
            model_id="lexnis-motion-engine",
            steps=1,
            native_width=w,
            native_height=h,
            native_fps=fps,
            native_frames=total_frames,
            timestamp=str(time.time()),
        )
        return ExportResult({
            "success": p.exists() and p.stat().st_size > 0,
            "path": str(p),
            "format": "MP4",
            "frames_count": total_frames,
            "duration": dur,
            "fps": fps,
            "width": w,
            "height": h,
            "file_size_bytes": p.stat().st_size if p.exists() else 0,
            "manifest": manifest,
        })

    render_mp4_direct = render_direct_mp4


exporter = CreativeExporter()
