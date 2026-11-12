# Agency security boundary

Single local operator only. New /api/agency endpoints enforce loopback peer, localhost/
loopback Host, same-origin requests and no cross-site fetches BEFORE body parsing.
Forwarded-IP headers are ignored. Responses use no-store/nosniff. Private research/text
jobs are client-scoped and never exposed through public video-job endpoints.

Opaque IDs, scoped document/history/reference lookups, same-client foreign keys and
optimistic version checks protect integrity. Audit/revisions have no mutation API.
An OS-level operator can edit SQLite: these are not cryptographic notarization.

No multi-user login/session/RBAC exists. Stakeholder/reviewer names are recorded context,
not authenticated identities or permission grants. Do not expose this as a LAN/public
multi-user system. Existing media endpoints retain their earlier authentication limits.

- JSON: 2 MB. Research multipart: 11 MB request / 10 MB file.
- UTF-8 TXT/CSV only: MIME/signature/control/structure limits, random names, safe attachment downloads.
- Documents: 1 GiB quota. Backups: 512 MB bundle cap / 20 retained bundles.
- Private jobs: two workers/eight active-or-queued, cancellation and restart recovery.
- Web: exact allowlist, public IP validation/pinning, no redirects/compression, verified
  TLS, robots and bounded page/time/rate.
- LLM: fixed loopback endpoint, no proxy/tools, schema/token/output/time limits.
- Restore: path/type/count/expansion/hash checks, expected SQLite schema/application ID/
  foreign keys and integrity, new empty destination only.
- CSV exports neutralize leading formulas; untrusted source HTML is escaped, not executed.

Checks are review aids, not legal certification. Prompt injection can affect draft quality
but cannot grant tools or publishing permission because the model has no action interface.

Secrets stay in environment configuration or an operator-managed vault. Access entries
accept env:NAME / keychain:NAME references; no new secret-resolution/encryption scheme is
invented. Never paste credentials into ordinary notes. .env is ignored/excluded from
backups. Public errors use safe IDs; protect local private validation/diagnostic logs.

Authentication/RBAC, per-user approvals, retention/erasure and encrypted secret management
remain later hardening work.

## Production workspaces (added 2026-11-12)

- Assets are registered only from application-managed media (`/renders/`, `/uploads/`,
  `/static/assets/` file names, or a Video Studio asset ID). Paths with directories, `..`,
  schemes, hosts or query strings are rejected. Files pass an extension allowlist, a
  signature check, a 256 MB limit and are stored under their SHA-256; responses never
  contain filesystem paths. Asset files are served with a restrictive
  `Content-Security-Policy: default-src 'none'; sandbox` header.
- Approval records cannot be created or edited through the generic record API. A decision is
  refused if the target changed after the request. Reviewer names are typed by the local
  operator and are not authenticated identities.
- CSV exports prefix formula-leading cells; CSV imports are size- and row-limited and atomic.
- Report narrative and all record text are HTML-escaped in rendered reports and storyboards.
- Production export routes never publish, send email or spend money. Optional local-text
  and local-ASR jobs invoke only their explicitly configured local runtimes.

## Acquisition, audio and erasure

Landing previews use a sandboxed iframe and CSP without same-origin privileges; forms
cannot submit in preview. HTML/email/JSON-LD output is escaped, and active-content URLs
are rejected. Static form endpoints need their own server-side consent/spam controls.
Contact CSV import cannot grant consent. Suppression/unsubscribe override tag filters.

Audio rendering uses the private agency queue, UUID/scoped asset references, checksums,
trim/duration/PCM-size limits and bounded shell-free FFmpeg. The optional ASR worker accepts
server-selected private files and explicitly installed local weights; it has no tools or
provider fallback. TTS/voice cloning is unavailable.

Erasure requires the exact typed client phrase, expected client version and a fresh review
token; changed data, legal holds and active jobs block it. Shared current/historical asset
files are preserved. Prior backups/downloads and independent media stores are outside this
workflow. Any file cleanup failure is reported rather than claiming complete removal.
Run a single uvicorn process: file creation/export/erasure share a process-local store lock.
