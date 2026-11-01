"""Runs only inside the isolated CUDA environment, never the server's Python."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def render(request_path):
    import faulthandler
    faulthandler.enable()
    print('Initializing local image libraries...', flush=True)
    import torch
    from scripts.windows_tensor_reader import configure_windows_tensor_reader
    reader = configure_windows_tensor_reader()
    print('Checkpoint reader:', reader, flush=True)
    from PIL import Image, ImageStat, ImageOps
    from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline, DPMSolverMultistepScheduler
    from visual_engine import LOCAL_MODELS, LOCAL_MODEL, REALISM_MODEL, photography_conditioning

    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    started = time.monotonic()
    model = request.get('model', LOCAL_MODEL)
    quality = model == REALISM_MODEL
    weights = ROOT / '.model-cache' / LOCAL_MODELS[model]['directory']
    if quality and (weights / 'streamed' / 'model_index.json').exists():
        weights = weights / 'streamed'
    download = weights / '.download.json'
    variant = json.loads(download.read_text(encoding='utf-8')).get('variant') if download.exists() else 'fp16'
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable in the local image runtime.')
    print('Loading local checkpoint:', model, flush=True)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        weights, torch_dtype=torch.float16,
        variant=variant, use_safetensors=True, local_files_only=True,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config,
        algorithm_type='sde-dpmsolver++' if quality else 'dpmsolver++',
        use_karras_sigmas=quality, solver_order=2)
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    if quality:
        prompt, prompt_2, negative, truncated = photography_conditioning(request['prompt'], pipe.tokenizer, pipe.tokenizer_2)
    else:
        prompt = prompt_2 = request['prompt']
        negative = 'illustration, painting, cartoon, CGI, plastic, deformed car, duplicate vehicle, extra wheels, text, watermark, blurry, low quality'
        truncated = False
    steps, guidance = (36, 5.0) if quality else (28, 9.0)
    print('Base render:', request['width'], request['height'], 'steps:', steps, flush=True)
    image = pipe(
        prompt=prompt, prompt_2=prompt_2, negative_prompt=negative,
        width=request['width'], height=request['height'],
        num_inference_steps=steps, guidance_scale=guidance,
        generator=torch.Generator('cpu').manual_seed(request['seed']),
    ).images[0]
    if quality:
        # Share the checkpoint components instead of loading another model into
        # the 8 GB GPU. Low denoise retains composition while rebuilding detail.
        image.save(str(Path(request['output']).with_name('base.jpg')), quality=95)
        pipe.remove_all_hooks()
        refine = StableDiffusionXLImg2ImgPipeline(**pipe.components)
        refine.scheduler = DPMSolverMultistepScheduler.from_config(refine.scheduler.config,
            algorithm_type='dpmsolver++', use_karras_sigmas=True, solver_order=2)
        refine.enable_model_cpu_offload()
        refine.vae.enable_slicing()
        refine.vae.enable_tiling()
        target = (request.get('output_width', request['width']), request.get('output_height', request['height']))
        target = tuple(max(64, min(1536, size // 8 * 8)) for size in target)
        initial = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS)
        print('Detail pass:', target, 'denoise: 0.2', flush=True)
        image = refine(prompt=prompt, prompt_2=prompt_2, negative_prompt=negative,
            image=initial, strength=.20, num_inference_steps=50, guidance_scale=4.5,
            generator=torch.Generator('cpu').manual_seed(request['seed'] + 1)).images[0]
    if max(ImageStat.Stat(image.convert('RGB')).stddev) < 8:
        raise RuntimeError('Image render is blank or numerically unstable; output was not saved.')
    image.save(request['output'], format='JPEG', quality=95)
    metadata = dict(model=model, seed=request['seed'], native_size=[request['width'], request['height']],
        output_size=list(image.size), steps=steps, guidance=guidance,
        refinement_strength=.20 if quality else 0, effective_prompt=prompt,
        effective_prompt_2=prompt_2, prompt_compacted=truncated,
        elapsed_seconds=round(time.monotonic()-started, 1), device=torch.cuda.get_device_name(0), checkpoint_reader=reader,
        checkpoint_sharded=weights.name == 'streamed')
    metadata['conditioning_tokens'] = [len(pipe.tokenizer.encode(prompt)), len(pipe.tokenizer_2.encode(prompt_2))]
    Path(request['output']).with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata), flush=True)

if __name__ == '__main__':
    render(sys.argv[1])
