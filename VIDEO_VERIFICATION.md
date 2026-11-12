# Video Studio execution record — 2026-11-12

## Executed successfully

- `python scripts/test_video_studio.py`: **12 tests passed**. Uses real FFmpeg/FFprobe for
  upload, metadata, byte-range seeking, trim/merge/crossfade, Arabic/English titles, logo
  overlay, mixed/extracted audio, MP4, WebM, CPU zoom-out animation, project CRUD/duplicate,
  path and request limits, direct campaign import integrity, cancellation, and error redaction.
  AI adapter/orchestration tests use mocks plus a synthetic encoded clip; these are not AI inference.
  The worker contract checks progress, offline environment, subprocess invocation, native output
  validation and temporary-directory cleanup.
- `python scripts/test_video_studio_browser.py`: **passed against the real local server**.
  Desktop and 390px mobile navigation, first-visit image default, persisted workspace,
  image form retention across switching, video upload/preview/trim/split/drag reorder, title
  entry, project save/reopen, real MP4 export, CPU image animation/download, direct campaign
  transfer, mobile Escape/focus restoration and no horizontal overflow. No page JavaScript errors.
- `python scripts/run_agency_regressions.py`: **all 15 existing script suites passed**,
  with bounded offline providers. This includes image/GIF endpoints, bilingual carousel,
  welcoming employee photos, multi-brand/logo safety, rendering, copy, agency browser and ZIPs.
  This run collected its script list before the two new video tests were created; those ran separately.
- `python scripts/test_professional_agency_suite.py`: **8 tests passed**.
- Python compilation, module syntax checks with `node --check`, and `git diff --check`: passed.

Local ignored evidence:

- `output/video-studio-backend-final.log`
- `output/video-studio-browser-final.log`
- `output/video-studio-desktop.png`, `output/video-studio-mobile.png`
- `output/agency_regressions/results.json` and per-suite logs
- `output/video-agency-suite.log`

Existing tests regenerate tracked sample JPEGs. Those fixture bytes were restored from the
initially clean commit after testing; no campaign source-image redesign is part of this change.

## Existing failing tests, independently checked against HEAD

`python -m unittest discover -s tests -p "test_*.py" -v` ran **27 tests: 22 passed, 5 failed**:

1. `CampaignTests.test_image_failure_keeps_copy_and_export`: expects unavailable image;
   existing fallback returns a ready image.
2. `TestCompanyWebsiteAnalysis.test_api_analyze_website_endpoint`: expects old `#08101E`;
   existing brand kit returns `#131724`.
3. `TestCompanyWebsiteAnalysis.test_lexnis_brand_dna_extraction`: same old brand-color expectation.
4. `TestCompanyWebsiteAnalysis.test_brand_flow_composite_template_swap`: expects 808×1024;
   current existing renderer returns 1080×1350.
5. `TestPersonalizedSwapAndArtboard.test_high_res_whatsapp_and_personalization`: same old dimensions.

The five tests were rerun with `visual_engine.py`, `campaign_generator.py` and `server.py`
loaded directly from **the pre-change Git HEAD**; all five fail identically there, with zero
test execution errors. Existing image behavior and assertions were retained. Evidence:
`output/video-existing-tests.log`, `output/video-baseline-tests.log`.

`python tests/browser_smoke.py` also fails its pre-existing `#visual-unavailable` visibility
assertion. The same assertion fails using the pre-change `HEAD:index.html`.
Its static-file fixture was updated to serve versioned CSS and workspace modules; no assertion
was removed or relaxed. Evidence: `output/video-baseline-browser.log`.
The newer agency browser suites and the new real-server video browser test pass.

## Hardware and tools actually used

- Windows, Python 3.12; RTX 4060 Laptop, 8188 MiB VRAM; 15.7 GiB system RAM.
- About 21 GiB disk free before tool downloads/test output.
- FFmpeg and FFprobe **9.0.2 essentials build from Gyan** installed locally in
  ignored `output/video-tools/`; H.264/libx264, VP9, AAC, Pillow Arabic shaping exercised.
- Tests used CPU rendering, synthetic test patterns, generated solid PNGs, and local fixtures.

## Not verified or not implemented

No multi-GB AI model weights or `.venv-video` were downloaded. No real CogVideoX/Wan inference
was executed. Actual inference latency, peak VRAM/RAM, quality, GPU OOM recovery and GPU
cancellation are **unverified**. GPU model gates disable unsupported configurations; normal
tests only simulate expensive inference. The opt-in setup/smoke commands are provided in
VIDEO_STUDIO.md. Acceptance criteria requiring successful real T2V and separately verified I2V
remain unfulfilled on this hardware/installation.

The CPU editor and image animation work without those optional models. Advanced depth
parallax, optical-flow slow motion, live composite preview, automated transcription/TTS,
arbitrary uploaded fonts and free-position primary-track editing are not implemented.
See VIDEO_STUDIO.md for the implemented timeline semantics and remaining limits.

## File manifest

Created backend modules:
`video_api.py`, `video_assets.py`, `video_editor.py`, `video_engine.py`, `video_ffmpeg.py`,
`video_jobs.py`, `video_models.py`, `video_projects.py`, `video_security.py`, `video_storage.py`,
`gpu_resources.py`.

Created frontend:
`static/js/workspace-navigation.js`, `static/js/video-api.js`, `static/js/video-studio.js`,
`static/js/video-editor.js`, `static/css/video-studio.css`.

Created scripts:
`scripts/render_local_video.py`, `scripts/setup_local_video.py`, `scripts/setup_video_tools.py`,
`scripts/verify_local_video.py`, `scripts/test_video_studio.py`, `scripts/test_video_studio_browser.py`.

Created dependencies/docs:
`requirements-video.txt`, `requirements-video-editor.txt`, `VIDEO_STUDIO.md`,
`VIDEO_VERIFICATION.md`, `VIDEO_THIRD_PARTY_NOTICES.md`.

Modified:
`server.py` (router, request limits, CORS), `index.html` (workspace shell only),
`visual_engine.py` (shared GPU lock at existing local inference boundaries),
`tests/browser_smoke.py` (static fixture routing only), `.gitignore`, `.env.example`, `README.md`.
Existing campaign API formats and the image-rendering implementation are retained.
