# Video production pipeline: audit and implementation record

## Phase 0 audit — 19 November 2026

The starting repository already has a four-step brief wizard, company research, editable storyboards,
asset upload, local image animation, local diffusion workers, a non-destructive editor, revisions,
brand compliance checks, narration, measured audio mastering, caption timing and MP4/WebM exports.
The new producer workflow must coordinate these components rather than replace them.

| Capability | Existing implementation |
| --- | --- |
| Brief, script and source evidence | `video/director.py`, `video/script_writer.py`, `video/company_intro.py`, `video/company_research.py` |
| Brand rules and typography | `brand/guidelines.py`, `brand/kits.py`, `video/brand_context.py`, `video/brand_editing.py`, `video/typography.py` |
| Local model registry and inference | `video/models.py`, `video/engine.py`, `scripts/render_local_video.py`, `scripts/setup_local_video.py` |
| Worker queue and GPU isolation | `video/jobs.py`, `core/gpu_resources.py` |
| Timeline, transitions and revisions | `video/projects.py`, `video/editor.py`, `video/operations.py`, `video/revisions.py` |
| Voice, subtitles and audio | `video/voice.py`, `video/caption_timing.py`, `video/audio.py`, `video/qa.py` |
| Safe composition and colour | `video/layout.py`, `video/platforms.py`, `video/grade.py` |
| Technical and editorial checks | `video/qa.py`, `video/editorial_qa.py`, `video/review.py` |
| Existing UI and routes | `static/js/video-studio.js`, `static/js/video-brief-wizard.js`, `video/routes/` |
| Regression coverage | `scripts/test_video_*.py`, `scripts/test_company_intro_video.py`, `scripts/test_storyboard_coach.py` |

Gaps to implement: a separate producer workspace, immutable governance snapshots, stable shot IDs,
structured continuity and camera notes, per-shot candidates and staged review gates, provenance for
every take, explicit model routing, final release tied to the exact reviewed edit and render, and a
delivery archive containing storyboard/script documents and all audit metadata.

## Observed hardware and starting model inventory

- NVIDIA GeForce RTX 4060 Laptop GPU: 8,188 MiB total VRAM.
- System memory: 15.7 GiB.
- `.venv-video` exists; diffusion dependencies are isolated from image rendering.
- CogVideoX-2B weights and a smoke-test marker exist. A marker is not a fresh live inference test.
- Wan2.1 and Wan2.2 adapters exist; Wan weights are not installed on this machine.
- Existing timeline canvases are capped at 1920 pixels per edge. Do not advertise 4K delivery without
  implementing and verifying the entire higher-resolution composition path.

## Research corrections and primary references

- Wan2.2 TI2V is a **5B** model; the 1.3B low-memory model belongs to Wan2.1. The vendor's normal
  Wan2.2 TI2V path specifies a substantially larger GPU than this laptop. Hardware-specific tests,
  not a general survey, determine what the UI can offer.
  [Wan2.2 model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)
  and [Diffusers implementation](https://huggingface.co/docs/diffusers/en/api/pipelines/wan).
- LTX model weights have model-specific terms; Apache licensing of code does not make all weights
  unrestricted. Avoid making enterprise eligibility claims based solely on the code repository.
  [LTX model card](https://huggingface.co/Lightricks/LTX-Video).
- Corporate logos, exact wording and typography remain compositor-owned layers. Generated plates
  must not be treated as approved artwork or as a reliable way to render critical text.
- The supplied claim of a 37% attention improvement from rule-of-thirds framing has not been
  established by a primary source. Use editable framing guides without presenting that statistic.
- Story, continuity and spelling cannot be guaranteed by FFprobe. Technical checks and explicit
  human approvals are separate and must be labelled accordingly.

## Verification policy

Test CPU/offline execution, model adapter contracts, workspace ownership, immutable approvals,
candidate invalidation, actual FFmpeg exports and archive integrity. Label model mocks as mocks.
Only claim GPU inference verification for a model and exact installed revision that were actually run.
Unavailable models must explain installation and hardware requirements; never silently substitute
an animated still while reporting diffusion success.

## Using the producer workspace

Start the existing application with `python server.py`, open its printed local address, and select
**Video Production** in the navigation. Existing Video Generation, Video Editor, Image & GIF Studio
and agency destinations remain available.

1. **Brief:** choose a brand, goal, audience, language, duration and format. Supply exact script words
   if available. Upload a guideline, inspect the extracted rules, and confirm them before creation.
   Creation freezes the selected brand/rules/logo hash/font choice; later brand-kit edits do not
   silently change this production. Start a new production to adopt new governance.
2. **Script:** inspect the draft and frozen pack. The optional script assistant contacts only the
   configured loopback llama.cpp service. Without that service, an explicitly labelled structured
   draft retains supplied wording. It does not pretend to have performed AI inference. A named
   reviewer approves the current script; factual accuracy still requires human review.
3. **Shot planning:** edit headlines, narration, duration, camera, subject, action, location, wardrobe,
   props, references, transitions and continuity notes. Save every changed shot and reapprove the
   script. Stable shot IDs and revision hashes preserve traceability. Unsaved edits survive saving
   another shot; approvals and generation require saving them first.
4. **Generation:** select an appropriate method, or use automatic routing: uploaded video means real
   footage; an approved still means deterministic image animation; otherwise use motion graphics.
   Diffusion is an explicit selection, never a hidden fallback. Accuracy-critical material requires
   real footage or a still. Batch concept drafting is available. Each shot needs separately named
   concept, continuity and final reviews. Subsequent takes record their approved parent, full prompt,
   seed, model/revision/licence, source hashes and native generation specification. All intermediate
   candidates remain available. Regeneration never approves a take automatically.
5. **Editing:** choose offline narration or recorded voiceover, licensed music, subtitle burn-in and
   platform variants. Build the master, then open its timeline in the existing Video Editor for
   multi-track edits, exact typography/logo layers, framing, grading, transitions, audio, local AI
   edit proposals and revision undo/redo. Save edits there and return to render the current revision.
   Rebuilding from approved shots preserves the old editor project and history. Audio choices apply
   at timeline construction; adjust existing tracks in the editor or rebuild before changing them.
6. **Review:** run brand compliance, watch the master and each variant, and inspect technical QA.
   Confirm story, continuity, readable wording/captions, audio and usage rights under a reviewer name.
   Managed title/caption palette, fonts, logo artwork/placement, required/prohibited wording and frozen
   rules are checked separately from human visual judgement. A contrasting caption colour is selected
   and recorded in the frozen pack when the supplied guideline does not specify one.
7. **Delivery:** approval produces a private, hash-checked client ZIP. Editing a reviewed timeline,
   changing media, missing QA, or a failed technical result invalidates release/download readiness.
   Preview media remain available to their owning workspace for review; release gates control the
   approved client handoff, not whether an owner can copy a preview.

The producer supports 6–60 second films, up to six script scenes, up to 36 candidates per shot,
30 fps H.264 masters at 720p/1080p, plus independently rendered/reflowed platform variants.
Diffusion retains each model's native dimensions/frame rate in provenance: a 30 fps export or larger
canvas is not a claim of native 30 fps/1080p generation. A continuity gate is a human comparison, not
an identity-lock model. Choose an approved reference and I2V-capable model when image conditioning
is needed. No automatic face cloning, lip-sync, native 4K, LTX or Coqui integration is claimed.

## API and persistence

Producer routes are under `/api/video/productions` in `video/routes/production.py`:

| Operation | Method/path suffix |
| --- | --- |
| List/create/open | `GET /`, `POST /`, `GET /{id}` |
| Save shot | `PUT /{id}/shots/{shot_id}` |
| Approve script | `POST /{id}/approve-script` |
| Queue take | `POST /{id}/shots/{shot_id}/generate` |
| Review take | `POST /{id}/shots/{shot_id}/review` |
| Brand checks | `POST /{id}/check` |
| Rebuild/edit/render | `POST /{id}/reset-timeline`, `POST /{id}/render` |
| Approve handoff | `POST /{id}/release` |
| Reviewed downloads | `GET /{id}/delivery/{zip|master|9x16|1x1|16x9}` |

All mutations carry `expected_version`. Stale versions or an active production job produce 409;
invalid gate ordering produces 400; another guest's IDs produce 404. Take requests specify
`pass_name` (`concept`, `continuity`, `final`). Reviews include the exact candidate ID, reviewer,
and required intent/continuity/readability attestations. Render/release return 202 jobs; poll
`/api/video/jobs/{id}` or cancel with `POST /api/video/jobs/{id}/cancel`. Cancellation never publishes
a result. Abandoned or cancelled-before-start workers are reconciled when the production is opened.
GPU jobs use the existing isolated worker and cross-workspace GPU resource lock. CPU work runs in
the existing bounded queue. Queue and storage metadata locks use consistent ordering.

`video/production.py` owns transitions and atomic versioned records, `production_text.py` plans only
through local text inference, `production_render.py` reuses existing sequence/editor/mastering code,
and `production_delivery.py` creates the portable archive. Their schemas reject editable server
governance/candidates/approvals. Public-test storage uses existing guest scoping; files and assets
are addressed with validated UUIDs, never arbitrary client paths. Upload checks, quotas, job limits
and FFmpeg timeouts remain enforced by the existing media layer.

The archive contains:

```text
video/VIDEO_<production>_master_v<version>.mp4
video/variants/<aspect>.mp4
script/script.txt
script/script.pdf
storyboard/storyboard.pdf
captions/subtitles.srt
captions/subtitles.vtt
media/<asset-id>.<extension>
audit/project.json
audit/governance.json
audit/shots-and-takes.json
audit/review-history.json
audit/quality.json
audit/release-review.json
manifest.json
README.txt
```

The manifest maps portable media IDs and SHA-256 hashes for every archive member except itself.
PDFs preserve English/Arabic typography as raster pages; script.txt supplies searchable wording.
Font files are not redistributed. Subtitle timing is narration-aligned when local narration supplies
timing; otherwise it uses the existing explicitly reported scene/text timing, not invented ASR.
Recorded audio and any generated speech require listening review for sync.

## Local setup and diagnostics

No new dependency is required for deterministic production: FastAPI, Pillow, FFmpeg/FFprobe and the
existing typography/caption/audio stack are reused. Piper or installed Windows voices provide offline
speech; Piper engine and individual voice licences must be checked separately. Configure the existing
local text service with `LOCAL_TEXT_URL`/`LOCAL_TEXT_MODEL` (see `scripts/setup_local_text.py`). The
producer text adapter rejects hosted URLs and disables proxies/redirects.

Diffusion is opt-in and isolated in `.venv-video`. Inspect/install using the existing commands:

```powershell
python scripts/setup_video_tools.py
python scripts/setup_local_video.py --model cogvideox-2b --accept-license
python scripts/verify_local_video.py --model cogvideox-2b --run-inference --quality draft
```

The CogVideoX low-memory path stages quantized T5 prompt encoding separately from FP16 video weights.
The default encoder is 8-bit; `VIDEO_TEXT_ENCODER_BITS=4` selects optional NF4/double quantization.
T5 modules are mapped individually so Transformers does not first place a whole unquantized shard
on CUDA. Worker fault traces and native exit codes remain in local job diagnostics. A newer failed
run invalidates the previous verified label; it never substitutes CPU motion and reports AI success.
Wan2.2 and Wan2.1 adapters are supported but unavailable until their own installation/hardware gates
pass. This laptop does not meet their configured memory requirements. No model download occurs
at application startup or as an implicit fallback.

## Verification commands

```powershell
python scripts/test_video_production_pipeline.py --browser
python scripts/test_video_brief_workflow.py
python scripts/test_video_creation.py
```

The producer suite performs actual FFmpeg generation through all three passes, master and vertical
composition, measured QA, release locking, PDF parsing, subtitle/ZIP/hash validation and a stale NLE
edit check. It separately covers ownership, immutable governance, accuracy-critical routing, local-only
drafting, parent-take invalidation, missing QA, wrong palette, abandoned worker recovery and reviewer
validation. Chromium exercises production creation, shot editing, approvals, mobile width and legacy
image navigation. Diffusion adapter tests use explicitly labelled mocks; only the separate inference
command establishes actual GPU model verification. Run GPU inference separately from render suites
on constrained laptops: GPU loading can consume shared memory/pagefile and available disk.
CPU concept takes use a 360-pixel short edge and transition handles; subsequent CPU takes use the
approved delivery canvas. Diffusion concept takes use 20 steps at the model's native dimensions;
continuity/final use 50 steps. Draft workers are bounded at 30 minutes, standard workers at 60 minutes
to accommodate measured CPU-offload latency on this 8 GB GPU. Cancellation remains available.

## Recorded acceptance results — 19 November 2026

| Verification | Result |
| --- | --- |
| Producer pipeline, including Chromium | 9 passed; 382.9 seconds |
| Final brand-review UI browser rerun | 1 passed; 43.3 seconds |
| Final editor handoff, reviewer policy and exact-length footage regression | 3 passed; 31.6 seconds |
| Final reader/adapter contract rerun | 1 passed; 3.3 seconds |
| Guest admission/recovery during a producer transaction | 1 passed; 1.5 seconds; abandoned-job recovery and lock order |
| Existing brief/storyboard workflow | 11 passed, 1 browser case skipped; 303.5 seconds |
| Existing video creation and motion checks | 7 passed; 436.2 seconds |
| Image/GIF contract, measured motion, ZIP and browser dashboard regression | 4 passed; 299.0 seconds |
| Python compilation, JS syntax and diff whitespace | Passed |

The producer acceptance artifact is `output/producer-verification/approved-client-kit.zip`:
720×720 at 30 fps for the test master, 1080×1920 at 30 fps for its vertical variant, three shots,
nine real CPU-composed candidates, valid script/storyboard PDFs and SRT/VTT, and a 24-member hashed
manifest. The low-motion abstract fixture produces a `frozen_frames` WARNING in both outputs;
the report retains it for human review rather than reclassifying it as PASS. Core measurements
(decoding, dimensions, duration, intended frame rate and codec) must pass before any release.
The fixture's review attestations are test inputs, not a claim of independent creative/client approval.
The suite confirmed that changing the saved NLE revision invalidates the approved download.

Initial attempts exposed and fixed missing palette contrast in the frozen pack, a shot-save HTTP
method mismatch, queue/storage lock ordering, and missing transition handles that caused costly
unnecessary optical-flow retiming. Final CPU rendering was tested after those fixes. Earlier GPU
attempts failed with Windows exit code `3221225477` in full-shard text-encoder loading; their old
smoke marker was explicitly invalidated. The module-level loading change requires its own fresh
inference result, recorded separately below.

The isolated runtime was checked directly after a cold-start inspection timeout: Torch imported in
15.9 seconds, Diffusers in 42.0 seconds total, CUDA and BF16 both available. The readiness probe now
allows up to 180 seconds for cold Windows imports without blocking the FastAPI event loop.

Module mapping alone did not resolve the native storage-slicing crash. The installed Safetensors
0.8.0 supports `backend="pread"`, including positional reads on Windows. The isolated worker now
selects that backend before importing Transformers/Diffusers; the web process and older Safetensors
versions are unchanged. `VIDEO_SAFETENSORS_BACKEND=mmap` is an explicit diagnostic override.
A real 4096×4096 T5 weight tensor was read through the positional backend and checked for finite
values successfully. This is a loader check, not proof of completed diffusion inference.
See the [official backend implementation](https://github.com/huggingface/safetensors/blob/v0.8.0/bindings/python/src/lib.rs)
for the supported positional reader and Windows implementation.

### Fresh local GPU inference result

The repaired loader completed real CogVideoX-2B inference on this RTX 4060 Laptop GPU:

- Installed revision: `1137dacfc2c9c012bed6a0793f4ecf2ca8e7ba01` (`zai-org/CogVideoX-2b`).
- Draft quality, 20 diffusion steps; staged **8-bit T5 / FP16 video**, Safetensors positional reader.
- Measured generation/export time: **1,053.3 seconds (17.6 minutes)**.
- Native model output: **720×480, 49 frames, 8 fps**, 6.125 seconds.
- Verified padded export: **1280×720, 24 fps, 147 frames**, H.264 High, yuv420p, progressive,
  Rec.709 SDR tags, no audio. This export resizes/repeats native frames; it is not native 720p24.
- Core technical measurements passed; QA retained a low-motion/frozen-picture WARNING for review.
- The worker exited and released GPU memory (approximately 99 MiB used afterwards).
- The previous failed marker was replaced only after actual output validation. The 50-step standard
  profile and Wan models were **not** live-tested; Wan remains unavailable on this hardware.

Local evidence: `output/producer-gpu-pread.log`,
`output/producer-verification/local-ai-smoke.mp4` and `local-ai-smoke.json`, alongside the CPU kit
and browser screenshots. The project documentation does not redistribute model weights.

The laptop's free disk space briefly fell below the media guard while decoding with CPU offload,
then recovered after worker exit. Avoid running render suites alongside GPU inference and keep ample
disk/pagefile headroom. Those guard failures were not bypassed; the affected targeted tests were
rerun after inference completed and passed. The expanded browser check also confirmed the producer
bridge opens **Advanced editor → Preview & improve** with the expected owned timeline and clips.
Exact-length accuracy-critical footage was tested through real FFmpeg upload and candidate export.

Across the producer's eleven distinct cases, eleven executed legacy brief cases, seven legacy creation
cases and four Image/GIF cases, **33 distinct automated cases passed**. One optional legacy browser
case was skipped; producer and Image/GIF browser cases ran successfully. The separate real GPU
inference benchmark is additional evidence, not a substitute for final human creative review.
Final hardening also aligns guest-session queued-job recovery with the storage-then-queue lock order;
its regression admits a guest with an abandoned job while a producer transaction owns storage.

## Follow-up improvements — 20 November 2026

The existing producer workflow now includes these additional controls:

- **Complete script context:** local drafting receives campaign goal, tone, language, runtime,
  aspect ratio, pacing, continuity notes, approved tagline and frozen rules. Headlines and narration
  are checked for unsupported numbers and prohibited wording. Generated narration must also fit the
  requested word budget and editable field limits. Invalid model output uses the labelled editable
  template; supplied scripts retain their wording. These checks support human factual review.
- **Example briefs:** select a brand and goal, then load an English or Arabic example. Existing
  message text is preserved. Examples contain general directions; replace them with approved company,
  product or vacancy details before requesting a script.
- **Actionable take reviews:** each pass supports approval or rejection with a feedback note and
  correction area: intent, continuity, readability, motion, brand or other. Rejection requires an
  explanation. Each candidate retains its named review history and suggested next steps. Earlier-gate
  rejection clears downstream approvals and the current render/release; unchanged footage needs an
  explicit re-review before it can enter a new approved export. Advice is a deterministic review aid,
  not an assertion that a vision model detected the defect.
- **Draft conflict protection:** unsaved edits retain their original shot revision across refreshes.
  If another editor changes that shot, the UI preserves the local draft and blocks saving it over the
  newer revision. Use its **Discard unsaved edits** button to load the current saved shot. Saving a
  different shot continues to preserve other local drafts.
- **Composition controls:** shot planning exposes still-image motion and motion-graphics background
  choices. Candidate previews have optional rule-of-thirds guides. These guides stay in the browser
  preview and are never burned into media or client exports; no attention/retention statistic is claimed.
- **Take provenance:** new takes record requested quality, diffusion step count and the inference
  profile returned by the engine. CPU takes record no diffusion step count. Review history and these
  settings travel with the existing `audit/shots-and-takes.json` and archive manifest.

The review endpoint keeps its existing path and version checks. To reject a selected current take,
send `approved: false`, a nonempty `note`, the `reviewer`, `gate`, `candidate_id`, `expected_version`
and optional `issue`. Existing approval requests remain valid. Readability, intent and continuity
attestations are still required at their existing approval gates.

The [CogVideoX-2B model card](https://huggingface.co/zai-org/CogVideoX-2b) and
[Wan2.2 TI2V-5B model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers) were rechecked
for the model/licence distinction in the supplied plan. Both cards identify Apache-2.0 weights;
Wan2.2 TI2V remains the 5B model. This follow-up installs no additional weights and does not alter
the local engine or the hardware availability gates. The recorded 19 November GPU benchmark above
remains historical evidence, not a fresh inference claim for this follow-up.

Run `python scripts/test_video_production_pipeline.py --browser` for the expanded suite. It includes
protocol-mocked script drafting, rejection feedback and downstream invalidation, browser draft conflicts,
editable examples/motion controls, framing guides, editor handoff, and real FFmpeg/PDF/ZIP delivery checks.

Follow-up verification results:

| Check | Result |
| --- | --- |
| Expanded producer suite, including browser and real render/export workflow | 14 passed; 178.5 seconds |
| Final browser rerun with framing guides, rejection history, conflicting draft and editor handoff | 1 passed; 10.7 seconds |
| Client archive inspection | 24 hashed members; 13 recorded reviews; every take includes generation settings |
| Python compilation, JavaScript syntax and diff whitespace | Passed |

Evidence logs are `output/producer-full-nov20.log` and
`output/producer-framing-browser-nov20.log`. Browser evidence adds `draft-conflict.png` and
`take-review.png` under `output/producer-verification/`. The client ZIP in that directory was
regenerated by the real CPU acceptance run. No GPU inference was repeated in this follow-up;
the unchanged model worker's previous benchmark remains labelled with its original date.
