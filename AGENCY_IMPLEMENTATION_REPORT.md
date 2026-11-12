# Agency implementation report ` 2026-11-12

This report supersedes the earlier foundation-only status. The application now has 55 validated record kinds and 20 working sidebar destinations. This is a local, single-operator application; passing checks does not establish production readiness or complete every optional capability in the master blueprint.

## A`B. Working capability and phase boundary

| Phase | Verified completion boundary |
| --- | --- |
| 0 Baseline | Complete: repository map, known pre-existing failures, regression evidence and migration/backup plan |
| 1 Foundation | Complete for one local operator: SQLite, IDs, client/project/campaign scope, immutable revisions, audit, optimistic edits, bounded private jobs |
| 2 Clients/brands/claims | Complete local core: onboarding, stakeholders/access metadata, brand versions, glossary, evidence and approved/expired claim checks |
| 3 Research/strategy | Complete bounded local core: UTF-8 imports, controlled one-page snapshots, findings/hypotheses, competitor/audience/JTBD/journey/positioning/messages/offers/strategy |
| 4 Campaigns | Complete local core: campaign/brief/channel/deliverable records, strategy-to-brief, review-plan export and explicit Image Studio handoff |
| 5 Local text | Partial: CPU llama.cpp adapter, schema/context/time/cancellation bounds and provenance exist. Qwen weights/runtime are not installed or inference-verified; no local AI copy generation beyond brief drafting |
| 6 Content | Complete manual production core: concept matrices, copy variants/checks, scripts, timed storyboards/shots, organic pillars/series and source links; no claim of AI-written content |
| 7 Video/audio | Editing core works: existing Video Studio preserved, storyboard-to-project, real private FFmpeg audio processing, editable timed SRT/VTT. Optional CPU Whisper adapter exists but is not installed/inference-tested; TTS synthesis/cloning is absent |
| 8 Assets/approval | Complete local core: content-addressed files, immutable versions/facts, rights, parent provenance, version-bound review/comments/decisions and stale-approval invalidation. Reviewers are operator-entered names |
| 9 SEO/landing | Complete initial local core: supplied/captured HTML audits, duplicate comparison, SEO briefs, 13 text/block categories, brand tokens, RTL, isolated responsive previews and offline page/metadata/sitemap/robots export. No full-site crawler, live ranking/speed checks or Search Console connector |
| 10 Email/CRM | Complete export core: contacts, evidence/timestamped consent, immutable email identity, suppression/unsubscribe, atomic CSV import, deterministic segments, HTML/text email previews, test kits and freshly filtered recipient snapshots. No sender/unsubscribe service or Mautic/listmonk |
| 11 Publishing | Complete manual export core: schedule, frozen approval/rights checks, draft/final posting packages and manual post references. No external posting/scheduler |
| 12 Analytics/experiments | Complete manual/CSV core: exact saved metrics, KPI trends, guarded two-proportion tests with multiple-comparison adjustment. No platform/Matomo fetch or attribution inference |
| 13 Reports/knowledge | Complete local core: saved-data HTML/CSV/JSON reports and evidence-linked learnings/history. Browser print supplies PDF; no automatic PDF renderer or AI narrative |
| 14 Operations | Complete planning core: tasks and cycle-safe dependencies, scope, costs, internal pricing/margin arithmetic, paid-media budget/UTM scenarios and creator briefs/draft exports. Nothing authorizes ad spend or outreach |
| 15 Optional automation | Partial: idempotent brief-approved production-task rule. No autonomous agents/Activepieces connector |
| 16 Hardening | Partial: loopback/origin protection, bounds, audit, backup validation, retention/consent/export/reviewed erasure and browser checks. Multi-user auth/RBAC and remote deployment remain unavailable |

`Complete local/export core` describes the tested initial workflow, not every mature-agency extension listed in todo.txt. The remaining work is stated explicitly in each row.

## C`D. Files added and changed

Foundation: `agency/schema_types.py`, `schemas.py`, `database.py`, `services.py`, `security.py`, `compliance.py`, `jobs.py`, `research.py`, `exports.py`, `local_text.py` and `api.py`.

Production: `agency/production_schemas.py`, `production.py`, `content.py`, `assets.py`, `analytics.py`, `api_production.py` and editable `channel_specs.json`.

Acquisition/audio/privacy/planning: `agency/acquisition_schemas.py`, `acquisition.py`, `api_acquisition.py`, `audio_schemas.py`, `audio.py`, `asr_worker.py`, `api_audio.py`, `privacy.py`, `api_privacy.py`, `planning_schemas.py`, `planning.py` and `api_planning.py`.

UI: `static/js/agency-api.js`, `app-context.js`, `agency-workspaces.js`, `agency-production.js`, `agency-acquisition.js`, `static/css/agency.css`, navigation and index mounts. The existing Video Studio job panel is visible across its tabs. Actual pinned local Lucide runtime/license/version metadata live in `static/vendor/`.

Checks/setup: `scripts/verify_agency.py`; foundation, production, acquisition, audio, privacy and planning backend checks; three real agency browser scenarios; local-text protocol/smoke/install helpers; backup CLI. The legacy media runner isolates video imports, and its browser waits on the specific export job.

Documentation: README, ARCHITECTURE, AGENCY_WORKFLOW, ACQUISITION_AND_AUDIO, LOCAL_AI, MODEL_LICENSES, SECURITY, PRIVACY, PUBLISHING, ANALYTICS, BACKUP_RESTORE and this report. `.env.example` documents opt-in settings; `requirements-agency.txt` reuses the current application stack. `todo.txt` remains the original requirements document.

## E`G. Persistence, migrations and context

SQLite remains schema version 1: additional typed JSON records require no destructive table migration. Unknown/newer/modified schemas are rejected. Existing legacy brand JSON and image/video stores remain in place. Client records and all references are checked transactionally; old versions are retained and optimistic writes reject races.

The shared context is client ` project ` campaign ` locale. Selection never automatically assigns legacy renders to a client. Asset registration copies an explicit managed file into the private library. Saved briefs hand off to Image Studio without starting a provider call. Asset registration/versioning and erasure serialize in the supported single-process server.

Backup/restore carries SQLite, research originals and every registered asset version. Restore validates structure/hashes/schema and targets a new empty directory. Client portability export is separate: 128 MB cap and no restore claim.

## H`J. Models and actual inference status

| Component | Actual status |
| --- | --- |
| Qwen3-4B Q4_K_M / Apache-2.0 | Adapter and explicit 2.5 GB installer exist; weights/runtime not installed; no new real inference |
| faster-whisper/CTranslate2 CPU int8 | Optional local-directory worker implemented; runtime and weights absent; no real ASR inference |
| TTS | No reviewed model/voice configured; synthesis/cloning unavailable; licensed imported audio works |
| CogVideoX/Wan | Existing adapters retained; no new installed/verified video inference; see VIDEO_STUDIO.md |
| Existing image models | Existing cache/adapters preserved; this pass validates media workflows without claiming new diffusion inference |
| FFmpeg/FFprobe | Both present; actual audio trim/normalize/WAV output and existing video/GIF/MP4 workflows tested |

Installed, reachable, available and verified are separate states. A protocol stub or a local animation is not proof of AI inference. No model is downloaded at startup, and no paid fallback is introduced.

## K`N. Workflows and exports

Research ` evidence/claims ` strategy ` campaign/brief ` Image/GIF and content/script/storyboard ` real Video Studio project ` registered asset version ` local approval ` posting package is connected through saved references. Analysis/experiments ` report ` evidence-linked learning is also persisted.

Additional working paths: captured Research snapshot ` SEO audit; brand ` frozen landing-page color ` RTL preview/offline ZIP; consent/contact ` segment ` email/recipient test kit; source asset ` private audio WAV ` subtitle editing/download; audience/creative/page ` budget/UTM scenario ` draft plan; creator ` rights/disclosure brief.

Exports include actual carousel/media kits, planning packages, storyboards/captions, posting packages, reports, static pages, email test kits, recipient snapshots, creator/ad/organic plans, client portability bundles and full backups. Downloads preserve the requested file formats.

## O`Q. Hardware, security and privacy

Observed workstation: Windows/Python 3.12, RTX 4060 Laptop 8 GB, approximately 16 GB system RAM; only 1.95 GB was available at the end of this pass (17.6 GB free disk). A 4B model was not loaded under that memory pressure. New audio/ASR processing uses CPU. Current text model context is bounded to 4096 tokens with explicit external CPU runtime lifecycle. Larger video models retain existing hardware gates; nothing assumes cloud-sized memory.

New agency routes enforce loopback peer and Host, same-origin requests and no cross-site fetches before body parsing. Research uses an exact allowlist, public-IP/DNS pinning, verified TLS, robots, rate/time/byte limits and no redirects. Private jobs and registered files are not exposed through legacy public video jobs.

HTML/email/report input is escaped. Landing previews are sandboxed; preview forms cannot submit. JSON-LD must parse and cannot close its script element. Active-content URLs are rejected. CSV imports are bounded/atomic; exports guard spreadsheet formula cells.

Consent grants require source/purpose/evidence and server timestamps; CSV cannot grant consent. Withdrawal, suppression, archive and purpose mismatch override segment membership. Each recipient export recomputes current eligibility.

Retention lists review candidates and never auto-deletes. Client erasure requires an exact typed phrase, current client version and fresh data-review token. Changed data, legal holds and active jobs block it. Another client's current/historical asset references preserve shared files. Tests erase only temporary fixtures. Prior backups, exported/downloaded copies and independent media stores remain outside erasure, explicitly disclosed in the UI. File cleanup failures are returned for manual removal. No legal/forensic-erasure certification is claimed.

Run one local uvicorn process. Authenticated remote/client review, RBAC, an encrypted secret vault and internet-facing deployment are not delivered. Existing media API authentication limits remain.

## R`S. Verification and actual results

- Agency backend: **55 passing tests** across seven isolated checks (18 foundation, 6 HTTP/SSE text protocol, 12 production, 8 acquisition, 3 real audio, 5 privacy, 3 planning).
- Three real-server browser scenarios: foundation; production; acquisition/audio/privacy/planning. Saved data, real downloads, Arabic/RTL, client isolation and mobile overflow are exercised. No page JavaScript errors in the new scenario.
- All **17 existing media scripts** passed the offline regression runner, including dual static/GIF kits, staged employee welcome motion, visual endpoints and existing Video Studio backend/browser.
- The dedicated existing agency integration suite also passed all **8 tests** in 49.337 seconds.
- Existing `tests/` suite: **27 run, 22 pass, five unchanged baseline failures**. Two expect previous brand colors, two expect 808`1024 instead of the established 1080`1350 kit contract, and one expects an unavailable image where the existing deterministic fallback succeeds. Assertions were not weakened to conceal these differences.
- The earlier `tests/browser_smoke.py` visual-unavailable expectation is a known baseline failure; it was not rerun as part of the new three-browser runner.
- A direct legacy run stalled in existing provider/model discovery; the bounded offline run completed with the same five baseline failures.

Evidence: `output/agency-verification/results.json` and per-script logs; `legacy-unit.log`; `output/agency_regressions/results.json`; `output/agency-browser/{result,production-result,acquisition-result}.json` and desktop/mobile screenshots. Original baseline logs remain in `output/agency-baseline` and `output/resume-baseline`.

## T`V. Limitations, optional connectors and external costs

No full-roadmap/production-ready claim is made. Remaining substantive items are model installation and actual inference/quality verification, broader AI content integration, TTS, advanced crawling/keyword/ASR tooling, genuine multi-user security/review, external connectors and optional autonomous automation. The local capability and export workflows above work without these.

There are no new authenticated platform, SMTP, Search Console, Matomo, Mautic, listmonk, Activepieces or CRM connectors. API-shaped placeholders are not advertised as integrations. Accounts, OAuth scopes, delivery infrastructure and advertising spend remain external and require explicit authorization. Budget scenarios and generated publication packages grant no such permission.

## W`Z. Commands, remaining phases and regression confirmation

~~~powershell
python -m pip install -r requirements-agency.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
python scripts/verify_agency.py --browser
python scripts/verify_agency.py --browser --media
~~~

No Node build is required. Install media dependencies/tools using VIDEO_STUDIO.md. Optional text setup and a real smoke run are documented in LOCAL_AI.md; optional ASR setup is in ACQUISITION_AND_AUDIO.md. No inference success is implied by installation.

The phase table is the completion boundary: phases 0`4 have the tested foundation, phases 6/8`14 have the stated local/manual/export scope, and phases 5/7/15/16 retain the explicit unfinished items. Existing Image/GIF and Video Studio regressions were checked. Screenshots and JSON evidence are saved locally as listed above.
