# Agency workflow delivered

Start at **Clients & Brands**, or keep using Image & GIF Studio (the first-visit default).
The planning domain needs no paid API, subscription, AI model or external account.

1. Create a client. Select it explicitly in Agency Context, then choose Project → Campaign
   → Language. Changing clients clears project/campaign selections.
2. Add a project and brand kit. Copy a legacy brand into a chosen client explicitly;
   old JSON remains intact. Editing creates another immutable revision.
3. Record stakeholders, onboarding and access requirements. Store credential references
   such as `env:CLIENT_ANALYTICS`, never password/token values.
4. Add English/Arabic terminology, approved spellings and prohibited forms.
5. Collect manual research or UTF-8 TXT/CSV originals, findings and competitor observations.
   Distinguish verified sources, client-supplied facts, approved assumptions and hypotheses.
   A finding marked fact requires a reviewed source.
6. Link exact claims to evidence. Verified/client-approved claims require evidence and a
   named recorded reviewer. Changed wording requires a draft revision before reapproval.
   Local recorded review is not authenticated external sign-off or independent fact-checking.
7. Define objectives, audiences, JTBD/personas, journeys, positioning, messages, offers and
   strategy. Saved revisions retain referenced record versions.
8. Create a campaign with brand/strategy/project, KPIs, budget, markets and languages.
   Status is manual planning metadata; setting it to live publishes nothing.
9. **Create brief from saved strategy** copies actual saved inputs without an LLM.
   Edit, select current approved claims and save another version.
10. **Run claim & terminology checks** flags configured prohibited wording, expired claims,
    unknown quantitative statements, missing disclosures/CTA and language mismatch.
    Numbers outside a verbatim selected claim are review flags; dates can be false positives.
    Passing checks is not legal sign-off, rights clearance or factual certification.
11. **Prepare Image Studio** transfers the SAVED brief, brand and locale. It clears stale
    image-brand context and records the prepared brief ID/version in browser context.
    It does not generate an image or call any provider.
12. Plan channels/deliverables and view real due dates. **Export review plan** writes a ZIP
    with campaign/brief records, checks and spreadsheet-safe deliverables CSV.

## Production, approval and measurement (added 2026-11-12)

13. **Content Studio → Creative concepts → Build a concept matrix**: enter your own options
    per axis (hook type, benefit, visual territory, CTA, channel…). Each combination becomes
    a proposed concept, 24 at most. Rationale and copy are never invented. Approve or reject
    concepts before producing assets.
14. **Copy variants**: pick a format from the channel registry, write the text and CTA, link
    approved claims. **Run copy checks** flags hard/recommended length limits, placeholders,
    unsubstantiated numbers, prohibited or expired claim wording, glossary violations,
    missing CTA, malformed links, hashtag counts, language mismatch and near-duplicate
    variants. Flags are review items, not scores.
15. **Scripts**: add scenes (narration, dialogue, on-screen text, visual). The spoken-length
    estimate uses the configured words-per-minute for the language and is labelled as an
    estimate. **Create storyboard from this script** makes one shot per scene.
16. **Storyboards / Storyboard shots**: add framing, motion, prompts and a registered
    reference image or clip per shot. **Shot list & timing** shows the sequence;
    **Create Video Studio project** builds a real project (shots in order, stills or clips,
    on-screen text as titles; shots without a picture get a plain animatic slate);
    **Export storyboard** downloads HTML plus images.
17. **Assets & Approvals → Assets**: register a generated or uploaded file (use
    **Register in Assets** under an Image Studio result, or paste its media URL or a Video
    Studio asset ID). The file is copied to a content-addressed store with its SHA-256,
    size and dimensions. **Add new file version** keeps earlier files and their history.
18. **Usage rights**: record licence type, owner, restrictions, markets, channels and expiry,
    then select it on the asset. Assets without rights block a final publication package.
19. **Approvals**: on a brief, concept, copy variant, script, storyboard, shot, asset,
    strategy or report choose **Request approval**. The request freezes the record version
    (and file checksum). Reviewers comment (with an optional timecode), approve, request
    changes or reject. Any later edit supersedes the approval. Approving a brief opens one
    production task per planned deliverable (a deterministic workflow rule, applied once).
    Reviewer names are typed, not authenticated: this is a recorded local review.
20. **Calendar & Publishing**: see PUBLISHING.md. Final packages need approved current
    versions and recorded rights; nothing is posted externally.
21. **Analytics & Experiments** and **Reports & Learnings**: see ANALYTICS.md.
22. **Operations**: tasks with dependencies, scope items, cost entries and pricing scenarios.
    A pricing scenario shows fee components, discount, pass-through markup, internal cost,
    gross margin and the revenue needed for your target margin, all from your own inputs.
    Media spend is shown as external money, never as agency revenue.

Workspaces have real APIs, persistence, validation, client-keyed browser drafts, errors,
search/pagination and version history. Reference selectors search within the selected client.
Dashboard counts actual stored records, not invented revenue or engagement.

## Optional online research

Manual research works offline. To enable one-page capture:

```dotenv
AGENCY_WEB_RESEARCH=1
AGENCY_RESEARCH_ALLOWED_DOMAINS=example.com,docs.your-client.example
```

Create a URL source, review site terms and research policy, then choose **Capture URL**.
Exact allowlisted domains/public IPs on ports 80/443 only; connections pin validated DNS.
Redirects/compressed responses are rejected. Verified TLS, robots, domain rate limits,
10-second socket timeouts, 2 MB pages and one-page-per-job limits apply. A snapshot never
automatically promotes source credibility. HTML is extracted as text, never executed.

Trusted roots default to requests' CA bundle; configure `AGENCY_RESEARCH_CA_BUNDLE` for a
trusted corporate bundle. Verification cannot be disabled. A real https://example.com
capture succeeded with verified TLS and a retained original.

TXT/CSV: 10 MB/file, UTF-8 only, 10,000 rows, 100 columns, 10,000 characters/cell;
displayed extraction is limited to 120,000 characters. Original bytes/hashes are retained.
PDF/Office ingestion, multi-page crawling and automatic fact verification are not implemented.

## Acquisition, audio, planning and privacy

See [Acquisition and audio](ACQUISITION_AND_AUDIO.md) for SEO snapshot handoff, the landing-page builder, CRM/consent/email exports, organic/paid/creator planning, FFmpeg processing and subtitle editing. See [Privacy](PRIVACY.md) for retention, client export and the reviewed erasure workflow. These use the same persisted client context and version history.

## Boundaries

Not implemented: authenticated multi-user/client review links, live external posting or SMTP delivery, analytics connectors, TTS synthesis, and autonomous agents. Text/ASR adapters need separately installed models and actual inference verification. No new inference success is claimed. Existing media studios remain available; a generated file belongs to an agency client only after explicit asset registration. Draft exports never authorize spending, publishing or sending.
