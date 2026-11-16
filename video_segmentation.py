"""Optional subject matting for background treatment. Local, explicit install, cached masks.

The provider interface keeps the matting model replaceable. The bundled provider uses rembg
(MIT) with a U-2-Net checkpoint (Apache-2.0) that is only present after an operator runs
scripts/setup_video_matting.py. Nothing is downloaded at startup or on demand.

A mask is a per-frame matte, not tracking: it has no identity or demographic information and
is used only to separate a person from the background.
"""
import hashlib
import json
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from video_storage import DATA, ROOT, read, atomic
from video_assets import path_for
from video_ffmpeg import ffmpeg, Cancelled

MODEL_DIR = Path(os.environ.get('AGENCY_MATTING_MODEL_DIR', str(ROOT / '.model-cache/video-matting')))
MODELS = {
    'u2net_human_seg': dict(file='u2net_human_seg.onnx', label='U-2-Net human segmentation', license='Apache-2.0 (U-2-Net)',
                            runtime='rembg (MIT) + onnxruntime CPU', disk_mb=168, note='Best of the bundled options for people.'),
    'u2netp': dict(file='u2netp.onnx', label='U-2-Net small', license='Apache-2.0 (U-2-Net)', runtime='rembg (MIT) + onnxruntime CPU',
                   disk_mb=5, note='Fast and small; rougher edges.'),
    'sam2_tiny': dict(file='sam2.1_hiera_tiny.pt',label='SAM 2.1 tiny image refinement',license='Apache-2.0 (SAM 2 checkpoints; published terms, not legal clearance)',
                     runtime='Operator-installed sam2 + PyTorch, with U-2-Net seed',disk_mb=156,
                     note='Optional image-anchor refinement plus optical flow; not verified here and not optical alpha matting.'),
}
MAX_SECONDS = 90
CACHE_VERSION = 3
LOCK = threading.Lock()
_sessions = {}


def model_file(name):
    """Checkpoint path. rembg versions store it either directly in the folder or under models/<name>/."""
    file = MODELS[name]['file']
    return next((p for p in (MODEL_DIR / 'models' / name / file, MODEL_DIR / file) if p.is_file()), None)


def installed_model():
    name = os.environ.get('AGENCY_MATTING_MODEL', '')
    candidates = [name] if name in MODELS else list(MODELS)
    return next((key for key in candidates if model_file(key)), None)


def status():
    model = installed_model()
    try:
        # Capabilities must not import every optional rembg backend (including
        # torch/CUDA) just to paint a settings menu. Inference validates the runtime.
        from importlib.util import find_spec
        runtime = find_spec('rembg') is not None and find_spec('onnxruntime') is not None
        if model=='sam2_tiny':runtime=runtime and find_spec('sam2') is not None and find_spec('torch') is not None and bool(model_file('u2net_human_seg'))
    except Exception:
        runtime = False
    ready = bool(model and runtime)
    return dict(available=ready, model=model, details=MODELS.get(model),
                reason='Subject-aware background editing is available.' if ready else
                'Subject-aware background editing requires the optional segmentation model. '
                'Run: python scripts/setup_video_matting.py (one explicit download; nothing is fetched automatically).',
                models=MODELS, privacy='Runs locally on CPU; frames never leave this machine.')


class RembgProvider:
    """One matte per frame from a locally installed U-2-Net checkpoint."""
    can_propagate = True
    def __init__(self, model):
        os.environ['U2NET_HOME'] = str(MODEL_DIR)       # rembg reads the checkpoint from here; the file already exists
        import rembg
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(8, int(os.environ.get('AGENCY_MATTING_THREADS', '4'))))
        options.inter_op_num_threads = 1
        from rembg.sessions import sessions_class
        base = next(cls for cls in sessions_class if cls.name() == model)
        checkpoint = model_file(model)
        # rembg.new_session normally calls a downloader, even during inference.
        # Override that hook locally: a missing/corrupt operator-installed file
        # fails locally and can never trigger an implicit network request.
        class LocalCheckpointSession(base):
            @classmethod
            def download_models(cls, *args, **kwargs):
                if not checkpoint or not checkpoint.is_file():
                    raise ValueError('The local subject-matting checkpoint is missing. Run the explicit setup script.')
                return checkpoint
        self.model, self.session, self.rembg = model, LocalCheckpointSession(model, options, providers=['CPUExecutionProvider']), rembg

    def mask(self, rgb):
        from PIL import Image
        import numpy as np
        return np.array(self.rembg.remove(Image.fromarray(rgb), session=self.session, only_mask=True))


def provider():
    model = installed_model()
    if not status()['available']:
        raise ValueError(status()['reason'])
    checkpoint = model_file(model)
    version = _checkpoint_hash(str(checkpoint), checkpoint.stat().st_size, checkpoint.stat().st_mtime_ns)
    key = (model, version)
    with LOCK:
        if key not in _sessions:
            if model=='sam2_tiny':
                from video_sam2 import Sam2Provider
                session=Sam2Provider(checkpoint,RembgProvider('u2net_human_seg'))
            else:
                session = RembgProvider(model)
            _sessions.clear()  # active jobs retain their own reference; avoid accumulating old model weights
            _sessions[key] = session
        return _sessions[key]


@lru_cache(maxsize=8)
def _checkpoint_hash(path, size, modified):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _key(asset_id, mask_fps):
    source = path_for(asset_id)
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    model = installed_model()
    checkpoint = model_file(model) if model in MODELS else None
    version = _checkpoint_hash(str(checkpoint), checkpoint.stat().st_size, checkpoint.stat().st_mtime_ns) if checkpoint else 'test-provider'
    return f'{asset_id}-{digest.hexdigest()[:16]}-{model}-{version}-v{CACHE_VERSION}-{mask_fps}'


def cached_mask(asset_id, mask_fps=12):
    """(mask video path, metadata) when a mask for this exact source, model and rate exists."""
    if not installed_model():
        return None
    folder = DATA / 'masks'
    key = _key(asset_id, mask_fps)
    video, meta = folder / (key + '.mp4'), folder / (key + '.json')
    if video.is_file() and meta.is_file():
        return video, json.loads(meta.read_text(encoding='utf-8'))
    return None


def propagate_mask(previous_gray, current_gray, matte):
    """Warp the previous matte with measured backward optical flow between neural anchors.

    Large movement or a high photometric residual asks for fresh inference instead.
    This is short-range propagation, not identity tracking or a generative prediction.
    """
    import cv2
    import numpy as np
    flow = cv2.calcOpticalFlowFarneback(current_gray, previous_gray, None, .5, 3, 21, 3, 5, 1.2, 0)
    yy, xx = np.mgrid[:matte.shape[0], :matte.shape[1]].astype('float32')
    xmap, ymap = xx + flow[:, :, 0], yy + flow[:, :, 1]
    predicted = cv2.remap(matte, xmap, ymap, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    reconstructed = cv2.remap(previous_gray, xmap, ymap, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    region = predicted > 127
    residual = float(np.mean(np.abs(reconstructed.astype('float32') - current_gray)[region])) if region.any() else 255.
    movement = float(np.percentile(np.linalg.norm(flow[region], axis=1), 95)) if region.any() else 100.
    return predicted, bool(residual < 18 and movement < min(matte.shape) * .025)


def subject_mask(asset_id, job=None, mask_fps=12):
    """Create (or reuse) a greyscale matte video for a managed video asset.

    Returns (path, metadata). Metadata reports temporal stability measured on the mattes:
    mean intersection-over-union between consecutive masks and the number of abrupt coverage
    jumps, so flicker is visible before anything is rendered with the mask.
    """
    existing = cached_mask(asset_id, mask_fps)
    if existing:
        return existing
    import cv2
    import numpy as np
    asset = read('assets', asset_id)
    if asset['kind'] != 'video':
        raise ValueError('Subject masks are created for video assets')
    if asset['duration'] > MAX_SECONDS:
        raise ValueError(f'Subject masking is limited to {MAX_SECONDS} seconds of source video')
    engine = provider()
    from contextlib import ExitStack
    lease=ExitStack()
    source = path_for(asset_id)
    folder = DATA / 'masks'
    folder.mkdir(exist_ok=True)
    key = _key(asset_id, mask_fps)
    capture = cv2.VideoCapture(str(source))
    total = max(1, int(asset['duration'] * mask_fps))
    scale = min(1.0, getattr(engine,'preferred_analysis_edge',480) / max(asset['width'], asset['height']))
    size = (max(2, int(asset['width'] * scale / 2) * 2), max(2, int(asset['height'] * scale / 2) * 2))
    ious, coverage, edge_uncertainty, jumps, previous = [], [], [], 0, None
    previous_gray, inferred, propagated, since_anchor = None, 0, 0, 0
    anchor_stride = max(1, mask_fps // 3)  # at most ~0.33s between fresh neural anchors
    if getattr(engine,'uses_gpu',False):
        from gpu_resources import gpu_slot
        lease.enter_context(gpu_slot(job.cancelled if job else lambda:False))
    try:
        with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='mask-') as tmp:
            tmp = Path(tmp)
            for index in range(total):
                if job and job.cancelled():
                    raise Cancelled()
                capture.set(cv2.CAP_PROP_POS_MSEC, index / mask_fps * 1000)
                ok, frame = capture.read()
                if not ok:
                    if previous is None:
                        raise ValueError('The source video could not be decoded for masking')
                    matte = previous
                else:
                    rgb = cv2.cvtColor(cv2.resize(frame, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                    trusted = False
                    if getattr(engine, 'can_propagate', False) and previous_gray is not None and since_anchor < anchor_stride - 1:
                        matte, trusted = propagate_mask(previous_gray, gray, previous)
                    if trusted:
                        propagated += 1
                        since_anchor += 1
                    else:
                        matte = engine.mask(rgb)
                        inferred += 1
                        since_anchor = 0
                    previous_gray = gray
                binary = matte > 127
                share = float(binary.mean())
                if previous is not None:
                    before = previous > 127
                    union = np.logical_or(binary, before).sum()
                    ious.append(float(np.logical_and(binary, before).sum() / union) if union else 1.0)
                    if abs(share - coverage[-1]) > 0.08:
                        jumps += 1
                coverage.append(share)
                edge_uncertainty.append(float(((matte>25)&(matte<230)).mean()))
                previous = matte
                cv2.imwrite(str(tmp / f'{index:05d}.png'), matte)
                if job and index % 12 == 0:
                    job.update(state='running', phase='Generating subject masks', progress={'frames': index + 1, 'total_frames': total})
            video = tmp / 'mask.mp4'
            ffmpeg(['-framerate', str(mask_fps), '-i', str(tmp / '%05d.png'), '-c:v', 'libx264', '-crf', '14', '-preset', 'veryfast',
                    '-pix_fmt', 'yuv420p', str(video)], job, timeout=300)
            final = folder / (key + '.mp4')
            video.replace(final)
    finally:
        capture.release()
        try:
            if hasattr(engine,'release'):engine.release()
        finally:lease.close()
    stability = sum(ious) / len(ious) if ious else None
    meta = dict(asset_id=asset_id, model=engine.model, license=MODELS[engine.model]['license'], mask_fps=mask_fps, frames=total,
                inferred_frames=inferred, propagated_frames=propagated, cache_version=CACHE_VERSION,
                size=list(size), mean_coverage=round(sum(coverage) / len(coverage), 4), min_coverage=round(min(coverage), 4),
                temporal_iou=round(stability, 4) if stability is not None else None, coverage_jumps=jumps,
                stable=bool(stability is not None and stability >= 0.88 and jumps <= max(1, total // 60)),
                subject_found=bool(0.03 <= sum(coverage) / len(coverage) <= 0.92),
                isolation=dict(coarse_mask='U2NET_SEED' if engine.model=='sam2_tiny' else 'U2NET_PROBABILITY',
                    refined_mask='SAM2_IMAGE_PROMPT' if engine.model=='sam2_tiny' else 'NOT_AVAILABLE',
                    alpha_matte='SOFT_SEGMENTATION_PROBABILITY_NOT_OPTICAL_MATTING',
                    uncertain_edge_share=round(sum(edge_uncertainty)/len(edge_uncertainty),5),hair_edge_confidence=None,
                    motion_edge_confidence=None,ears_fingers_clothing_quality='HUMAN_REVIEW_REQUIRED',
                    warning='Temporal IoU measures consistency, not hair/hand realism. Inspect soft edges and motion blur.'),
                note='Masks use reduced-resolution neural anchors with short-range optical-flow propagation; fast or uncertain movement triggers fresh inference. Edges are feathered; inspect hair and gestures.')
    atomic(folder / (key + '.json'), meta)
    return final, meta
