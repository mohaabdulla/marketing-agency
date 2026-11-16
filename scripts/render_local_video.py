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
        extra = {'text_encoder': None} if request.get('prompt_encoded') else {}
        pipe = diffusers.CogVideoXPipeline.from_pretrained(request['model_path'], torch_dtype=torch.float16,
                                                          local_files_only=True, use_safetensors=True, **extra)
    elif request['model'] == 'wan21-i2v-480p':
        if request['mode'] != 'image-to-video' or not request.get('image'):
            raise ValueError('Wan I2V requires a starting image')
        vae = diffusers.AutoencoderKLWan.from_pretrained(request['model_path'], subfolder='vae',
                                                        torch_dtype=torch.float32, local_files_only=True)
        pipe = diffusers.WanImageToVideoPipeline.from_pretrained(request['model_path'], vae=vae,
            torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True)
    elif request['model'] == 'wan21-t2v-480p':
        if request['mode'] != 'text-to-video':
            raise ValueError('Wan T2V is text-only')
        pipe = getattr(diffusers, 'WanPipeline', diffusers.CogVideoXPipeline).from_pretrained(
            request['model_path'], torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True
        )
    elif request['model'] == 'wan22-ti2v-5b':
        if request['mode'] == 'image-to-video':
            if not request.get('image'):
                raise ValueError('Wan TI2V requires a starting image in image-to-video mode')
            pipe = diffusers.WanImageToVideoPipeline.from_pretrained(
                request['model_path'], torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True
            )
        else:
            pipe = getattr(diffusers, 'WanPipeline', diffusers.CogVideoXPipeline).from_pretrained(
                request['model_path'], torch_dtype=torch.bfloat16, local_files_only=True, use_safetensors=True
            )
    else:
        raise ValueError('Unsupported model')
    pipe.enable_sequential_cpu_offload()
    if hasattr(pipe.vae, 'enable_slicing'):
        pipe.vae.enable_slicing()
    if hasattr(pipe.vae, 'enable_tiling'):
        pipe.vae.enable_tiling()
    return pipe


def encode_cog_prompt(request, torch):
    """Encode with an 8-bit T5, then release it before loading the video model.
    The full text encoder and video transformer need not share a 16 GB laptop's RAM.
    Only the text encoder is quantized; video weights keep their original FP16 precision.
    """
    from transformers import T5Tokenizer, T5EncoderModel, BitsAndBytesConfig
    root = Path(request['model_path'])
    tokenizer = T5Tokenizer.from_pretrained(root / 'tokenizer', local_files_only=True)
    encoder = T5EncoderModel.from_pretrained(root / 'text_encoder', local_files_only=True,
        torch_dtype=torch.float16, low_cpu_mem_usage=True, device_map={'': 0},
        quantization_config=BitsAndBytesConfig(load_in_8bit=True))
    try:
        embeddings = []
        for text in [(request['prompt'] + '. ' + request['camera']).strip(), request['negative_prompt'] or '']:
            tokens = tokenizer(text, padding='max_length', max_length=226, truncation=True,
                               add_special_tokens=True, return_tensors='pt')
            with torch.inference_mode():
                embeddings.append(encoder(tokens.input_ids.to('cuda'))[0].to('cpu', dtype=torch.float16))
        return dict(prompt_embeds=embeddings[0], negative_prompt_embeds=embeddings[1])
    finally:
        del encoder, tokenizer
        gc.collect()
        torch.cuda.empty_cache()


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    import torch
    import diffusers
    from diffusers.utils import export_to_video, load_image
    if not torch.cuda.is_available():
        raise ValueError('CUDA unavailable in the isolated video environment')
    pipe = None
    try:
        embeddings = None
        if request['model'] == 'cogvideox-2b' and request.get('low_memory'):
            target = Path(request['progress'])
            target.write_text(json.dumps({'phase': 'Encoding prompt with the low-memory text encoder'}))
            embeddings = encode_cog_prompt(request, torch)
            request['prompt_encoded'] = True
        Path(request['progress']).write_text(json.dumps({'phase': 'Loading video generator'}))
        pipe = build_pipeline(request, torch, diffusers)
        steps = 20 if request['quality'] == 'draft' else 50
        def progress(pipeline, index, timestep, tensors):
            target = Path(request['progress'])
            temp = target.with_suffix('.tmp')
            status = {'step':index + 1, 'total_steps':steps}
            if index + 1 == steps:
                status['phase'] = 'Decoding generated video frames'
            temp.write_text(json.dumps(status))
            os.replace(temp, target)
            return tensors
        args = dict(prompt=(request['prompt'] + '. ' + request['camera']).strip(),
                    height=request['height'], width=request['width'], num_frames=request['frames'],
                    num_inference_steps=steps, generator=torch.Generator('cpu').manual_seed(request['seed']),
                    callback_on_step_end=progress)
        if request['negative_prompt']:
            args['negative_prompt'] = request['negative_prompt']
        if embeddings:
            args.pop('prompt', None)
            args.pop('negative_prompt', None)
            args.update({key: value.to('cuda') for key, value in embeddings.items()})
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
