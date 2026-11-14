"""Forking and intelligent reframing of master video projects into platform variants."""
import copy
from typing import Any, Dict, Literal, Optional
from video_projects import Project, Canvas, Clip
from video_compliance import SAFE_ZONE_PROFILES
from video_storage import uid

TargetAspect = Literal['9:16', '1:1', '4:5', '16:9']

VARIANT_CANVAS_CONFIGS = {
    '9:16': {'width': 1080, 'height': 1920, 'safe_zone': 'vertical-social'},
    '1:1': {'width': 1080, 'height': 1080, 'safe_zone': 'square-social'},
    '4:5': {'width': 1080, 'height': 1350, 'safe_zone': 'vertical-social'},
    '16:9': {'width': 1920, 'height': 1080, 'safe_zone': 'landscape-social'},
}


def create_platform_variant(
    master_project: Project,
    master_project_id: str,
    target_aspect: TargetAspect = '9:16',
    focal_x: float = 0.5,
    focal_y: float = 0.5,
) -> Project:
    """Fork an approved master project into an aspect-ratio variant with safe-zone reframing."""
    config = VARIANT_CANVAS_CONFIGS.get(target_aspect, VARIANT_CANVAS_CONFIGS['9:16'])

    variant_dict = copy.deepcopy(master_project.model_dump())
    variant_dict['name'] = f"{master_project.name[:90]} ({target_aspect})"
    variant_dict['master_project_id'] = master_project_id
    variant_dict['variant_target'] = target_aspect
    variant_dict['safe_zone_profile'] = config['safe_zone']
    variant_dict['status'] = 'draft'

    # Update Canvas
    variant_dict['canvas']['width'] = config['width']
    variant_dict['canvas']['height'] = config['height']

    sz = SAFE_ZONE_PROFILES.get(config['safe_zone'], SAFE_ZONE_PROFILES['generic'])

    # Reframe and reposition elements
    new_clips = []
    for c_dict in variant_dict.get('clips', []):
        cd = dict(c_dict)
        cd['id'] = uid()  # New IDs for cloned clips

        if cd['kind'] == 'video':
            # Adjust crop/scale for focal point if converting wide to tall
            if target_aspect in {'9:16', '4:5'} and master_project.canvas.width > master_project.canvas.height:
                cd['scale'] = min(2.0, cd.get('scale', 1.0) * 1.15)
                cd['x'] = focal_x

        elif cd['kind'] == 'title':
            # Ensure titles remain inside new safe zones
            top_bound = sz['top'] + 0.05
            bottom_bound = 1.0 - sz['bottom'] - 0.05
            cd['y'] = max(top_bound, min(bottom_bound, cd.get('y', 0.5)))
            cd['x'] = 0.5  # Re-center horizontally for social aspect ratios
            # Scale down slightly if font size is too large for vertical canvas
            if target_aspect in {'9:16', '1:1'}:
                cd['font_size'] = max(24, int(cd.get('font_size', 48) * 0.9))

        elif cd['kind'] == 'overlay':
            # Re-anchor logo inside top-right corner of new safe zone
            cd['x'] = round(1.0 - sz['right'] - 0.06, 2)
            cd['y'] = round(sz['top'] + 0.04, 2)
            cd['scale'] = min(0.4, cd.get('scale', 0.4) * 0.9)

        new_clips.append(Clip(**cd))

    variant_dict['clips'] = new_clips
    return Project(**variant_dict)

