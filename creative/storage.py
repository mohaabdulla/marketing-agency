"""Secure project persistence and managed asset library storage."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from .schemas import CreativeProject


ROOT_DIR = Path(__file__).resolve().parents[1]
CREATIVE_STORAGE_DIR = ROOT_DIR / "output/creative_projects"
CREATIVE_ASSET_DIR = ROOT_DIR / "output/creative_assets"


class CreativeStorage:
    """Safely manages project JSON persistence and asset file isolation."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or CREATIVE_STORAGE_DIR
        self.asset_dir = CREATIVE_ASSET_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.asset_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_path(self, target: Path) -> Path:
        resolved = target.resolve()
        if not (str(resolved).startswith(str(self.base_dir.resolve())) or str(resolved).startswith(str(self.asset_dir.resolve()))):
            raise PermissionError(f"Access denied: path '{target}' escapes allowed creative storage.")
        return resolved

    def save_project(self, project: CreativeProject) -> str:
        project_file = self.base_dir / f"{project.project_id}.json"
        self._sanitize_path(project_file)
        data = project.to_dict()
        project_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(project_file)

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        safe_id = "".join([c for c in project_id if c.isalnum() or c in "-_"])
        project_file = self.base_dir / f"{safe_id}.json"
        if not project_file.exists():
            return None
        self._sanitize_path(project_file)
        return json.loads(project_file.read_text(encoding="utf-8"))

    def list_projects(self) -> List[Dict[str, Any]]:
        results = []
        for p in self.base_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append({
                    "project_id": data.get("project_id", p.stem),
                    "name": data.get("name", "Untitled"),
                    "version": data.get("version", 1),
                    "updated": data.get("updated", ""),
                    "scenes_count": len(data.get("scenes", [])),
                })
            except Exception:
                continue
        return results

    def register_asset(self, filename: str, data: bytes, mime_type: str = "image/png") -> Dict[str, Any]:
        """Save asset file with content hashing and deduplication."""
        checksum = hashlib.sha256(data).hexdigest()
        asset_id = f"asset_{checksum[:16]}"
        ext = Path(filename).suffix or ".bin"
        asset_file = self.asset_dir / f"{asset_id}{ext}"
        self._sanitize_path(asset_file)

        if not asset_file.exists():
            asset_file.write_bytes(data)

        return {
            "asset_id": asset_id,
            "filename": filename,
            "path": str(asset_file),
            "size_bytes": len(data),
            "mime_type": mime_type,
            "checksum": checksum,
        }


creative_storage = CreativeStorage()

