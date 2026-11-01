# Photographic output improvements

Researched October 29, 2026. All inference runs on the existing local GPU. No paid service, cloud inference credit, subscription or API key is used.

## Findings from primary sources

- [Vega's model card](https://huggingface.co/segmind/Segmind-Vega) describes a heavily distilled SDXL model focused on size and speed. It recommends CFG around 9. This profile remains the faster option; its guidance setting was not arbitrarily reduced.
- [RealVisXL V5.0's creator](https://huggingface.co/SG161222/RealVisXL_V5.0) explicitly targets photorealism. The card recommends DPM++ SDE Karras with 30+ steps, or DPM++ 2M Karras with 50+ steps. It recommends a 1.1–1.5× high-resolution pass with denoising strength between 0.1 and 0.3.
- [Diffusers' image-to-image guide](https://huggingface.co/docs/diffusers/using-diffusers/img2img) explains that low denoising strength better preserves the starting image. It also documents CPU offload and the built-in PyTorch attention path for memory savings.
- RealVisXL is listed under OpenRAIL++ in its model metadata. The SDXL [CreativeML Open RAIL++-M license](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md) grants no-charge rights subject to its terms. It is not Apache 2.0. Downloaded weights are kept locally and excluded from Git.

## Implementation and limits

RealVisXL uses a DPM++ 2M SDE/Karras base pass with 36 steps and CFG 5.0. The modest CFG is an implementation choice to test for less exaggerated contrast; it is not presented as the creator's recommended CFG. Landscape generation starts at 1344×768 rather than Vega's 1024×576. Portrait uses 896×1152; square uses 1024×1024.

The same checkpoint then performs a second DPM++ 2M/Karras image-to-image pass at the output size with strength 0.20 and CFG 4.5. Fifty scheduled steps yield approximately ten effective denoising steps at that strength. This shares the model components and uses CPU offload, VAE slicing and VAE tiling for the laptop's 8 GB GPU. No additional upscaler weights are required; Lanczos resizing provides the starting image for learned refinement. This is a practical variation of the creator's high-resolution recommendations, not an exact reproduction.

Prompts reserve room for photographic direction within both CLIP encoders' token budgets. Render metadata records the effective prompts, seed, native/output sizes, token counts and settings. Overly stylized wording is reduced, and a fixed contrast boost and unsharp mask were removed from the export path.

RealVisXL is enabled as the automatic default only after a real sample has been generated and inspected. Vega remains available. Render cache keys have changed so old images are not reused.

Text-only generation can still distort headlights, wheel geometry, badges and exact product identity. Higher resolution alone cannot guarantee faithful branding. An approved product photograph plus controlled editing is a further step; this update does not claim that reference-image workflow is implemented.

## Reproduce

```powershell
python scripts/setup_realism_model.py
python scripts/verify_realism_images.py
```

Add `--activate` to the verification command to enable the model after successful image validation. In this workspace, the sample was also inspected visually before activation.

Samples and settings are saved under `output/tesla_realism_*`. The worker's live progress is in `output/local-render-progress.log`; errors are in `output/local-render-error.log`.

## Windows checkpoint loader

Repeated live API tests exposed a native Windows access violation while Safetensors 0.8 loaded a large checkpoint through PyTorch's storage mmap path. The stack and exit code matched an [upstream Windows report](https://github.com/invoke-ai/InvokeAI/issues/9957). The isolated worker now selects Safetensors' public `pread` backend before importing Diffusers/Transformers. This reads tensor data without that memory-mapped storage path; the server and installed library files are unchanged. The worker records its reader backend and native exit codes for diagnostics.

The subsequent direct-read test exposed Windows error 1455 (insufficient paging-file capacity) while loading large components. The checkpoint is therefore repacked into standard Safetensors shards of approximately 512 MB. Repacking streams the original tensor bytes without converting, quantizing or retraining them. Diffusers/Transformers load the indexed shards sequentially, reducing temporary loader allocations. The downloaded originals are retained. `python scripts/shard_local_checkpoint.py` reproduces this preparation without another download; the model setup helper runs it automatically.
