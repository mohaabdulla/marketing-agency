# Unified workflow and website repair report

Implemented in the existing LEXNIS application, 2026-11-14.

## Reference inspection

Read the actual Image & GIF HTML, inline state and event handlers, company/brand kit
controls, guideline upload/paste/review, post-type quick fields, prompt enhancement
and approval modal, visual uploads/template swap, generation payload, progress/errors,
bilingual carousel, motion assets, and downloads. Its useful pattern is a concrete
brief and source assets followed by reviewed instructions and a visible output kit.

Also inspected Video Studio modes/library/projects, timeline editing/properties,
analysis/jobs/exports, shared guideline APIs/parsers, local model adapters, public
session/storage guards, the schema-driven agency pages and their production/acquisition
actions, and Command Center context/stage/export handling.

## Problems and changes

| Problem found | Repair |
|---|---|
| Image/GIF used `isPythonBackendActive && backendApiBase`, rejecting the valid empty same-origin API prefix. | Uploads and prompt suggestions now call the actual same-origin backend. |
| A failed guideline upload could fall through to client-side text reading, report success for a binary file, or fabricate extracted image directives. | Rejected uploads display the backend reason. Missing backend produces an actionable error. The false-success fallback was removed. |
| Video generation offered no dedicated guideline upload and sent no guideline context. | A visible Brand Guidelines step supports upload/replace, existing shared documents, brand kits, rule corrections, original downloads, confirmation and removal. |
| Video guidelines affected the editing API but not generated outputs. | Generation freezes the reviewed document version before queueing, enriches the real diffusion-worker prompt, applies checked timeline styling to supported output features, saves an editable project/revision, and reports compliance limitations. CPU image animation uses the same route. |
| Prompt assistance was inconsistent and the older image review flow could imply AI use for a fallback. | One task-aware assistant service and UI provides explicit local-model and editable-template modes. The image review modal also uses this service. |
| Users had to find controls across large screens without a shared progression. | Image/GIF, Video Generation and Video Editor have eight numbered steps with Back/Next. Optional focused mode shows one step; the default keeps all controls accessible. Existing nodes are moved, preserving handlers and values. Creative agency record forms use four meaningful scope/objective/assistant/save steps. |
| Video generation drafts restored only after asynchronous library/model loading, risking late overwrites. | Prompt/objective/static settings restore immediately; dynamic selections restore without replacing user edits. The last completed video preview/download is restored only from the current workspace's managed media library. Guest-scoped browser keys remain intact. |
| Command Center used stale independent browser IDs. | It uses the selected Agency Context. |
| Command Center export navigated with GET to a POST-only endpoint. | It posts to the real endpoint and downloads the ZIP, with progress and error feedback. |
| Command Center interpolated stored text into HTML. | Text is escaped and progress values are bounded. |
| Public Image generation supplied private bundled template/portrait URLs when only one asset was uploaded. | Public requests use only the visitor's uploaded assets. |
| Starting a new timeline left stale guideline association text visible. | Both video guideline panels synchronize when a project is opened or reset. |
| The desktop navigation could extend beyond the viewport with no scroll area. | The existing rail now scrolls, including its lower destinations. |

## Updated workflows and pages

- **Image & GIF:** existing controls, visual identity and social-kit output are retained.
  Shared rule review is now the same component used by Video. Settings that were inside
  the initially hidden result area are available before generation. The output choice
  describes the existing kit truthfully: matching static cards and a looping GIF.
- **Video Generation:** choose supported AI mode or CPU image animation, upload/select and
  review guidelines, describe the objective, accept/edit a suggested prompt, configure,
  generate, preview, download, and open the saved timeline for revisions.
- **Video Editor:** import footage, review shared guidelines, describe an objective,
  prepare actual editing instructions, configure, analyze/propose/apply or reject,
  preview/check/revise, and export using the existing non-destructive timeline.
- **Agency creative forms:** the shared assistant works on prompt-bearing campaign,
  brief, concept, copy, script, storyboard, shot, web, email and related description fields.
  Accepted suggestions change the exact record field and its normal saved revision.
  Stored client/campaign brand context is resolved in the workspace-scoped backend.
- **Command Center:** selected context, safe display and real ZIP export.
- **Other agency pages:** retain their existing validated record, preview, check and
  export workflows. Data-only contact, approval, consent and numeric controls are not
  represented as AI generation tasks.

## Shared assistant behavior

`GET /api/creative/assistant/capabilities` checks the configured loopback model.
`POST /api/creative/assistant/suggest` validates the task, action, target field limit,
objective/audience/message/style/platform/language/CTA, and optional selected guideline
or client brand. Tasks have distinct instructions for image, GIF, video generation,
video editing, campaign, copy/storyboard, audio, web and CRM.

Generate, Improve, Make More Professional, Apply Brand Guidelines and Simplify produce
a suggestion for review. Use Suggested Prompt updates the real destination field;
Edit Manually focuses it. Nothing renders, saves or publishes automatically from an
assistant click. Templates retain supplied facts and list missing details; they are
labelled as templates. Real local AI calls use bounded input/output, token-budget checks,
a strict JSON schema, a shared model lock and the existing loopback-only HTTP adapter.
No paid API is required by this assistant.

## Guideline generation and limitations

The existing shared parsers support PDF, DOCX, UTF-8 TXT/Markdown and structured JSON.
Originals and versioned reviewed rules stay in the managed workspace. Project association
retains the document ID, version and rule snapshot. Wrong-guest, unconfirmed or stale
documents cannot be silently used to start generation.

The same checked editing operations apply supported typography, logo overlays, approved
CTA/disclosures, aspect/duration rules, fades and existing audio/caption styling. Diffusion
prompts receive the selected context; that does not prove a model obeys every visual rule.
Compliance still explicitly marks unsupported semantic/pixel checks as not checked.
CPU animation preserves the supplied image and follows the selected motion setting;
free-form prose is retained as context and does not become arbitrary animation code.

The local text runtime/model is unavailable on this installation. Actual AI inference
and diffusion quality therefore remain unverified. HTTP protocol tests use a fixture,
clearly distinguished from a real model. Optional diffusion, ASR and TTS still require
their documented runtimes, models, licenses and hardware. Reviewed SRT/manual editing,
templates and CPU image animation remain usable.

Public mode stays opt-in. No login/paywall system, account migration, hosting, paid
connector, external publishing, model download, firewall change or secret was added.

## Verification

- `python scripts/test_unified_workflows.py`: 4 passing backend tests, including real
  FFmpeg branded CPU output, editable project/revisions, original preservation,
  task-aware template context, wrong-guest/stale/unreviewed rejection, and an actual HTTP
  model-protocol fixture.
- `python scripts/test_video_studio.py`: 12 passing existing video tests, including
  actual rendering, imports, timing, Arabic titles, audio and exports.
- `python scripts/test_public_brand_video.py`: 10 passing existing public/brand tests,
  including isolated guest media/projects/jobs, real parsing and Arabic caption pixels.
- `python scripts/verify_agency.py --browser`: all 55 backend checks and three existing
  real agency browser scenarios pass.
- `python scripts/test_public_brand_video_browser.py`: passes the existing real guest
  upload/review/analyze/edit/reject/render/revision/export/Arabic/reload/mobile workflow.
- `python scripts/test_unified_workflows_browser.py`: passes. Evidence is recorded in
  `output/unified-workflows/result.json` and desktop/mobile screenshots. The test exercises
  actual still/GIF and branded CPU video output, assistant request handoff, invalid-file
  errors, all 20 public workspace destinations, Command Center ZIP/escaping, retained
  state and mobile layout. External providers are disabled; media rendering is real.

Historical palette/geometry expectations in the older ignored `tests/` directory were
not rewritten to conceal differences; no claim is made that every historical fixture
or every optional local-model installation passes.

## Changed files

- New: `prompt_assistant.py`, `static/js/{creative-workflow,image-workflow,guideline-review}.js`,
  `static/css/creative-workflow.css`, `scripts/test_unified_workflows{,_browser}.py`, this report.
- Extended: `server.py`, `video_engine.py`, `video_projects.py`, `index.html`,
  `static/js/{video-studio,video-editor,video-brand-editor,shared-guideline-picker,agency-workspaces,campaign-command-center,workspace-navigation}.js`.
- Existing browser tests now retain JavaScript stack traces in failures.
- README, Video Studio and public-testing guides link to this report.

Enable with the existing environment/dependencies:

```powershell
python -m pip install -r requirements-brand-video.txt
$env:PUBLIC_TEST_MODE = "true"
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Use one process. Internet testing needs the existing documented HTTPS deployment setup.
No runtime/model availability is implied by enabling the feature flag.
