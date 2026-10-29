# Lexnis Campaign Studio — improved pipeline

Product research → creative brief → copywriting → creative review → photographic asset → separately typeset advertising copy.

## Run

```powershell
pip install -r requirements.txt
python server.py
```

Open http://localhost:8000. Use the Python backend; direct-file browser generation has been retired because its fallback templates fabricated product claims.

The compiled Tailwind stylesheet is included in `static/tailwind.css`; no browser Tailwind CDN is used. After changing utility classes or the theme, run `npm ci` and `npm run build:css`. Node.js is only needed to rebuild CSS, not to run the app. Theme settings are in `tailwind.config.cjs`.

The model setup message reports whether credentials are configured, not remote quota availability. Missing setup disables visual retries. Expected provider failures return `image_status: unavailable` with actionable warnings; campaign copy remains usable.

For the supplied reference style, choose **Cinematic Lifestyle**, **Landscape ad**, and use:

> Tesla Model 3, deep blue, driving on a winding coastal road at sunset. Ocean horizon, warm natural light, low front three-quarter tracking shot, realistic reflections and road motion blur. Keep the whole car visible with quiet space upper left and lower right. Campaign hook: Accelerate the future. Product title: Tesla Model 3.

Quality depends on the actual image model and product knowledge. These changes do not guarantee reference-level output or exact product geometry. The next quality step is reference-image editing with an approved product photograph, followed by visual review; reference-image upload is not implemented here.

## Models researched

Verified using primary documentation on October 29, 2026. Free model weights and hosted computation have different costs.

| Option | Why try it | Cost/setup |
| --- | --- | --- |
| [Cloudflare FLUX Schnell](https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/) | Fast photographic drafts; integrated REST API | Account ID + Workers AI token. [10,000 neurons/day free](https://developers.cloudflare.com/workers-ai/platform/pricing/), shared across model usage. |
| [Z-Image Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) | Photorealism, fast sampling | Apache 2.0 weights. Local GPU or Hugging Face hosting. |
| [Qwen Image 2512](https://huggingface.co/Qwen/Qwen-Image-2512) | Detailed imagery and composition | Apache 2.0 weights; heavier local inference or hosted computation. This license finding applies to 2512 specifically. |
| [FLUX.1 Schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) | Four-step local drafts | Apache 2.0 weights. Local GPU or hosted computation. |
| Gemini Image / Pollinations | Existing integrations retained | Provider keys, model access and image quota apply. No automatic cross-provider substitution. |

Hugging Face [currently lists no included inference credits for free accounts](https://huggingface.co/docs/inference-providers/en/pricing). A free model download is not a free hosted API. Provider availability can change.

## Configure

### Local engine on this laptop

The isolated Segmind Vega engine uses `.venv-image` and `.model-cache/segmind-vega`. It needs no Cloudflare or Hugging Face API key after downloading the weights. The default selects this engine after a real smoke render creates its readiness marker. Its GPU runtime is separate from the server Python, which can keep using its existing CPU-only PyTorch.

To install on another machine: `python -m venv .venv-image`, then `python scripts/setup_local_images.py`. This downloads CUDA PyTorch and the fp16 [Segmind Vega](https://huggingface.co/segmind/Segmind-Vega) model (Apache 2.0), verifies CUDA, and generates a real sample before enabling the engine. Downloads require several GB. Recheck an existing installation with `python scripts/verify_local_images.py`.

The laptop engine renders up to 1024 pixels across, then resizes to the selected export size. Expect lower product fidelity than larger hosted models; inspect outputs before use. Each render starts a subprocess and frees its GPU memory on completion. Model files and runtime are ignored by Git.

Select **Segmind Vega — local GPU, no API key** in the dashboard. An explicit `IMAGE_MODEL` setting overrides the automatic default; use `IMAGE_MODEL=local:segmind-vega` if needed.

Use `.env.example` to configure `.env`, preserving any existing keys. Restart the server after edits. Keys stay on the backend.

**Free hosted route:** create a Cloudflare account, locate its Account ID, and create an API token with Workers AI access for that account. Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`; choose Cloudflare FLUX Schnell. Its documented request schema does not offer width/height controls, so the app crops its output to the selected format. Providers supporting native dimensions can preserve more composition detail.

**Local route:** install CUDA-compatible PyTorch, then `pip install -r requirements-local.txt`. Set `IMAGE_PROVIDER=local`, select an open-weight model and pre-download its weights, or explicitly set `ALLOW_MODEL_DOWNLOAD=1`. Downloads can be many GB. CPU offload needs sufficient RAM/disk; an 8 GB GPU may still run out of memory, especially with Qwen. Local inference is serialized. No large model downloads happen by default.

**Hugging Face route:** set `HF_TOKEN` with Inference Providers permission and required credits, leave `IMAGE_PROVIDER=huggingface`, and choose an open-weight model. Integration uses the [official InferenceClient](https://huggingface.co/docs/inference-providers/en/tasks/text-to-image). `HF_PROVIDER` overrides automatic provider selection; exact model availability depends on providers.

**Text/research:** `GEMINI_API_KEY` enables Gemini copy and search grounding. `GEMINI_MODEL` overrides the text model. Pollinations remains supported; anonymous services can fail. Failed text steps produce an editorial-review warning and safe fallback copy.

## Changes

- Removed the synthetic cube fallback reported as successful AI photography.
- Preserved requested product identity; vague Tesla requests no longer become Cybercab.
- Removed invented charging/material/latency/ROI claims from production fallbacks.
- Replaced forced dark macro prompts with scene-aware photographic direction and full prompts.
- Added portrait 1080×1350, landscape 1536×864 and square 1080×1080 formats.
- Replaced telemetry and “official archive” labels with restrained white ad typography.
- Added explicit providers, actionable failures, partial campaign results and copy-only export.
- Versioned cache keys to avoid reusing earlier placeholder renders.

API: `/api/health`, `/api/generate`, `/api/render`, `/api/export`, `/api/search`, `/api/enhance-prompt`. Generate/render accept `output_format`: `portrait`, `landscape`, `square`. Generation returns `image_status` and `warnings`; missing visuals have empty URLs.

```powershell
python campaign_generator.py "Blue Tesla Model 3 coastal sunset campaign" --brand Tesla --theme "cinematic coastal photography" --format landscape --image-model cf:flux-schnell --download
python -m unittest discover -s tests -v
```

Exports: `output/`. Image cache: `output/renders/`. Review factual claims and visual fidelity before publication. Source-backed prompting does not implement automatic claim-by-claim verification.
