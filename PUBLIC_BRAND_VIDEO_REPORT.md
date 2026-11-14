# Public testing + brand-guided video report — 2026-11-14

## Delivered

Explicit public testing now gives anonymous visitors isolated creative workspaces. The
existing Video Editor accepts shared documents/brand kits, reviews extracted rules,
analyzes footage, previews validated plans, applies/rejects actual timeline changes,
renders, checks guidelines, revises/undoes/redoes, reloads and exports.
Reviewed SRT captions, including Arabic, are actually burned into video. Original media
and documents remain unchanged. Image/GIF reuse the same guideline library.

No account, registration, subscription or credit system existed in this checkout.
None was removed, and no shared account or fake authenticated-user migration was invented.
Default-off normal mode is loopback-only; public mode does not grant operator privileges.

## File groups

New:

- `public_access.py` — opt-in mode, opaque cookie, scope, origin/path/upload/storage safeguards.
- `brand_guidelines.py`, `brand_guideline_worker.py`, `guideline_api.py` — shared bounded
  parsing/library, retained originals, review/evidence and Image response compatibility.
- `video_brand_editing.py`, `video_guideline_api.py`, `video_fonts.py` — actual local HTTP
  planning, strict operation validation, proposals/rejection, rules, compliance and SRT import.
- `static/js/{public-session,shared-guideline-picker,video-brand-editor}.js` — integrated UI.
- `scripts/{test_public_brand_video,test_public_brand_video_browser,cleanup_public_workspaces}.py`.
- `requirements-brand-video.txt`, `PUBLIC_TESTING.md` and this report.

Extended:

- `server.py`, `campaign_generator.py`, `brand_kits.py` — guest output/uploads/brands, shared
  documents, safe public page fetches and private sample/template behavior.
- `video_{storage,assets,jobs,projects,operations,editor,api,ai_editor}.py` — scoped workers,
  real imports, validated edits/fonts, genuine AI requests and Windows-safe revision temps.
- `creative/{storage,api}.py` — isolated layered projects/renders and rendering budgets.
- `agency/{database,jobs,security,assets,documents,tts,music,portal,research}.py` — isolated
  repositories/files, copied contexts, private review links and pinned public page fetches.
- `scripts/run_agency_regressions.py` isolates video/agency storage and testing-mode settings for regression subprocesses.
- `index.html`, `static/js/{video-editor,video-studio,workspace-navigation,app-context,agency-workspaces,campaign-command-center}.js`,
  `.env.example` and `README.md`.

Pre-existing user UI changes and unrelated working-tree edits are preserved. No secrets,
model weights, live user data, firewall or internet deployment were changed. Tests use
temporary storage; sample JPEGs modified by regressions are restored to their starting bytes.

## Verification

- New backend suite: 10 tests cover guest isolation, operator denial, CSRF, expiry/cleanup,
  real PDF/DOCX/text parsing, originals, brand kits, corrections/conflicts, actual still/GIF/
  video output, Arabic caption pixels, HTTP planner protocol, stale/rejected plans and revisions.
- Real public browser workflow passes: upload, review/confirm, measured analysis, SRT import,
  preview/apply/reject, rendering, revisions, Image/GIF reuse, second-guest isolation,
  actual export/download, preserved operator browser drafts, guest draft reload, mobile overflow and JavaScript checks.
- Existing Video Studio backend: all 12 tests pass, including real FFmpeg output/imports.
- Agency verification: 55 backend checks and three real browser scenarios pass.
- All 19 media suites pass: the 17 existing suites plus the new public backend and browser suites.
- The local-model probe reports unavailable. The planner's HTTP stub validates integration,
  not actual model inference. FFmpeg renders, source preservation and caption pixel checks
  use real media.

The five earlier legacy `tests/` expectation differences were not altered or claimed fixed.

## Limitations and enablement

Real local-model inference remains unverified while the runtime/model is unavailable.
Optional diffusion/transcription require their existing dependencies/hardware.
Missing models are technical setup issues, not premium restrictions.

Extraction/Auto Polish have the explicit scope in `PUBLIC_TESTING.md`; advanced interpretation
needs local AI or manual edits. Compliance marks unsupported semantic/pixel checks honestly.
There is no authenticated account backend or guest-to-account migration to claim.
Use one process and HTTPS for internet testing. No hosting/domain was configured.

~~~powershell
python -m pip install -r requirements-brand-video.txt
$env:PUBLIC_TEST_MODE = "true"
python -m uvicorn server:app --host 0.0.0.0 --port 8000
~~~

For persistence, set `PUBLIC_TEST_MODE=true` in `.env` and restart. Code/configuration defaults
remain false. `PUBLIC_TESTING.md` documents storage, expiry, cleanup and the complete workflow.
