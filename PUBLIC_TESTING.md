# Public testing and brand-guided video editing

Implemented in the existing application on 2026-11-14. There is no separate studio or
shared public account. The audit found no login, registration, subscription, credit or
account-role implementation in this checkout; none was removed or invented.

## Enable

Use the current application environment and existing image/video dependencies:

~~~powershell
python -m pip install -r requirements-brand-video.txt
$env:PUBLIC_TEST_MODE = "true"
python -m uvicorn server:app --host 0.0.0.0 --port 8000
~~~

Open http://localhost:8000. Other testers on a reachable network can use the host's address
on port 8000. For persistent configuration, set `PUBLIC_TEST_MODE=true` in `.env` and restart.
The code and `.env.example` default to false. This change does not configure internet
hosting, a firewall, a domain, or your `.env` secrets.

Run one server process. For internet testing, serve the app and API from one HTTPS origin,
with the proxy preserving Host and passing the correct trusted scheme/client address. HTTPS cookies are Secure.
Cross-origin public-mode API clients are intentionally not enabled.

To disable, set `PUBLIC_TEST_MODE=false` and restart. Normal mode is now explicitly
loopback/localhost-only, including legacy media APIs, so switching off guests cannot expose
the operator's desktop store to remote anonymous visitors. Existing local workflows remain.
This is not a replacement for a future authenticated production account system.

## Identity, isolation and cleanup

- Opening `/` or same-origin `GET /api/session` creates an opaque 256-bit cookie. It is
  HttpOnly, SameSite=Lax, host-only and Secure over HTTPS. Headers, URLs, request IDs and
  localStorage never prove ownership.
- Each guest has private renders/uploads, brands, video assets/projects/revisions/jobs/
  analysis, layered projects/renders, guidelines, document vault and agency SQLite under
  `output/public-test`. Pre-existing operator data and test portraits are not assigned to guests.
- Queued workers retain that guest context. Reopening uses the same cookie. Browser drafts
  and preferences use separate keys per guest workspace; existing operator drafts are preserved.
- A different cookie cannot read, alter, import, export or cancel known project/file/job IDs.
  Operator/system and credential-connector routes remain blocked; filesystem paths are
  removed or converted to scoped media URLs in legacy JSON.
- Sessions last seven days. Expiry does not immediately delete originals. Stop the server
  before operator cleanup; the default command only previews expired workspaces:

~~~powershell
python scripts/cleanup_public_workspaces.py
python scripts/cleanup_public_workspaces.py --apply
~~~

Cleanup checks resolved paths within the configured guest root and skips recorded active
video jobs. Actual cleanup tests use temporary fixtures only.

Optional configuration: `PUBLIC_TEST_DATA_DIR`, `PUBLIC_TEST_MAX_SESSIONS` (1000),
`PUBLIC_TEST_DISK_QUOTA_GB` (8). Each guest also has a 2 GiB storage ceiling.
Upload/clip/frame limits, bounded queues, timeouts, hardware and license checks remain
operational safeguards, not paid plans. Public page extraction pins validated public DNS/IPs,
verifies TLS, rejects redirects and bounds responses. Cross-site mutations are rejected
before multipart parsing. Signatures, SVG external references and document containers are checked.

## Editor workflow

1. Open **Video Studio → Video Editor**, import footage and save/open projects normally.
2. Under **Brand Guidelines**, upload PDF, DOCX, TXT, Markdown or JSON; select a saved
   guideline; or import an existing brand kit.
3. Review source evidence, missing fields and conflicts. Correct colors, fonts, CTA,
   disclosures, language, layout and logo selection. Confirm to bind that document version.
4. **Analyze Video** measures local scene/audio characteristics. Actual AI requests also
   wait for analysis of up to six source videos.
5. Enter **Tell AI How to Edit Your Video**. **Edit with AI** calls the configured local
   model. **Auto Polish / Apply Guidelines** is explicitly deterministic.
6. Review operations and failed checks; render the proposed preview, then apply or reject.
   Rejection revokes the server plan. Changed projects invalidate stale plans. Applying an
   old proposal cannot overwrite unsaved manual edits.
7. Use **Check Against Guidelines**, **Fix Issues (preview)**, **Undo**, **Redo**, and
   **Revision history**. Export actual MP4/WebM through the existing controls.

Captions are never invented. **Import SRT captions** creates actual English/Arabic rendered
title clips from reviewed timing/text, retaining the original SRT. Imports must fit the
timeline and the 60-clip budget. Recheck timings after trimming/reordering.

The same document appears in Image & GIF Studio's **Shared guideline library**.
**Use in Image & GIF** reuses it without uploading again. The original Image upload route
also stores supported documents in this library and preserves its legacy response fields.

## Applied rules and honest limitations

The validated operation set supports add/remove/split/reorder/trim clips, duration/speed,
canvas/aspect/safe zones, available named fonts, title/caption colors, logo overlays and
placement, fades/transitions, exact reviewed CTA/disclosures, color adjustments and volume.
Arbitrary commands, filters, filesystem paths, unsupported parameters and unowned assets
are rejected. Project and source lengths are revalidated before saving/rendering.

Deterministic Auto Polish implements a bounded subset: styling/placement, simple shortening
and aspect changes, subtle fades, music volume, and exact approved CTA/disclosures.
Other free-form editorial instructions need manual editing or the local model.

The fixed local font registry supports Arial, Inter, Montserrat, Cairo, DejaVu Sans and
Times New Roman when installed. Missing preferences report the actual fallback.
The renderer preserves logo source aspect ratio. Select/import an approved logo; arbitrary
PDF artwork is not guessed to be an official logo.

Documents: 8 MB each, eight files/16 MB total and 120,000 extracted characters per original.
PDF parsing uses a separate process with a 25-second deadline, RSS monitoring and at most
40 unencrypted pages. Scanned PDFs need a text export/OCR outside this parser.
DOCX ZIP/XML budgets and entities are checked; originals are never executed or unpacked
to caller-selected paths.

Extraction uses explicit labelled fields/structured JSON with source evidence. Unlabelled
prose is retained for review, not fabricated into mandatory rules. Conflicts/missing/unmapped
fields and operator corrections are distinct. AI receives reviewed rules and a bounded,
explicitly untrusted source excerpt.

Compliance inspects saved timeline colors, font availability/usage, selected logo, wording,
safe-zone centers, title size, duration/aspect, language presence and managed assets.
It marks rendered pixels, semantic footage, exact glyph extents, full-video contrast,
music rights and spoken-language accuracy as NOT_CHECKED. Legal/metric wording cannot be
automatically rewritten. A report is not legal or perfect visual certification.

## AI setup and tests

Configure `LOCAL_TEXT_URL` / `LOCAL_TEXT_MODEL` using `LOCAL_AI.md`. The endpoint must be
a literal loopback HTTP address; proxies/redirects are disabled. Planning uses tokenizer/
context limits, strict EditPlan JSON, one inference slot and bounded responses.
There is no paid fallback or startup model download.

The configured local model is currently unavailable. CPU edits, captions, analysis, previews,
history and exports work. An explicit HTTP stub tests planner protocol/validation; it is not
a claim of successful model inference or editorial quality.

~~~powershell
python scripts/test_public_brand_video.py
python scripts/test_public_brand_video_browser.py
python scripts/test_video_studio.py
python scripts/verify_agency.py --browser
python scripts/run_agency_regressions.py
~~~

Evidence: `output/public-brand-video/backend.log`, `result.json` and screenshots;
`output/agency-verification/results.json`; `output/agency_regressions/results.json`.
Changed-file groups/results are in `PUBLIC_BRAND_VIDEO_REPORT.md`.
