"""Photographic direction, layout and optional open-weight image inference."""
import io
import os
import re
import threading
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_MODEL = 'local:segmind-vega'
LOCAL_PYTHON = ROOT / '.venv-image' / 'Scripts' / 'python.exe'
LOCAL_WEIGHTS = ROOT / '.model-cache' / 'segmind-vega'
REALISM_MODEL = 'local:realvisxl-v5'
LOCAL_MODELS = {
    LOCAL_MODEL: {'directory': 'segmind-vega', 'label': 'Segmind Vega — fast local GPU'},
    REALISM_MODEL: {'directory': 'realvisxl-v5', 'label': 'RealVisXL 5 — photographic detail, local GPU'},
}
RENDER_VERSION = 'photo-v5-realism'


def local_model_ready(model=LOCAL_MODEL):
    if model not in LOCAL_MODELS:
        return False
    weights = ROOT / '.model-cache' / LOCAL_MODELS[model]['directory']
    return LOCAL_PYTHON.exists() and (weights / '.ready').exists() and (weights / 'model_index.json').exists()


def preferred_local_model():
    return next((model for model in (REALISM_MODEL, LOCAL_MODEL) if local_model_ready(model)), None)


def local_render_dimensions(width, height, model=LOCAL_MODEL):
    ratio = width / height
    if model == REALISM_MODEL:
        return (1344, 768) if ratio > 1.3 else ((896, 1152) if ratio < .9 else (1024, 1024))
    return (1024, 576) if ratio > 1.3 else ((768, 960) if ratio < .9 else (896, 896))


def photography_conditioning(prompt, tokenizer, tokenizer_2):
    """Respect CLIP's 77-token budget and reserve room for photographic direction."""
    cleaned = re.sub(r'\b(?:cinematic|hyperrealistic|ultrarealistic|masterpiece|8k|16k|unreal engine|luxury)\b', '', prompt, flags=re.I)
    cleaned = ' '.join(cleaned.split()).strip(' ,.')
    suffix = ', professional photograph, natural color, balanced exposure, realistic surface texture'
    budget = min(tokenizer.model_max_length, tokenizer_2.model_max_length, 77) - 2

    def compact(text, tail='', main_budget=budget):
        content = text
        while content and any(len(tok.encode(content.rstrip(' ,.') + tail, add_special_tokens=False)) > main_budget for tok in (tokenizer, tokenizer_2)):
            content = content.rsplit(' ', 1)[0] if ' ' in content else content[:-1]
        return content.rstrip(' ,.') + tail

    primary = compact(cleaned, suffix)
    secondary = compact('Natural product photograph. ' + cleaned,
        ', subtle reflections, believable perspective, detailed materials')
    negative = compact('CGI, 3d render, illustration, painting, plastic, waxy, oversaturated, HDR, excessive bloom, crushed shadows, distorted geometry, duplicate wheels, melted panels, illegible logo, text, watermark, oversharpened')
    return primary, secondary, negative, primary != cleaned + suffix


def local_image(prompt, seed, width, height, require_ready=True, model=LOCAL_MODEL):
    if model not in LOCAL_MODELS:
        raise RuntimeError('Unsupported local image model.')
    if require_ready and not local_model_ready(model):
        raise RuntimeError(model_setup(model)['message'])
    # Render within the laptop GPU's memory budget, then the main pipeline resizes
    # to the exact export size. Each subprocess releases CUDA memory on completion.
    (ROOT / 'output').mkdir(exist_ok=True)
    output_width, output_height = width, height
    width, height = local_render_dimensions(width, height, model)
    with _local_lock, tempfile.TemporaryDirectory(prefix='lexnis-render-', dir=ROOT / 'output') as directory:
        output = Path(directory) / 'image.jpg'
        request = Path(directory) / 'request.json'
        request.write_text(json.dumps(dict(prompt=prompt, seed=seed, width=width, height=height, output=str(output),
            model=model, output_width=output_width, output_height=output_height)), encoding='utf-8')
        try:
            # Persist progress while the GPU works; model loading and diffusion
            # should be distinguishable from a stalled subprocess.
            with (ROOT / 'output' / 'local-render-progress.log').open('w', encoding='utf-8') as log:
                result = subprocess.run([str(LOCAL_PYTHON), '-u', str(ROOT / 'scripts' / 'render_local_image.py'), str(request)],
                    cwd=ROOT, stdout=log, stderr=log, timeout=900,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not output.exists():
                details = (ROOT / 'output' / 'local-render-progress.log').read_text(encoding='utf-8')
                details += f'\nWorker exit code: {result.returncode} (0x{result.returncode & 0xffffffff:08x})\n'
                (ROOT / 'output' / 'local-render-error.log').write_text(details, encoding='utf-8')
                raise RuntimeError('Local GPU rendering failed. See output/local-render-error.log for details.')
            metadata = output.with_suffix('.json')
            if metadata.exists():
                (ROOT / 'output' / 'latest-local-render.json').write_bytes(metadata.read_bytes())
            base = Path(directory) / 'base.jpg'
            if base.exists():
                (ROOT / 'output' / 'latest-local-base.jpg').write_bytes(base.read_bytes())
            return output.read_bytes(), True
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Local image generation exceeded fifteen minutes. Retry with other GPU applications closed.') from exc

FORMATS = {"portrait": (1080, 1350), "landscape": (1536, 864), "square": (1080, 1080)}
OPEN_MODELS = {
    "hf:Tongyi-MAI/Z-Image-Turbo": "Z-Image Turbo — open weights (Apache 2.0)",
    "hf:Qwen/Qwen-Image-2512": "Qwen Image 2512 — open weights (Apache 2.0)",
    "hf:black-forest-labs/FLUX.1-schnell": "FLUX.1 Schnell — open weights (Apache 2.0)",
}
_pipelines = {}
_local_lock = threading.Lock()


def model_setup(model):
    """Credential readiness only; never imply that quotas or remote health were tested."""
    if model in LOCAL_MODELS:
        ready = local_model_ready(model)
        message = ('Install the photographic checkpoint with python scripts/setup_realism_model.py and enable it with python scripts/verify_realism_images.py --activate.'
                   if model == REALISM_MODEL else 'Install and verify the local image engine with python scripts/setup_local_images.py.')
    elif model == "cf:flux-schnell":
        ready = bool(os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"))
        message = "Add CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to .env, then restart python server.py."
    elif model.startswith("hf:"):
        local = os.getenv("IMAGE_PROVIDER") == "local"
        ready = local or bool(os.getenv("HF_TOKEN"))
        message = "Set HF_TOKEN for hosted inference, or configure IMAGE_PROVIDER=local and install the local model dependencies."
    elif model == "gemini-image":
        ready = bool(os.getenv("GEMINI_API_KEY"))
        message = "Set GEMINI_API_KEY in .env and restart the server. Image access requires separate image quota."
    else:
        ready = bool(os.getenv("POLLINATIONS_API_KEY"))
        message = "Set POLLINATIONS_API_KEY in .env and restart the server, or select a configured image provider."
    if ready:
        message = ('Local GPU engine verified. Generates on this computer without API keys.'
                   if model in LOCAL_MODELS else 'Provider configured; availability depends on model access and quota.')
    return {"configured": ready, "message": message}


def cloudflare_image(prompt, seed):
    import base64
    import requests
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not account or not token:
        raise RuntimeError("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env for FLUX Schnell's free daily allowance, then restart the server.")
    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {token}"},
            json={"prompt": prompt[:2048], "steps": 4, "seed": seed}, timeout=120,
        )
        if response.ok:
            data = response.json()
            if data.get("success") and data.get("result", {}).get("image"):
                return base64.b64decode(data["result"]["image"]), True
    except requests.RequestException:
        pass
    raise RuntimeError("Cloudflare image generation failed. Check account/token permissions and daily allowance.")


def photo_direction(request, theme="", brand=""):
    """Preserve the requested product and scene instead of substituting a flagship."""
    subject = re.sub(r"https?://\S+", "", request).strip()[:1200]
    outdoor = any(word in (theme + " " + request).lower()
                  for word in ("coast", "sunset", "road", "lifestyle", "outdoor", "cinematic"))
    scene = ("On a winding coastal road above the ocean at golden hour, warm sunset sky, "
             "natural reflections, believable shadows, neutral photographic color and balanced exposure. "
             "For a vehicle use a low front three-quarter tracking shot, entire vehicle visible, "
             "sharp body with subtle wheel and road motion blur, 35mm lens."
             if outdoor else
             "Use a setting appropriate to the product and the requested visual direction. "
             "Soft directional key light, realistic material reflections and contact shadows, "
             "50mm commercial photography, believable proportions.")
    return (f"Premium advertising photograph for {brand}. Subject and campaign: {subject}. "
            f"Visual direction: {theme}. {scene} "
            "Product is the hero in the middle of the frame. Keep the upper left and lower right "
            "quiet for separately typeset advertising copy. Preserve the exact requested model, "
            "color and silhouette. Photographic detail, natural dynamic range. "
            "No added typography, letters, captions, watermarks, wireframes or geometric placeholders.")


def open_model_image(prompt, seed, model, width, height):
    """No silent model changes. Local inference is explicit and downloads are opt-in."""
    model_id = model.removeprefix("hf:")
    if model not in OPEN_MODELS:
        raise RuntimeError("Select a supported open-weight image model.")
    if os.getenv("IMAGE_PROVIDER", "huggingface") == "local":
        try:
            import torch
            from diffusers import DiffusionPipeline
        except ImportError as exc:
            raise RuntimeError("Install requirements-local.txt to use local image models.") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("Local image inference requires a compatible CUDA GPU. Use a hosted provider instead.")
        with _local_lock:
            if model_id not in _pipelines:
                pipe = DiffusionPipeline.from_pretrained(
                    model_id, torch_dtype=torch.bfloat16,
                    local_files_only=os.getenv("ALLOW_MODEL_DOWNLOAD", "0") != "1",
                )
                pipe.enable_model_cpu_offload()
                _pipelines.clear()
                _pipelines[model_id] = pipe
            kwargs = {"num_inference_steps": 9, "guidance_scale": 0.0}
            if "FLUX" in model_id:
                kwargs = {"num_inference_steps": 4, "guidance_scale": 0.0, "max_sequence_length": 256}
            elif "Qwen" in model_id:
                kwargs = {"num_inference_steps": 50, "true_cfg_scale": 4.0, "negative_prompt": " "}
            result = _pipelines[model_id](prompt=prompt, width=width, height=height,
                generator=torch.Generator("cpu").manual_seed(seed), **kwargs).images[0]
    else:
        token = os.getenv("HF_TOKEN", "")
        if not token:
            raise RuntimeError("Set HF_TOKEN for hosted inference, or IMAGE_PROVIDER=local for free local weights. Hosted inference may require credits.")
        try:
            from huggingface_hub import InferenceClient
            result = InferenceClient(provider=os.getenv("HF_PROVIDER", "auto"), api_key=token,
                timeout=120).text_to_image(prompt, model=model_id, width=width, height=height, seed=seed)
        except Exception as exc:
            # Provider exceptions may contain authorization headers. Do not expose them.
            raise RuntimeError("Hosted image inference failed. Check model/provider availability, HF token permission and credits.") from exc
    buffer = io.BytesIO()
    result.convert("RGB").save(buffer, format="JPEG", quality=95)
    return buffer.getvalue(), True


def compose_ad(image, headline="", brand="", tagline=""):
    """Restrained typography in reserved corners; no telemetry on customer artwork."""
    from PIL import Image, ImageDraw
    from campaign_generator import _load_font, _wrap
    image = image.convert("RGBA")
    width, height = image.size
    layer = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(layer)
    pad = round(min(width, height) * .065)
    for y in range(height):
        top = max(0, 1 - y / (height * .32))
        bottom = max(0, (y - height * .67) / (height * .33))
        draw.line((0, y, width, y), fill=(0, 0, 0, round(85 * max(top, bottom))))
    max_width = width - pad * 2

    def lines(text, size, limit):
        text = " ".join(text.replace("//", " ").split()).upper()[:160]
        while size > 12:
            font = _load_font(size)
            wrapped = _wrap(draw, text, font, max_width)
            if len(wrapped) <= limit and all(draw.textlength(line, font=font) <= max_width for line in wrapped):
                return wrapped, font, size
            size -= 1
        return _wrap(draw, text, _load_font(size), max_width)[:limit], _load_font(size), size

    brand_lines, font, size = lines(brand, round(height * .030), 2)
    y = pad
    for line in brand_lines:
        draw.text((pad, y), line, font=font, fill="white")
        y += round(size * 1.3)
    title_lines, font, size = lines(headline, round(height * .052), 2)
    tag_lines, tag_font, tag_size = lines(tagline, round(height * .022), 2)
    y = height - pad - len(title_lines) * round(size * 1.25) - len(tag_lines) * round(tag_size * 1.4)
    for line in title_lines:
        draw.text((width-pad-draw.textlength(line, font=font), y), line, font=font, fill="white")
        y += round(size * 1.25)
    for line in tag_lines:
        draw.text((width-pad-draw.textlength(line, font=tag_font), y), line, font=tag_font, fill="white")
        y += round(tag_size * 1.4)
    return Image.alpha_composite(image, layer).convert("RGB")
