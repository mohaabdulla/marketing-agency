# Publishing boundary

LEXNIS does not post to any external platform. There is no publishing connector, OAuth flow,
scheduler, email delivery or advertising-spend action. Calendar entries are local planning
records; a person posts the exported package from an account they control.

## Calendar entries and publication packages

**Calendar & Publishing** holds one entry per planned post: channel, account label, date,
time and IANA timezone, linked copy variant, linked media assets, alt text and disclosure.
**View schedule** groups saved entries by week.

**Export final publication package** writes a ZIP only when all of these hold:

- the linked copy variant and every linked asset have an approval of their **current
  version** (an edit after approval withdraws clearance);
- every asset has a usage-rights record that is not `unknown` and not expired;
- the copy has no blocking check flag (placeholder text, hard platform limit, prohibited or
  expired claim wording).

Otherwise the request is refused with the open issues listed. **Export draft package** always
works and marks itself as a draft with the same issues in `posting-checklist.txt`.

Package contents: `media/NN-name.ext` (the exact approved bytes), `thumbnail.jpg`,
`caption.txt`, `title.txt`, `alt-text.txt`, `hashtags.txt`, `disclosure.txt`,
`posting-checklist.txt` and `metadata.json` (record IDs and versions, SHA-256 of each file,
approval and rights state, copy check flags). `metadata.json` always records
`publishes_externally: false` and `publication_authorized: false`: the package is material
for a human to post, not an authorisation. A final export sets the entry to
`package-exported`; after posting, record the post link in the entry and mark it
`published-manually`.

Checks are deterministic review flags, not legal clearance. Platform limits come from the
editable `agency/channel_specs.json`; they have not been re-verified against each platform on
a specific date, so confirm a limit before relying on it.

## Not implemented

Platform adapters (TikTok, YouTube, LinkedIn, Meta), scheduled posting, platform post-ID
retrieval, email sending and paid-media execution. Any future connector needs the operator's
own platform account, OAuth scopes, explicit per-post confirmation and, for ads, real
external spend. The campaign review-plan ZIP (campaign-plan.json, deliverables.csv) from the
Campaigns workspace is unchanged and still grants no publishing permission.
