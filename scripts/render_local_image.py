"""Runs only inside the isolated CUDA environment, never the server's Python."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def render(request_path):
    import torch
    from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable in the local image runtime.')
    pipe = StableDiffusionXLPipeline.from_pretrained(
        ROOT / '.model-cache' / 'segmind-vega', torch_dtype=torch.float16,
        variant='fp16', use_safetensors=True, local_files_only=True,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
    image = pipe(
        prompt=request['prompt'],
        negative_prompt='illustration, painting, cartoon, CGI, plastic, deformed car, duplicate vehicle, extra wheels, text, watermark, blurry, low quality',
        width=request['width'], height=request['height'],
        num_inference_steps=28, guidance_scale=9.0,
        generator=torch.Generator('cpu').manual_seed(request['seed']),
    ).images[0]
    image.save(request['output'], format='JPEG', quality=95)
    print(json.dumps({'image': request['output'], 'device': torch.cuda.get_device_name(0)}))

if __name__ == '__main__':
    render(sys.argv[1])
