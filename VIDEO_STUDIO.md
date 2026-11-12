# LEXNIS Video Studio

The existing Image & GIF Studio remains mounted in place. A separate vanilla-JavaScript
workspace adds media import, a non-destructive timeline, projects, CPU image animation,
and local-model adapters. There are no hosted video APIs or automatic model downloads.

## Start and install

Use the existing application Python environment. Add CPU video dependencies without changing
the image worker's PyTorch installation:

```powershell
python -m pip install -r requirements-video-editor.txt
# Windows: explicit FFmpeg + FFprobe download, verified against the publisher's SHA-256
python scripts/setup_video_tools.py --install
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Restart an already-running server to load the new routes.
The sidebar defaults to Image & GIF Studio on first visit, remembers the workspace and
collapsed state, and becomes a focus-trapped drawer on mobile. Image form DOM state is
retained when switching workspaces. Video drafts also persist in this browser's localStorage.

On Debian/Ubuntu:

```sh
sudo apt update
sudo apt install ffmpeg fonts-dejavu-core
python -m pip install -r requirements-video-editor.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Alternatively set `FFMPEG_BIN` and `FFPROBE_BIN` to installed executables. Detection checks
these variables, PATH, then `output/video-tools/`; FFmpeg alone can also use imageio-ffmpeg.
FFprobe must be installed separately if only imageio-ffmpeg is present. Nothing is downloaded
by starting the server or checking status. Run **one server worker**: the persistent queue
is designed for a single local application process, not multiple independent ASGI workers.

## Editing workflow

1. Open Video Studio → Media Library and import MP4, MOV, WebM, GIF, PNG/JPEG/WebP,
   MP3, WAV, OGG, FLAC or M4A. Metadata, image thumbnails, video thumbnails and audio
   waveform previews are generated locally. Optional thumbnail failures retain the media.
2. Add assets to the Editor. Primary clips play sequentially; reorder by drag/drop or
   Move earlier/later. Logos, titles and audio have their own tracks and editable start times.
3. Select a clip to set source trim, timeline duration, speed, volume/mute, position,
   scale, rotation, crop, color adjustment, Ken Burns zoom/pan, fades, and crossfade length.
   Move the playhead inside a primary clip and choose Split.
4. Add English/Arabic titles, captions or lower thirds. Pillow uses RAQM shaping when
   available, otherwise arabic-reshaper/python-bidi. Sans/Arabic/serif select installed
   Arial/Times on Windows or DejaVu on Linux. Text never enters an FFmpeg shell or drawtext string.
   A brand kit applies its primary color to current titles and imports its logo when present.
5. Source preview plays the selected trimmed clip. **Render preview** produces the complete
   composition at a maximum 480px edge. It includes effects, overlays, transitions and audio.
6. Save/reopen, rename, duplicate or delete projects. Deleting a project retains original assets.
7. Export H.264 MP4 or VP9 WebM, with/without mixed audio. Presets include landscape/portrait
   720p/1080p, square and 4:5. Select 24 fps, 30 fps, or the first primary asset's original fps.
   Download links report FFprobe's actual encoded dimensions, duration and frame rate.

The generation result carousel has **Send to Video**, **Animate Image**, and
**Use as starting frame** actions. They copy managed campaign media directly into the video
library without browser download/reupload. GIFs/videos enter the editor; diffusion starting
frames require a still image. The original campaign file is retained byte-for-byte.
Audio extraction is available for library assets containing an audio stream.

**Image Animation** is a separate CPU mode (zoom, pan, still with fades), available without
AI weights. It animates the supplied image, including an employee photograph on a welcome
card, without synthesizing a different person. Layer-by-layer welcome animations from the
existing image engine remain available there; this CPU mode moves the complete flattened card.

## Local AI models and licensing

Official model documentation and license files were checked on 2026-11-12. Adapters are
implemented, but **neither model was installed or executed during this task**. Both remain
unverified until an operator runs the explicit real-model smoke test. Contract tests with
mocks verify adapter selection; they do not establish inference quality or measured VRAM.

| Model | Adapter / native output | License / commercial conditions | Practical installation gate |
| --- | --- | --- | --- |
| [zai-org/CogVideoX-2b](https://huggingface.co/zai-org/CogVideoX-2b) | Text-only CogVideoXPipeline; 720×480, 49 frames at 8 fps (6.125s) | Apache-2.0; retain license/notices when redistributing, no trademark grant | 6 GB total/free VRAM, 24 GB system RAM; 32 GB RAM recommended; 30 GiB free for weight installation |
| [Wan-AI/Wan2.1-I2V-14B-480P-Diffusers](https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P-Diffusers) | Separate WanImageToVideoPipeline with image encoder and starting frame; 832×480, 81 frames at 16 fps (5.0625s) | Apache-2.0; same redistribution/notice obligations | Conservative, unverified lower gate: 24 GB total/free VRAM, 48 GB system RAM, 110 GiB free for weight installation; larger systems recommended |

HF repository metadata reports approximately **13.77 GB** of safetensors for CogVideoX-2B and
**90.08 GB** for this full-precision Wan Diffusers snapshot (decimal GB, excluding small configs
and the isolated runtime). The setup script resolves and records the exact repository commit
and downloaded file sizes. It does not assume a smaller community quantization is equivalent.
These are configuration gates, not measured guarantees that a particular GPU will fit.

Cog's model card documents optimized starting VRAM figures, with measurements on A100/H100
and important qualifications for other hardware. The worker uses FP16, sequential CPU
offload, and VAE slicing/tiling; laptop latency and peak RAM are unmeasured here.
See the [official CogVideoX Diffusers documentation](https://huggingface.co/docs/diffusers/api/pipelines/cogvideox).
Wan uses BF16 with an FP32 VAE and sequential offload; CUDA BF16 support is checked in the
isolated runtime. Its image input is passed to the actual image-conditioned pipeline.
See the [official Wan pipeline documentation](https://huggingface.co/docs/diffusers/api/pipelines/wan).

Evaluated alternatives:

- [LTX-Video 0.9.1's actual license](https://huggingface.co/Lightricks/LTX-Video-0.9.1/blob/main/ltx-video-2b-v0.9.1.license.txt)
  defines its permitted purpose as academic/research use and restricts commercialization.
  It is excluded from this commercial agency model registry. Other LTX revisions have
  different custom terms and require their own review; they are not interchangeable licenses.
- [Wan2.2 TI2V-5B](https://github.com/Wan-Video/Wan2.2) is Apache-2.0 and supports T2V/I2V.
  Its official 1280×704 / 704×1280 configuration calls for at least 24 GB VRAM. It was evaluated,
  but is not an implemented/verified adapter in this release. No 8 GB compatibility is claimed.

Selected weights do not make source photographs, trademarks, fonts or generated outputs
automatically cleared for every campaign. Use appropriately licensed client assets and fonts.
The code uses free libraries. FFmpeg's license depends on its build: the Windows essentials
build includes GPL components and libx264. Retain applicable notices/source obligations if
redistributing those binaries. Codec patent considerations depend on deployment/jurisdiction;
see [FFmpeg's own legal notes](https://www.ffmpeg.org/legal.html). No binaries are committed.
Lucide sidebar icon paths use the ISC license (see VIDEO_THIRD_PARTY_NOTICES.md).

## Explicit AI installation and verification

The isolated environment uses PyTorch 2.6.0 CUDA 12.4, Diffusers 0.36.0 and Transformers
4.57.3; it does not modify `.venv-image`. Dependency/inference compatibility is still
unverified with real weights here. Initial downloads require internet, disk and local compute.

```powershell
# Explicit multi-GB runtime download:
python scripts/setup_local_video.py --runtime
# Review the linked model license, then explicitly download ONE model:
python scripts/setup_local_video.py --model cogvideox-2b --accept-license
# Or, on a larger machine:
python scripts/setup_local_video.py --model wan21-i2v-480p --accept-license

# Status only; no inference/download:
python scripts/verify_local_video.py
# Real opt-in smoke tests; may take many minutes:
python scripts/verify_local_video.py --model cogvideox-2b --run-inference
python scripts/verify_local_video.py --model wan21-i2v-480p --image path/to/starting-image.png --run-inference
```

Only a successful worker run followed by FFprobe validation writes the model's smoke marker.
The marker records the installed revision. AI duration/native resolution are fixed per adapter;
export aspect/resolution are explicitly padded/resized afterward, without claiming native 1080p.
Draft uses 20 steps, standard 50; longer stories are assembled in the editor.

This development machine has an RTX 4060 Laptop (~8 GB), 15.7 GB RAM and initially ~21 GB
disk free. Its RAM does not meet this Cog offload configuration; Wan also exceeds GPU/disk
capacity. AI controls therefore remain disabled with specific reasons. CPU editing and
Image Animation were executed successfully. Installing a model is not required to use them.

## Architecture, API and storage

`server.py` includes `video_api.router`; it never imports Diffusers/PyTorch for video inference.
`video_storage.py`, `video_assets.py` and `video_projects.py` own UUID media IDs, atomic JSON
and validated timelines. `video_editor.py` renders normalized clips, concat/crossfades,
Pillow title PNGs, overlays and mixed audio through bounded `video_ffmpeg.py` subprocess calls.
`video_engine.py` coordinates deterministic animation and the isolated model worker.
`video_models.py` provides capabilities/hardware/model status. `video_jobs.py` bounds the queue
to eight jobs, with two CPU workers and one AI worker; `gpu_resources.py` provides an OS lock
shared with both existing local image inference paths.

UI modules live in `static/js/{workspace-navigation,video-api,video-studio,video-editor}.js`;
styles in `static/css/video-studio.css`. `index.html` only gains the shell, stylesheet and module.

| API | Purpose |
| --- | --- |
| GET `/api/video/health`, `/capabilities`, `/models` | Tools, hardware, limits, model availability |
| POST `/api/video/upload`, `/import` | Multipart upload or managed campaign URL import |
| GET `/api/video/assets`, `/media/{id}`, `/thumbnails/{id}`, `/download/{id}` | Library, range-enabled playback, thumbnail, download |
| POST `/api/video/assets/{id}/extract-audio` | Background WAV extraction |
| POST `/api/video/generate`, `/export` | Return HTTP 202 with persistent job ID |
| GET `/api/video/jobs`, `/jobs/{id}`; POST `/jobs/{id}/cancel` | Lifecycle and cancellation |
| GET/POST `/api/video/projects`; GET/PUT/DELETE `/projects/{id}` | Project persistence |
| POST `/api/video/projects/{id}/duplicate` | Copy timeline, retain source references |

Storage defaults to git-ignored `output/video/{assets,projects,jobs,work}`; override
`VIDEO_DATA_DIR` before starting the process. Models live in `.model-cache/video/`.
Projects reference UUID asset IDs; no browser path can resolve an arbitrary disk file.
Uploads are streamed, limited to 256 MB with an 8 GiB workspace quota by default, and checked
by signature, Pillow/FFprobe, codecs, dimensions and duration. HTTP size/origin limits run
before multipart parsing, with three simultaneous uploads. FFmpeg network protocols are
disabled for input. Arguments use `shell=False`. Titles are raster inputs, not shell text.
Maximum timeline: 60 clips / 300 seconds / 1920px edge; FFmpeg jobs have bounded threads,
disk checks and timeouts. Pending jobs interrupted by restart become failed with an explanation.
Cancel stops the actual child before reporting cancelled. Temporary render directories are
removed on success/failure/cancellation; abandoned work older than a day is cleaned at startup.
Original media and completed renders are retained intentionally; no automatic destructive purge.

CORS no longer allows every origin with credentials. Same-origin UI works directly; explicit
additional clients require both `CORS_ALLOWED_ORIGINS` and `VIDEO_ALLOWED_ORIGINS`. This is a
local, single-user application, with no new authentication or multi-tenant permission model.
Detailed processing/worker errors stay in local `jobs/*.log` / `work/last-ffmpeg-error.log`.

## Verification and current limits

```powershell
python scripts/test_video_studio.py
python scripts/test_video_studio_browser.py
python scripts/run_agency_regressions.py
python scripts/test_professional_agency_suite.py
python -m unittest discover -s tests -p "test_*.py" -v
python tests/browser_smoke.py
```

New backend tests exercise real FFmpeg/FFprobe, security, persistent project/job states,
crossfades, Arabic/English titles, logos, audio mixing/extraction, MP4/WebM, CPU animation,
cancellation, error redaction and mode-specific AI adapters with mocks. Browser tests use
the real local server, not mocked video APIs. They cover desktop/mobile navigation, preserved
image form state, import, trim, save/reopen, actual exports, animation and downloads.

Known limits: real AI inference and GPU cancellation/OOM recovery have not been executed
with weights. No AI speech/TTS, scene extension, optical-flow interpolation, depth-estimated
parallax, arbitrary uploaded fonts or live GPU compositing are implemented. Slow motion uses
frame retiming/resampling. Primary clips are sequential; overlay start times are edited in
properties, rather than freely dragged along a time ruler. Only still-image logo overlays
are supported. Title entry supports manual captions, not automated transcription. Source
preview is not a live composition; render preview for final effects. Offline video work
needs only locally installed tools/models/fonts; existing internet-backed image/research
features retain their existing connectivity requirements.

See VIDEO_VERIFICATION.md for execution results and pre-existing regression failures.
