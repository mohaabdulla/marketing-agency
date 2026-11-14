"""Generative Output Manifest creation, validation, and auditing."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .schemas import GenerationManifest


class ManifestEngine:
    """Creates auditable generation manifests for all creative outputs."""

    @staticmethod
    def create_manifest(
        generator_type: str,
        model_id: str,
        seed: int,
        prompt: str = "",
        model_license: str = "Apache-2.0",
        commercial_status: str = "COMMERCIAL_ALLOWED",
        native_width: int = 1024,
        native_height: int = 1024,
        export_resolution: str = "1080x1080",
        generation_duration_seconds: float = 0.0,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> GenerationManifest:
        # Enforce honest generation type tagging
        valid_types = {
            "ai-image",
            "ai-image-edit",
            "ai-text-to-video",
            "ai-image-to-video",
            "deterministic-motion",
            "transcode",
        }
        gen_type = generator_type if generator_type in valid_types else "deterministic-motion"

        extra = extra_metadata or {}
        return GenerationManifest(
            generator_type=gen_type,
            model_id=model_id,
            model_repo=extra.get("model_repo", ""),
            model_revision=extra.get("model_revision", "main"),
            model_license=model_license,
            commercial_status=commercial_status,
            seed=seed,
            prompt=prompt,
            negative_prompt=extra.get("negative_prompt", ""),
            prompt_compiler_version="1.0",
            input_assets=extra.get("input_assets", []),
            reference_images=extra.get("reference_images", []),
            masks=extra.get("masks", []),
            control_images=extra.get("control_images", []),
            adapter_settings=extra.get("adapter_settings", {}),
            steps=extra.get("steps", 25),
            guidance=extra.get("guidance", 7.5),
            scheduler=extra.get("scheduler", "EulerDiscrete"),
            precision=extra.get("precision", "fp16"),
            device=extra.get("device", "cuda"),
            native_width=native_width,
            native_height=native_height,
            native_fps=extra.get("native_fps", 0),
            native_frames=extra.get("native_frames", 1),
            generation_duration_seconds=generation_duration_seconds,
            post_processing=extra.get("post_processing", []),
            upscale_method=extra.get("upscale_method"),
            crop_method=extra.get("crop_method"),
            export_resolution=export_resolution,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def validate_manifest(manifest: GenerationManifest) -> List[str]:
        warnings = []
        if manifest.generator_type == "transcode" and "ai" in manifest.model_id.lower():
            warnings.append("Transcoded asset should not claim an AI generator model.")
        if manifest.commercial_status == "NON_COMMERCIAL":
            warnings.append("Asset was produced with a non-commercial licensed model.")
        if not manifest.seed and manifest.generator_type.startswith("ai-"):
            warnings.append("AI-generated manifest missing deterministic seed.")
        return warnings

