"""Isolated inference only. Never imported by the web server; never downloads weights."""
import gc
import json
import os
import sys
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'


def build_pipeline(request, torch, diffusers):
    """Mode-specific adapters, injectable for lightweight contract tests."""
    if request['model'] == 'cogvideox-2b':
        if request['mode'] != 'text-to-video':
            raise ValueError('CogVideoX-2B is text-only')
        pipe = diffusers.CogVideoXPipeline.from_pretrained(request['model_path'], torch_dtype=torch.float16,
                                                          local_files_only=True, use_safetensors=True)
    elif request['model'] == 'wan21-i2v-480p':
        if request['mode'] != 'image-to-video' or not request.get('image'):
            raise ValueError('Wan I2V requires a starting image')
        vae = diffusers.AutoencoderKLWan.from_pretrained(request['model_path'], subfolder='vae',
                                                        torch_dtype=torch.float32, local_files_only=True)
        pipe = diffusers.WanImageToVideoPipeline.from_pretrained(request['model_path'], vae=vae,
            torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True)
    else:
        raise ValueError('Unsupported model')
    pipe.enable_sequential_cpu_offload()
    if hasattr(pipe.vae, 'enable_slicing'):
        pipe.vae.enable_slicing()
    if hasattr(pipe.vae, 'enable_tiling'):
        pipe.vae.enable_tiling()
    return pipe


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    import torch
    import diffusers
    from diffusers.utils import export_to_video, load_image
    if not torch.cuda.is_available():
        raise ValueError('CUDA unavailable in the isolated video environment')
    pipe = None
    try:
        pipe = build_pipeline(request, torch, diffusers)
        steps = 20 if request['quality'] == 'draft' else 50
        def progress(pipeline, index, timestep, tensors):
            target = Path(request['progress'])
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps({'step':index + 1, 'total_steps':steps}))
            os.replace(temp, target)
            return tensors
        args = dict(prompt=(request['prompt'] + '. ' + request['camera']).strip(),
                    height=request['height'], width=request['width'], num_frames=request['frames'],
                    num_inference_steps=steps, generator=torch.Generator('cpu').manual_seed(request['seed']),
                    callback_on_step_end=progress)
        if request['negative_prompt']:
            args['negative_prompt'] = request['negative_prompt']
        if request['mode'] == 'image-to-video':
            args['image'] = load_image(request['image']).resize((request['width'],request['height']))
        with torch.inference_mode():
            frames = pipe(**args).frames[0]
        export_to_video(frames, request['output'], fps=request['fps'])
    finally:
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


if __name__ == '__main__':
    main()
