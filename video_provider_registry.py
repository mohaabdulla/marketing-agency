"""Operator-visible local provider declarations and graceful performance-tier selection."""
from importlib.util import find_spec
from video_segmentation import MODELS,model_file


def providers():
    records=[]
    for key,value in MODELS.items():
        sam=key=='sam2_tiny'
        checkpoint=model_file(key)
        runtime=bool(find_spec('sam2') and find_spec('torch')) if sam else bool(find_spec('rembg') and find_spec('onnxruntime'))
        records.append(dict(name=key,version='SAM 2.1 image predictor' if sam else 'U-2-Net',checkpoint=checkpoint.name if checkpoint else value['file'],
            license=value['license'],commercial_use_status='PUBLISHED_PERMISSIVE_TERMS_REVIEW_REQUIRED',
            source='https://github.com/facebookresearch/sam2' if sam else 'https://github.com/xuebinqin/U-2-Net',
            ram_estimate_gb=4 if sam else 2,vram_estimate_gb=4 if sam else 0,cpu_support=True,gpu_support=sam,
            privacy='LOCAL_ONLY_NO_INFERENCE_DOWNLOAD',installed=bool(checkpoint),runtime_installed=runtime,
            inference_verified=False if sam else bool(checkpoint and checkpoint.parent.joinpath(key+'.verified.json').is_file()),
            note='Resource estimates are planning allowances, not measured peaks. Model/license availability is not legal clearance. '+value['note']))
    return records


def tier(requested):
    specs=providers()
    enhanced=any(s['installed'] and s['runtime_installed'] for s in specs)
    selected='enhanced-cpu' if enhanced else 'basic-cpu'
    note='CPU deterministic editing remains available.'
    if requested=='basic-cpu':selected='basic-cpu'
    elif requested=='gpu-professional':
        sam=next(s for s in specs if s['name']=='sam2_tiny')
        if sam['installed'] and sam['runtime_installed']:
            # Actual GPU/runtime compatibility is checked by the provider before allocation.
            import os
            if os.getenv('AGENCY_MATTING_MODEL')=='sam2_tiny' and os.getenv('AGENCY_SAM2_DEVICE')=='cuda':
                selected='gpu-professional';note='Configured optional GPU refinement; actual runtime compatibility is validated during inference, quality still needs review.'
            else:note='SAM 2 is not configured as the active CUDA provider; using CPU editing.'
        else:note='Optional SAM 2 checkpoint/runtime is not installed; using CPU editing. Nothing is downloaded automatically.'
    return dict(requested=requested,selected=selected,notice=note,providers=specs)
