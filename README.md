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

### Photographic quality upgrade

The **RealVisXL 5 — photographic detail, local GPU** option improves on the faster Vega engine with a full-size photography-focused checkpoint, larger native renders and a low-strength detail pass. It runs locally without API charges. After a verified sample enables the checkpoint, automatic model selection prefers it; Vega remains available for faster drafts.

Install its weights with `python scripts/setup_realism_model.py` and generate a sample and activate the verified engine with `python scripts/verify_realism_images.py --activate`. Omit `--activate` to generate an inspectable sample without changing the default. The setup uses the existing isolated CUDA environment. RealVisXL uses OpenRAIL++ rather than Apache 2.0; see [research, sources, settings and limitations](REALISM_RESEARCH.md). More detailed generation takes longer than Vega on an 8 GB GPU.

Old cached renders are invalidated. `output/latest-local-render.json` records the effective prompt, token counts, native resolution, detail-pass settings and elapsed time; `output/local-render-progress.log` shows model loading and diffusion progress. The export path preserves the original photographic contrast and does not apply blanket sharpening.

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

## Professional agency workspace

Generation now adds LinkedIn, Instagram and X copy, hashtag strategy, portrait/story/banner exports, GIF and optional 24fps H.264 MP4, and a full downloadable ZIP. The employee's actual welcome card and staged portrait/name entrances are preserved for welcome motion.

- `POST /api/campaign/generate` (also `/api/generate`) accepts `language: "en" | "ar" | "both"`, `brand_id`, `key_points`, and `key_points_ar` alongside the existing fields. Use `use_local_sdxl: false` and `use_search: false` for deterministic offline visual generation. `/api/template/swap` and `/api/template-swap` continue to accept multipart input.
- Both routes retain `image_url`, `companion_image_url`, `animation_url`, and `carousel_urls`. New fields are `story_url` (1080×1920), `landscape_url` (1200×628), `animation_mp4_url`, `copywriting`, and `bundle_zip_url`. Corresponding `arabic_*` fields and `agency_kits.en` / `agency_kits.ar` let the workspace switch all deliverables and copy together. An Arabic-only request selects Arabic media in the top-level URLs. Single-card opt-out remains supported.
- `generate_campaign_copy(req_data, brand_theme)` and `render_omnichannel_variants(primary_card_path, req_data, brand_theme)` are available from `campaign_generator.py`. Copy is deterministic, uses supplied talking points, and does not invent performance results. Supply localized `topic_ar`, `brand_name_ar`, or `key_points_ar` for exact custom Arabic terminology. Suggested posting windows are experiments to refine with account analytics, following [LinkedIn's guidance](https://www.linkedin.com/business/marketing/blog/linkedin-ads/whats-the-best-time-to-post-on-linkedin).
- GIF motion uses 72 samples at 60 ms (4.32 seconds), a shared adaptive MEDIANCUT palette and Floyd–Steinberg dithering. Identical welcome hold frames are merged without changing playback duration. MP4 encoding uses system FFmpeg or the installed `imageio_ffmpeg` binary at 24fps; if unavailable, the GIF remains available and `animation_mp4_url` is empty. No encoder download is attempted.
- Brand kits are stored atomically in `static/assets/brand_kits.json`. `GET /api/brands` lists them; `POST /api/brands` creates one; `PUT /api/brands/{id}` updates it; `DELETE /api/brands/{id}` removes it. Fields: `brand_name`, `brand_name_ar`, `primary_hex`, `accent_hex`, `logo_path`, `tagline`, `hashtag`. The workspace offers client selection and save/edit/delete before generation.
- Full bundles are prebuilt under `static/assets/<campaign>_agency_kit.zip`, containing the two feed JPGs, animated GIF, MP4 when available, story JPG, banner JPG and UTF-8 `campaign_copy_and_strategy.txt`. `POST /api/campaign/bundle` rebuilds a kit from `{deliverables: {image_url, companion_image_url, animation_url, animation_mp4_url, story_url, landscape_url}, copywriting: {...}}`. Only public generated media URLs are accepted. The existing three-asset carousel ZIP endpoint remains supported.

Verification: `python scripts/test_professional_agency_suite.py`, then `python scripts/test_professional_agency_browser.py`. The browser test uses the generated API fixtures and requires Playwright/Chromium. `python scripts/run_agency_regressions.py` runs the other `scripts/test*.py` scripts against an isolated local server with external text/image providers disabled; results and per-script logs are in `output/agency_regressions/`.

### Carousel compatibility

Campaigns retain the three-card 1080×1350 social media kit in English and Arabic: a primary graphic, a static topic companion, and an animated GIF. Welcome motion uses the actual employee card; other topics animate the companion. Both static cards and the loop share the same brand header. `static/assets/brand_logo.png` was extracted from the existing uploaded Lexnis artwork (`logo_images_91926a2739df.jpg`) using the logo loader's background removal, dark-background adaptation and trimming. Uploaded logos take precedence; the existing wordmark fallback remains available if the bundled asset is removed.

`POST /api/generate` (alias `/api/campaign/generate`) accepts `generate_companion` (default `true`) and `use_local_sdxl` (`null` = use a ready local model automatically, `false` = deterministic CPU editorial showcase, `true` = try the local model). Existing `/api/template-swap` and its alias `/api/template/swap` accept the same fields as multipart form values. Responses include `image_url`, `companion_image_url`, `animation_url`, and `carousel_urls: [image_url, companion_image_url, animation_url]`, plus `arabic_image_url`, `arabic_companion_image_url`, `arabic_animation_url` and `arabic_carousel_urls`. With companions disabled, the animation URL is empty and each carousel array contains its primary image only. Kit mode uses portrait exports; disabling it preserves the existing format choices.

`generate_social_gif(topic, post_type, output_gif_path)` renders a 4.32-second infinite loop using Pillow. The integrated welcome pipeline supplies the employee card and its lossless layers for staged entrances; other topics use floating architecture nodes, gentle parallax and a sweeping brand sheen. Welcome calls require their employee card as `base_image`. Animations are saved alongside the cards as `<primary_stem>_anim.gif` and optional `.mp4`. `/api/render`, CLI exports and `POST /api/carousel/download` retain the media formats and extensions.

The photographic path reuses the isolated local SDXL worker and applies an editorial grade. When no ready model exists or a render fails, the companion uses a perspective glass architecture window with topic-specific content. Each companion has a JSON sidecar recording its source, scene direction, layout bounds and any local-render failure. Showcase benchmark values are illustrative campaign copy, not measurements collected from a deployment.

CLI: use `--companion-cpu` for fast deterministic output, `--no-companion` for a single graphic, and `--download` to export both languages, static companions and GIF loops. Python callers can use `generate_campaign_post(primary_card, req_data, brand_theme, output_path=..., generate_companion=True)` to turn an already-rendered card into a kit.

```powershell
python scripts/test_dual_social_images.py
python scripts/test_dual_social_browser.py
```

The rendering suite regenerates `lexnis_hiring_{en,ar}`, `lexnis_launch_{en,ar}`, and `api_swap_{en,ar}` with matching `_companion.jpg` and `_anim.gif` files under `static/assets/`. It tests API kits/opt-out, ZIP/download/export extensions, GIF frame count/duration/loop/seam and stable branding, and companion text bounds. GPU routing is tested with a stub worker; these checks do not require diffusion inference. Browser checks require Playwright and Chromium.
