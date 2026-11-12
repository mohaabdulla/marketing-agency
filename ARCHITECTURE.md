# Repository architecture and agency foundation

## Baseline discovered before implementation

FastAPI (`server.py`) serves a vanilla-JavaScript/Tailwind shell (`index.html`).
`campaign_generator.py` owns campaign research/copy/render orchestration;
`visual_engine.py` owns layouts and local/optional remote image adapters;
`agency_suite.py` builds bilingual omnichannel kits. `brand_kits.py` stores legacy brands
as atomic JSON in `static/assets/brand_kits.json`. Media are served under `/renders`,
`/uploads`, `/test_assets` and `/static`.

Video functionality is already separated into `video_*` modules, four UI modules and
`static/css/video-studio.css`. Video assets/projects/jobs use UUID JSON records under
`output/video`; FFmpeg subprocesses render on CPU. The queue has bounded CPU/GPU workers,
persistent lifecycle records, cancellation and startup recovery. `.venv-image` and
optional `.venv-video` isolate inference; `gpu_resources.py` coordinates local GPU use.
Video model installation and actual successful inference are distinct states.

Existing APIs remain unchanged: `/api/generate`, `/api/campaign/generate`, template-swap
aliases, render/export/carousel routes, legacy brands and `/api/video/*`.
Existing optional external providers include Gemini, Pollinations, Cloudflare and Hugging
Face hosted inference. New agency planning must not call any of these providers implicitly.

## Extension boundary

`agency/` adds a modular local planning domain beside the media engines. SQLite is
appropriate for the current single local operator; no PostgreSQL or new frontend framework
is required. Client-scoped opaque IDs connect research, claims, strategies and briefs.
Separate revisions retain immutable brand/brief history, referenced versions and audit events.
Connections enable foreign keys, transactions, WAL and optimistic locking.

UI workspaces share an explicit Client → Project → Campaign → Language context. Changing
context must never silently relabel an older generated asset. Explicit adapters send a
saved brief to Image Studio without changing existing image API formats or auto-generating.

## Production modules (added 2026-11-12)

The same typed-record store now also holds concepts, copy, scripts, storyboards, shots,
assets, licenses, approvals, calendar entries, metrics, snapshots, experiments, reports,
learnings, tasks, scope, costs and pricing (55 record kinds in total; schema version is
still 1 because records are JSON payloads in the existing `records` table).

- `agency/production_schemas.py`: validated models and reference map for those kinds.
- `agency/production.py`: save-time rules (campaign scoping, immutable file facts, frozen
  approval targets, superseding approvals when a record changes) and read-time calculations
  (script length estimate, experiment statistics, pricing arithmetic).
- `agency/content.py`: concept matrix, copy checks, script → storyboard, storyboard →
  Video Studio project (through `video_assets.ingest`, `video_editor.validate_sources` and
  `video_projects.save`; no video code was copied or changed) and storyboard export.
- `agency/assets.py`: content-addressed asset store under `output/agency/assets`, asset
  versions, approval requests/comments/decisions, the brief-approved workflow rule and the
  publication package.
- `agency/analytics.py`: CSV import, summaries, report rendering and the dashboard overview.
- `agency/api_production.py`: routes on the existing `/api/agency` router (same loopback
  guard). `agency/channel_specs.json`: editable platform limits and speaking rates.
- `static/js/agency-production.js`: workspace definitions, nested-row forms, actions and
  downloads, plugged into the schema-driven pages in `agency-workspaces.js`.

Lineage now stored: brief → concept → copy/script → storyboard → shot → asset version →
approval → calendar entry → package export, and metric → snapshot → experiment → report →
learning. Assets and approvals are created only by their own endpoints; file facts are
immutable through ordinary edits.

## Migration and backup plan

The agency database is additive in `output/agency` (configurable). Schema migrations are
versioned and transactional. Unknown/newer databases are rejected. Existing brand JSON,
campaign files and video JSON remain in place. A legacy brand can be copied into a chosen
client explicitly; no automatic assignment or deletion occurs. SQLite backup uses its
online backup API; integrity and foreign keys are checked. Restore targets a new directory,
preserving the source database and all existing media.

## Acquisition, audio and privacy extensions

The same version-1 typed-record table now contains SEO audits/briefs, landing pages, contacts, segments, email templates, retention policies, audio projects, subtitles, content pillars/series, ad plans, creators and creator briefs. Shared validation types live in `agency/schema_types.py`, so model files can be imported independently without a circular registry import.

`acquisition.py` performs HTML inspection, page/email rendering, contact import and consent-aware segmentation. `audio.py` uses the existing bounded FFmpeg helper with private agency jobs and asset storage; `asr_worker.py` is an optional local-files-only CPU worker. `privacy.py` provides client portability exports, retention review and explicit erasure. `planning.py` performs budget/UTM calculations and draft plan export. Their `api_*` modules extend the same protected router; `agency-acquisition.js` attaches real actions to the existing schema-driven UI.

Asset creation/export/erasure serialize through a re-entrant store lock in the supported single-process local server. Run one uvicorn process. Client erasure checks a fresh review token and preserves content-addressed files still referenced by another client. Full backup/restore remains separate and retains all current/historical asset versions.

Remaining boundaries: multi-user auth/RBAC, actual installed text/ASR/video inference verification, TTS synthesis, full-site crawling and optional external posting/mail/analytics adapters. Existing manual workflows remain usable without these services.

## Baseline execution

Before application changes: all 17 collected `scripts/test*.py` suites passed via the
offline regression runner. Video backend: 12 tests passed; agency integration: 8 passed.
`tests/`: 27 ran, 22 passed, five known failures (old brand colors, old dimensions, image
fallback expectation). `tests/browser_smoke.py` fails its existing visual-unavailable
assertion. The standalone video browser test initially failed an export-duration assertion,
then passed when rerun; the full regression runner also passed it. Preserve the initial
failure as timing/environment evidence rather than calling the baseline entirely green.
Logs: `output/agency-baseline/`, plus its saved `script-results.json`.
