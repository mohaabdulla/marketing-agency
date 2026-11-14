"""Creative Studio API router connecting layered scenes, typography, motion, and direct MP4 export."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .schemas import CreativeProject, Scene
from .storage import creative_storage
from .presets import FORMAT_PRESETS, MOTION_PRESETS, build_preset_scene
from .scene import SceneGraph
from .exports import CreativeExporter
from .qa import CreativeQAEngine

router = APIRouter(prefix="/api/creative", tags=["creative"])
exporter = CreativeExporter()
qa_engine = CreativeQAEngine()


class ProjectSaveRequest(BaseModel):
    project: Dict[str, Any]


class RenderRequest(BaseModel):
    project: Optional[Dict[str, Any]] = None
    project_id: Optional[str] = None
    scene_id: Optional[str] = None
    t: float = 0.0
    fps: int = 30
    bitrate: str = "4M"
    format: str = "png"
    optimize_palette: bool = True


class QAAuditRequest(BaseModel):
    project: Optional[Dict[str, Any]] = None
    project_id: Optional[str] = None


class BridgeToVideoRequest(BaseModel):
    output_path: str
    name: Optional[str] = None


def _resolve_scene(req: RenderRequest | QAAuditRequest) -> Scene:
    proj_data = req.project
    if not proj_data and req.project_id:
        proj_data = creative_storage.load_project(req.project_id)
        if not proj_data:
            raise HTTPException(404, f"Project '{req.project_id}' not found")
    if not proj_data:
        raise HTTPException(400, "Must provide 'project' or 'project_id'")

    project = CreativeProject.from_dict(proj_data)
    if not project.scenes:
        raise HTTPException(400, "Project has no scenes")

    scene_id = getattr(req, "scene_id", None)
    if scene_id:
        scene = next((s for s in project.scenes if s.scene_id == scene_id), None)
        if not scene:
            raise HTTPException(404, f"Scene '{scene_id}' not found in project")
        return scene
    return project.scenes[0]


@router.get("/presets")
def get_presets():
    """List supported canvas dimensions and deterministic motion presets."""
    return {
        "formats": FORMAT_PRESETS,
        "motion_presets": list(MOTION_PRESETS.keys()),
    }


@router.get("/projects")
def list_projects():
    """List all saved creative projects."""
    return {"projects": creative_storage.list_projects()}


@router.post("/projects")
def save_project(req: ProjectSaveRequest):
    """Save or update a creative project."""
    try:
        project = CreativeProject.from_dict(req.project)
        path = creative_storage.save_project(project)
        return {"status": "ok", "project_id": project.project_id, "path": path}
    except Exception as exc:
        raise HTTPException(400, f"Invalid creative project: {exc}")


@router.get("/projects/{project_id}")
def load_project(project_id: str):
    """Load a creative project by ID."""
    proj = creative_storage.load_project(project_id)
    if not proj:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return proj


@router.post("/qa/audit")
def audit_project(req: QAAuditRequest):
    """Perform pre-flight creative QA audit."""
    scene = _resolve_scene(req)
    report = qa_engine.audit_scene(scene)
    return {
        "scene_id": scene.scene_id,
        "passed": report.passed,
        "findings_count": len(report.findings),
        "findings": [f.to_dict() for f in report.findings],
    }


@router.post("/render/still")
def render_still(req: RenderRequest):
    """Render a single high-resolution still frame at timestamp t."""
    scene = _resolve_scene(req)
    out_dir = Path("output/creative_renders")
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if req.format.lower() in ("jpg", "jpeg") else "png"
    out_file = out_dir / f"{scene.scene_id}_t{int(req.t*1000)}.{ext}"

    result = exporter.render_still(scene, t=req.t, output_path=out_file)
    return {
        "status": "ok",
        "output_path": str(out_file),
        "manifest": result.manifest.to_dict(),
    }


@router.post("/render/gif")
def render_gif(req: RenderRequest):
    """Render an animated GIF with palette optimization from the scene graph."""
    scene = _resolve_scene(req)
    out_dir = Path("output/creative_renders")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{scene.scene_id}.gif"

    fps = max(5, min(req.fps, 30))
    result = exporter.render_gif(scene, output_path=out_file, fps=fps, optimize_palette=req.optimize_palette)
    return {
        "status": "ok",
        "output_path": str(out_file),
        "manifest": result.manifest.to_dict(),
    }


@router.post("/render/mp4")
def render_mp4(req: RenderRequest):
    """Render a direct broadcast-quality MP4 via FFmpeg rawvideo pipe without intermediate GIF."""
    scene = _resolve_scene(req)
    out_dir = Path("output/creative_renders")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{scene.scene_id}.mp4"

    fps = max(10, min(req.fps, 60))
    result = exporter.render_mp4_direct(scene, output_path=out_file, fps=fps, bitrate=req.bitrate)
    return {
        "status": "ok",
        "output_path": str(out_file),
        "manifest": result.manifest.to_dict(),
    }


@router.post("/bridge-to-video")
def bridge_to_video(req: BridgeToVideoRequest):
    """Ingest a rendered still, GIF, or direct MP4 into Video Studio's managed media library."""
    file_path = Path(req.output_path)
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {req.output_path}")

    try:
        from video_assets import ingest
        name = req.name or file_path.name
        if not Path(name).suffix and file_path.suffix:
            name = f"{name}{file_path.suffix}"
        asset = ingest(file_path, name=name)
        return {
            "status": "ok",
            "asset_id": asset["id"],
            "kind": asset["kind"],
            "name": asset["name"],
        }
    except Exception as exc:
        raise HTTPException(500, f"Failed to ingest into Video Studio: {exc}")
