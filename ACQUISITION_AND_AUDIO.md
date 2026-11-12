# Local acquisition and audio workflows

These workspaces share the selected client/project/campaign, SQLite revisions, audit and
same-origin loopback protection. They never publish a page, send mail, contact a creator or
authorize advertising spend. Restart the server after updating the code.

## SEO and landing pages

In **SEO & Landing Pages → HTML audits**, save a URL and supplied HTML, then inspect it.
Alternatively, capture an allowlisted website in Research, then choose **Audit a captured
Research source**. This reuses the retained, checksummed snapshot and freezes its source
reference. It performs no second request. Research retains its robots, DNS/IP, TLS, time
and response limits; this is a bounded one-page workflow, not an unrestricted crawler.

Inspection covers title/description, canonical, robots meta, headings, missing alt attributes,
internal/external links, hreflang, declared sitemap links, JSON-LD syntax, viewport, source
bytes/hash and an explicitly operator-entered HTTP status. Compare up to 100 saved audits
for duplicate titles/descriptions. HTML is limited to 300,000 characters and 15,000 elements.
The report does not measure live indexability, robots.txt, browser performance or rankings.
No invented SEO/GEO score, keyword volumes or ranking claims are produced.

SEO briefs retain intent hypotheses, questions, manually entered keywords, sections,
evidence, audience and CTA. Search Console and proprietary keyword connectors are absent.

Landing pages support the requested 13 block categories, colors, a selected brand token,
metadata, canonical/Open Graph, syntactically checked JSON-LD, and Arabic RTL.
A selected brand's primary color is copied into the page revision at save time; changing
the brand later does not silently change that revision's exported HTML.

**Preview page** offers desktop/tablet/mobile widths in a sandboxed iframe. Preview forms
cannot submit. **Export static page** returns offline HTML, CSS, event hooks, metadata and,
when a canonical URL exists, a sitemap and robots draft. Review deployment paths before use.
There are no CDN dependencies. Form blocks use local test mode until an HTTP(S) endpoint
and privacy copy are configured. A real endpoint must validate consent, reject the honeypot,
rate-limit requests and provide delivery infrastructure. Events use the local
`lexnis:analytics` DOM event; no external tracker is enabled.

## Contacts, consent and email

**Email & CRM** supports contacts, deterministic segments and email templates.
An email is normalized and unique per client, including archived contacts. It remains
immutable to retain address-specific consent and suppression history. Granted consent
requires a source, purpose and evidence note; the server records its timestamp, and all
changes remain in revision history. This is operator-recorded evidence, not legal verification.

CSV import is explicit, atomic, UTF-8, at most 1 MB/1,000 rows. Columns:
`name,email` and optionally `language,source,tags`. Separate tags with `|`.
Unknown columns, including consent-grant columns, are rejected; imported consent is always
unknown. Existing email collisions reject the entire import.

A segment checks consent purpose, locale, required tags and excluded tags. Archived,
suppressed and unsubscribed contacts are always excluded, even when tags match.
**Preview eligible contacts** gives the real saved membership and exclusion counts.

Email templates render escaped table-based HTML and plain text. Preview/checks flag missing
physical address and unsubscribe URL; tone heuristics are labelled, not deliverability scores.
Export a test kit alone or explicitly select a segment to include a recipient snapshot.
Every export recomputes eligibility, so withdrawal applies to the next export. The ZIP contains
template/segment versions, contact versions, timestamp, CSV and JSON; an audit records its hash.
Old exported lists cannot be revoked: recheck consent before any external send.
There is no SMTP sender, unsubscribe web service, tracking pixel or automatic mail delivery.

## Organic, paid-media and creator plans

Content Studio includes pillars and series with audience/evidence and source-copy/script/brief
links. Paid Media Planning retains audience/placement/creative/page links, operator-entered
budget and CPC/conversion assumptions, KPI and UTM fields. Calculations show real arithmetic
from those inputs and distinguish scenarios from measured results. UTM building preserves
unrelated query parameters and the URL fragment. Missing assumptions yield no forecast.
Ad spend is external, and no account or budget is changed.

Creators & UGC stores manually supplied public contact details and creator briefs with
deliverables, talking points, disclosure, compensation, geography and usage-rights fields.
Organic/creator/paid plans export draft JSON/CSV with a review checklist. No outreach is sent.

## Audio and subtitles

Register audio/video through Assets & Approvals first. In **Audio & Subtitles**, create an
audio project, choose that asset and set trim boundaries, normalization and optional gain.
**Render processed audio** runs actual FFmpeg in the private client job queue and stores a
checksummed 48 kHz stereo PCM WAV in the private asset library. It retains source asset
ID/version and project ID/version. No private render is copied to the public renders folder.
Download the result or open it under Assets. Registering it does not grant usage rights.

Input: audio stream required, up to one hour. Output: at most 256 MB; oversized PCM ranges are
rejected before rendering. CPU processing has a five-minute deadline and cancellation.
Normalization is a single-pass -16 LUFS target, not a measured delivery certification.

Subtitle documents contain ordered, non-overlapping, millisecond-valid cues, locale, origin
and review state. Edit text/timings in the nested rows, then download actual SRT or WebVTT.
These are entered timings. Existing storyboard captions remain explicitly planned timings.

### Optional local transcription

The [faster-whisper project](https://github.com/SYSTRAN/faster-whisper) documents CPU int8
and local model directories. Its [constructor](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)
supports `local_files_only`. The engine is MIT; review the license of the exact chosen weights
separately. No weights, inference success or TTS voice are bundled by this change.

Explicit optional runtime setup:

~~~powershell
python -m pip install "faster-whisper>=1,<2"
~~~

Separately install/review a compatible CTranslate2 Whisper model and set:

~~~dotenv
AGENCY_ASR_MODEL_DIR=C:/models/your-reviewed-whisper-model
~~~

The directory must contain `model.bin`, `config.json` and `tokenizer.json`. Restart the app.
When runtime and files exist, an audio/video asset offers **Transcribe locally**. A cancellable
CPU subprocess uses int8/four threads, local files only, up to 30 minutes of audio and a
ten-minute processing deadline. Successful output becomes an unreviewed subtitle document.
The capability endpoint does not claim verified ASR: actual inference was not run here.
TTS synthesis/cloning is unavailable; import a licensed voiceover instead.
