# Agency video editing implementation — 2026-11-15

This report supersedes the editorial limitations and test numbers in
`VIDEO_EDITING_UPGRADE.md`. That document remains the record of the earlier technical
mastering work. The original research and implementation brief is retained in `todo.txt`.

## Implemented workflow

The guided editor keeps source, brand/logo, brief, prompt assistant, settings, preview,
QA and export in separate sections. Extra settings are collapsed. One short instruction
works with the preceding brand and brief fields. Advanced timeline editing remains available.

Preview answers each recognized request with DONE, PARTLY DONE, NOT AVAILABLE, NOT NEEDED
or NOT APPLIED and an explanation. A background blur is explicitly distinguished from
replacement with an uploaded approved image. Neither is described as generative reconstruction.

The plan lists actual cuts, captions, lighting, framing, graphics and mastering decisions,
their evidence/confidence, review flag, reversibility, guideline version and platform version.
The four styles can be compared as plans before choosing one to render. They do not launch
four simultaneous exports. Style interpretation is labelled as an interpretation.
Platform, style and CTA fields in the preceding creative brief also feed the edit directly;
an explicit platform in the short instruction takes precedence. A mandatory guideline CTA
takes precedence over the optional brief CTA. No advertising copy is invented.

The source-time StoryMap shows sentence text, recognition confidence, visual emphasis and
editable positional roles. Those roles do not reorder the recording. Semantic importance
and hook strength remain unmeasured without a person or the separate local text planner.

## Architecture and files

| Area | Implementation |
| --- | --- |
| Safe quick edit, request fulfillment, plans, story map | `video_quick_edit.py` |
| Exposure measurements, bounded correction, rendered-frame checks | `video_grade.py` |
| Local subject masks, neural anchors, optical-flow propagation, model-hash cache | `video_segmentation.py` |
| Technical delivery QA and mastering | Existing `video_qa.py`, `video_presets.py` |
| Separate editorial/brand/platform QA | `video_editorial_qa.py` |
| Signal measurements and cached audio indicators | `video_measure.py`, `video_analysis.py` |
| Reviewed caption-style snapshots, local fonts, Arabic line shaping | `video_captions.py`, `video_fonts.py` |
| Timeline schema, title/lower-third motion, multi-bus audio compositor | `video_projects.py`, `video_editor.py` |
| Revision snapshots with plans, render asset and both QA reports | `video_revisions.py` |
| Per-render review events and approval gates | `video_review.py`, `video_api.py` |
| Product-default obstruction regions | `video_safe_zones.json`, `video_platforms.py` |
| Guided controls, comparison, review, plan selection | `static/js/video-quick-editor.js`, `static/css/creative-workflow.css` |
| Windows status persistence and stopped-worker recovery | `video_storage.py`, `video_jobs.py` |

## Editing and QA behavior

- Cuts below 60% confidence remain proposals until explicitly approved. Confidence from
  recognition is not promoted merely because a phrase occurs at the end. Applied cuts at
  60–80% retain a review warning. Silence measurements corroborate pause removals.
- Punch-ins hide a cut or emphasize a sentence with measured movement. They are held framings,
  anchored near a detected face, with constrained scale; there is no alternating timer zoom.
- Lighting is proposed from measured luminance, crushed shadows, highlights and approximate
  face/skin statistics. FFmpeg renders a candidate frame; corrections that introduce excessive
  clipping or hue/saturation shifts are reduced or rejected. Missing face metrics stay unknown.
- Local subject masking supports blur/dim/desaturation and an approved still background.
  Between neural anchors, short-range optical flow propagates the matte only while movement
  and photometric residual stay within bounds. Otherwise it requests fresh inference. Cache
  keys include source SHA, checkpoint SHA, algorithm version and mask rate. Metadata reports
  coverage, temporal IoU, jumps, inferred frames and propagated frames. This is approximate
  segmentation, not hair-level matting or identity tracking.
- Captions retain ASR word probabilities. Uncertain likely names require an explicit spelling
  correction or confirmation, and block final readiness while unresolved. “Mr.”/“Dr.” do not
  cause the following name to be missed. Draft downloads remain available.
- Caption style is a saved snapshot of supported reviewed settings (font, color, size), plus
  the reusable plate/stroke/padding/radius/position style. Unsupported fonts fall back with a
  notice. Size is constrained to the renderer's supported range. Arabic wraps logical text
  before shaping each line with RAQM or the reshaper/bidi fallback; long cues are flagged.
- TikTok LTR/RTL, Reels, Stories, Shorts, standard YouTube and generic horizontal/vertical
  profiles have separate versioned obstruction margins. These are **PRODUCT DEFAULTS**, not
  official or immutable platform rules. QA checks captions, logo and titles against them.
- Native output preserves source detail within the existing 1920-pixel limit. Platform canvas
  uses scaling and states that enlargement does not restore lost detail. No AI restoration
  or 4K reconstruction is claimed.
- Dialogue clarity is optional high-pass filtering and gentle compression. Audio indicators
  include quiet-block RMS, sample peak and 50/60 Hz spectral prominence. Quiet-block RMS is
  not an isolated noise floor, and a hum candidate needs listening. Intelligibility is not
  measured. True peak and loudness remain separate measured delivery checks.
- Licensed uploaded music is ducked by the dialogue/voiceover bus. SFX and ambient tracks stay
  on a separate bus and do not trigger ducking. Music is never downloaded or invented.
- Speaker lower thirds and supplied title/CTA/disclosure graphics use the existing shared
  typography and brand rules. Entrance motion uses a bounded cubic ease-out with Minimal,
  Balanced or Expressive intensity. Speech captions have no automatic karaoke emphasis.
- Review progresses DRAFT → INTERNAL_REVIEW → CLIENT_REVIEW → APPROVED → FINAL. Returning to
  draft is allowed. Approval/final require completed caption review, no pending cuts and no
  failed readiness checks. Approved captions become APPROVED, then LOCKED for that render;
  a new rendered revision starts as a draft. The original project and render stay unchanged.
- Render revisions retain the parent render revision, instruction, complete plan, output asset,
  technical QA, editorial QA and timestamps. Review notes have their own bounded event log.
  Original/previous/current comparison and original/current synchronized playback are available;
  synchronization maps the edited timeline through the removed source ranges.
- Windows JSON replacement retries transient sharing violations with bounded backoff. A stopped
  worker cannot leave a polled job permanently labelled running.

## Models, licenses and setup

No new checkpoint was downloaded during this implementation. The speech and human-segmentation
weights were already installed. All inference and rendering stay on this machine. Inference
cannot invoke rembg's model downloader; only the explicit setup script can download a checkpoint.

| Component | License/source | Status and resources |
| --- | --- | --- |
| faster-whisper small / CTranslate2 | [MIT model card](https://huggingface.co/Systran/faster-whisper-small), [MIT runtime](https://github.com/SYSTRAN/faster-whisper) | Installed in isolated `.venv-asr`; CPU int8, four threads; local checkpoint files total 486,212,590 bytes. Rough planning allowance: 1–2 GB free RAM; speed depends on CPU. |
| U-2-Net human segmentation | [Authors' Apache-2.0 repository and model description](https://github.com/xuebinqin/U-2-Net) | Installed ONNX checkpoint: 175,997,641 bytes. CPU, four intra-op threads / one inter-op thread by default; no GPU needed. Allow roughly 1–2 GB additional RAM. The authors note limited hair accuracy. |
| rembg / ONNX Runtime | [rembg MIT](https://github.com/danielgatis/rembg), [ORT MIT](https://github.com/microsoft/onnxruntime) | Optional CPU runtime. Model licensing is independent of rembg. Only the two explicit U-2-Net choices are enabled; there is no cloud/default-model fallback. |
| U-2-Net small (`u2netp`) | Same U-2-Net source | Optional ~5 MB checkpoint; lower edge quality. Not installed for this review. |
| Qwen3-4B GGUF / llama.cpp | Sources and setup in [LOCAL_AI.md](LOCAL_AI.md) | Optional separate loopback process, ~2.5 GB weights, suggested 8 GB RAM. Not running; no semantic inference success is claimed. Advanced editor retains schema-validated preview/apply. |
| ProPainter | [Authors' non-commercial declaration](https://github.com/sczhou/ProPainter#non-commercial-use-only-declaration) | Excluded from the commercial core. No inpainting dependency or checkpoint installed. |

Repository licenses above describe the published components; they are not a blanket clearance
for uploaded footage, logos, fonts, replacement images or music. Runtime default RAM is an
estimate, not a measured peak. A practical combined CPU workstation should have 8 GB or more
available system RAM; render/matting concurrency and source size affect the requirement.

To explicitly install subject masking on another workstation:

```powershell
python -m pip install rembg onnxruntime
python scripts/setup_video_matting.py
# Smaller alternative:
python scripts/setup_video_matting.py --model u2netp
```

Optional operator settings: `AGENCY_MATTING_MODEL_DIR`, `AGENCY_MATTING_MODEL`,
`AGENCY_MATTING_THREADS` (1–8). Installation is an operator action, unavailable to public
guests. The provider module is optional; its Python dependencies currently run in the web
worker process. Speech and the local text model have separate processes/environments.

For the semantic text planner, follow [LOCAL_AI.md](LOCAL_AI.md), configure `LOCAL_TEXT_URL`
and `LOCAL_TEXT_MODEL`, and verify a real schema-valid response. The UI distinguishes its
availability from the deterministic Quick Edit engine. Existing HTTP protocol tests use a
stub and do not prove real Qwen inference. Text, transcripts and documents remain untrusted
model context; no arbitrary command/filter/path is accepted.

## Security and limits

The new endpoints use the existing cookie workspace, same-origin checks, UUID paths, scoped
storage and validated uploads. Guest A cannot read Guest B's review events, renders, revision
plans or QA. No admin/model-install capability was exposed. Job cancellation, timeouts, disk
quota and upload limits remain. Review events and request fields are bounded. Original footage
is read only; source SHA is checked again after export.

Core limits remain explicit: 1920-pixel canvas, maximum five-minute timeline, maximum 90-second
masking source, CPU model latency, coarse Haar face detection, occasional soft/flickering mask
edges, representative-frame lighting checks, center crops for aspect changes, and human judgment
for story, word accuracy and aesthetic approval. There is no generative background, AI detail
restoration, automatic B-roll, guaranteed semantic hook, music recommendation or universal
professional-quality score. Those optional/unsupported capabilities are not marked done.

During verification C: dropped below the existing 512 MB disk reserve. The app correctly refused
an upload/export. No source, campaign export or model weight was deleted and the reserve was
not lowered. Reversible NTFS compression was applied to `.venv-asr` (308,540,160 logical bytes
stored in 189,140,933 bytes) and the image environment's static `torch/lib/dnnl.lib` library
(653,534,016 logical bytes stored in 204,214,272 bytes; SHA-256 unchanged). The speech runtime
still imports faster-whisper 1.2.1 / PyAV 16.1.0. Compression can be undone with `compact /U`
on those paths when adequate free space is available. Other disk-space changes during the
session are not attributed to this task.

## Verification evidence

Completed checks (41 backend tests plus two browser workflows):

| Command | Result |
| --- | --- |
| `python scripts/test_video_editorial.py` | 14 passed, including actual lighting/background/replacement renders, proper-name correction, cut approval, review-state gating, render lineage, Arabic pixels, checkpoint invalidation and motion propagation. |
| `python scripts/test_video_mastering.py` | 10 passed; 1 opt-in real-footage case skipped because its environment variable was unset. The supplied source was separately exercised through the real live API below. |
| `python scripts/test_quick_video_edit.py` | 3 passed, including original preservation, per-guest review/revision isolation and cross-origin rejection. |
| `python scripts/test_public_brand_video.py` | 10 passed, including shared Image/GIF guidelines, Arabic burn-in, scoped assets and real HTTP planner-protocol/operation validation. The protocol test uses a stub, not an installed LLM. |
| `python scripts/test_video_audio_bus.py` | 2 passed; real rendered frequency measurements confirm music ducking while SFX retain their level, plus a measured hum fixture/cache check. |
| `python scripts/test_video_storage.py` | 2 passed; a real Windows sharing lock releases during atomic save, and an orphan job becomes failed rather than remaining running. |
| `python scripts/test_video_guided_edit_browser.py` | Passed: guest source/logo/guideline upload, plan, render, decisions, separate QA, download and mobile width. |
| `python scripts/test_video_review_browser.py output/video-review/agency-upgrade/result.json` | Passed against the actual supplied-video result: restoration, visible logo upload, collapsed settings, request status, review transitions/readiness block, previous/current switching, exact download bytes, synchronized playback and mobile width. |

Python compilation, JavaScript syntax and `git diff --check` also passed. The user-supplied
source is described by `scripts/fixtures/office_video.json`; its private bytes stay outside
Git. The general review runner accepts any local source and can resume an existing managed
project after an interrupted export without recomputing completed masks. `--parent-asset`
links the next rendered revision to a previous result.

### Actual office-video results

Artifacts: [edited MP4](output/video-review/agency-upgrade/edited.mp4),
[before/after frames](output/video-review/agency-upgrade/before-after.png),
[API result and both QA reports](output/video-review/agency-upgrade/result.json),
[decoded-frame measurements](output/video-review/agency-upgrade/inspection.json), and
[browser evidence](output/video-review/agency-upgrade/review-browser.json).

The final render is asset `4696519a531c4c86aebc72362f6a616b`, linked to the previous real render
`73fdcf12584948beaffbcd06011e640e`. Both use the original managed source; neither overwrites it.
The source SHA-256 remains
`eb5fbf9b4bb70cb9b1797d1c4dd09069824b9e8f02f5f4d54718d7d241c3b70d`.

Output: 15.7067 seconds, 464×832, source rate 35325/589 (59.9745 fps), H.264 High,
progressive yuv420p, Rec.709 limited-range tags, AAC-LC 48 kHz stereo. No 4K/upscale claim.
The source-project brief supplies Instagram/TikTok, so the final edit uses the versioned
TikTok LTR product-default obstruction profile.

Technical QA: **20 PASS, 3 WARNING, 0 FAIL, 0 NOT_CHECKED**. True peak changes from +0.5
to −1.8 dBTP; integrated loudness from −17.3 to −17.4 LUFS. The limiter ceiling takes priority
over reaching the −16 target. The warnings concern that headroom tradeoff, caption reading
speed/uncertain words, and captions not yet reviewed by a person.

| Measured on decoded full-render frames | 2.50 s source → edit | 10.50 s source → edit |
| --- | --- | --- |
| Approximate face luminance (0–1) | 0.4543 → 0.5166 | 0.3465 → 0.4296 |
| Background-minus-face luminance | 0.2020 → 0.0520 | 0.3226 → 0.1433 |
| Share of clipped highlights | 1.29% → 0.33% | 1.86% → 0.42% |
| Face-region hue difference | 0.4° | 1.5° |
| Upper-left diagnostic ROI sharpness (Laplacian variance) | 312.25 → 2.45 | 408.14 → 3.03 |

These are approximate face-box/ROI measurements, not a skin-quality certification. The source
and edited frames were also visually inspected: the speaker is brighter, the window texture
is softened, captions remain below the face, and the logo is visible within the selected safe
area. Hair and arm boundaries are approximate and still merit watching in motion.

The subject mask contains 188 frames at 12 fps / 266×478, with 52 neural inferences and 136
propagated frames. Mean temporal IoU is 0.9856, there are no abrupt coverage jumps, and mean
subject coverage is 35.84%. Completed masks were reused after the disk-space interruption.
The final cached-mask render took 265 seconds on this machine, including measurement/QA;
that is not real-time performance. The earlier full mask preparation completed within a
364-second job that subsequently stopped at the disk reserve before rendering.

For the exact acceptance instruction:

| Request | Result |
| --- | --- |
| Change the background / make it more professional | PARTLY DONE: actual masked blur/dim/desaturation; no fabricated new office. Approved uploaded-image replacement is separately implemented and render-tested. |
| Edit the lighting | DONE: actual rendered correction and measured brighter face, with lower clipping in the inspected final frames. |
| Add words | DONE: 9 burned caption cues, with names and recognition uncertainty retained for review. |
| Add effects | DONE: measured lighting, masked background treatment, a held 6% emphasis punch-in from 5.36–7.38 s, return to the original framing and short opening/closing fades. |

The edit is deliberately **DRAFT**. The two uncertain names (“Mee”, 52%; “Ahmad”, 16%) require
the user's correction/confirmation. The closing “Okay, that's it” removal is proposed at 48%
confidence and **not applied**; approval would remove about 1.967 seconds. No guessed spelling
or weak semantic cut is silently shipped as approved. The browser test verified that approval
is blocked, then returned its test review state to DRAFT for the user.
