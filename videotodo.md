
# Professional Video Editing Upgrade for LEXNIS: Evidence, Standards, Architecture, and Fable 5.2 Implementation Prompt

## Evidence from the supplied videos and current repository

I was able to inspect both supplied MP4 files and unpack the current repository at `/mnt/data/marketing-agency-main (3)(1).zip`. This means the recommendations below are grounded in the actual comparison files and current implementation rather than assumptions.

The first supplied file, `/mnt/data/e96aba6752a648f6b1211ca0633f2795.mp4`, is 13.04 seconds long, 464×832 portrait video, H.264 High Profile, approximately 59.97 fps, AAC stereo at 48 kHz, about 2.04 Mbps video bitrate, and roughly 127 kbps audio. Its measured integrated loudness is approximately **−17.1 LUFS**, with a measured true peak of about **−2.5 dBTP**. Frame sampling shows visible LEXNIS branding near the top and burned-in subtitles at several points.

The second supplied file, `/mnt/data/WhatsApp Video 2026-11-15 at 13.25.02.mp4`, is 15.71 seconds long, also 464×832, H.264 Baseline Profile, approximately 59.97 fps average, AAC stereo at 44.1 kHz, about 1.61 Mbps video bitrate, and approximately 63 kbps audio. Its measured integrated loudness is approximately **−17.3 LUFS**, but its measured true peak reaches approximately **+0.5 dBTP**. That is a significant technical warning because true-peak overs can produce clipping or distortion after codec conversion. ITU-R BS.1770 specifically defines true-peak measurement because reconstructed audio peaks can exceed the highest stored PCM sample, and EBU production guidance recommends maintaining true-peak headroom rather than allowing peaks around or above 0 dBTP. citeturn996028search0turn996028search7turn996028search8

The second filename indicates that it passed through WhatsApp or was at least saved from WhatsApp, so its H.264 Baseline profile, reduced bitrate, 44.1 kHz audio, and some compression differences cannot safely be attributed entirely to the LEXNIS renderer. A definitive encoder-quality comparison should therefore use the original MP4 downloaded directly from LEXNIS before it is sent through another messaging platform. Even so, the supplied file remains useful for judging the visible result and overall editorial behavior.

Frame sampling confirms that the two clips contain substantially corresponding footage of the same speaker and environment. A central-region visual similarity check aligns much of the first file with the second, although the temporal offset increases through the clip. For example, footage around 7 seconds in the first clip aligns approximately with 7.5 seconds in the second, and footage near 13 seconds aligns around 14 seconds. The edited file is about **2.67 seconds longer** than the first file. This matters because a professional automatic editor should be able to explain where duration was added or removed and why; duration changes should be represented explicitly in a non-destructive edit decision list rather than emerging opaquely from processing.

The visual comparison also reveals an important issue: the sampled first file contains visible branding and captions, whereas corresponding sampled frames from the second file do not. I am therefore not treating the first file as literally “completely raw” in the technical sense; I am treating it as the user-designated before/reference file. The important product finding is that the resulting automated edit is not visibly demonstrating a stronger branded post-production treatment than the reference. The current editing experience therefore needs to move from a collection of deterministic transformations toward an editorial system that understands what should be preserved, improved, removed, added, and verified.

The repository explains why this is happening. `video_quick_edit.py` currently performs mostly deterministic speech cleanup and regularly alternating digital zooms. It removes detected long pauses and certain filler words, creates caption cues only when local transcription is available, alternates zoom pairs such as approximately `1.00 → 1.035` and `1.07 → 1.09`, rebuilds the project timeline, then calls the brand-polish pipeline. This is useful infrastructure, but it is not yet a professional editorial intelligence layer.

`video_ai_editor.py` likewise contains useful foundations, including an edit-plan schema and non-destructive operations, but its deterministic `auto_polish()` applies generalized rules such as adding a 0.5-second crossfade between primary clips, placing a logo at a predefined position, adding a hook title, and adding a three-second CTA. Those choices are not inherently wrong, but professional editing requires contextual decisions. A talking-head cut often needs a clean cut, J-cut, L-cut, punch-in, reaction change, graphic insert, or no transition at all; repeatedly applying crossfades is not a substitute for editorial intent.

The current analysis layer is an especially important limitation. In `video_analysis.py`, shot boundaries can be detected using PySceneDetect or FFmpeg, and silence is genuinely detected. However, `motion_score` is currently set to a constant `0.5`, `speech_present` is initialized as `False`, and `audio_metrics.peak_db` is initialized to `−1.5` rather than being measured from the source. Those placeholder-like analysis values mean the AI editor cannot yet make reliable decisions based on actual motion intensity, speaking activity, audio peaks, framing quality, or visual importance.

The renderer in `video_editor.py` already has several strong foundations: source media stays immutable, edits are expressed through project/timeline objects, FFmpeg is invoked without shell interpolation, it can composite titles and overlays, it supports crossfades, zoom/pan, music ducking, AAC audio, and H.264 rendering, and it optionally applies FFmpeg `loudnorm` at `I=-16:TP=-1.5:LRA=7`. That local-first renderer should be retained rather than replaced.

The brand-guideline functionality also exists in the repository more than the current UI suggests. `static/js/video-brand-editor.js` contains **Upload / Replace Guidelines**, existing-guideline selection, guideline viewing, brand-kit selection, removal, AI editing, analysis, compliance, repair, undo, redo, and revision history. The main UX problem is that Quick Edit moves much of the branding workflow into a collapsed **“Brand, purpose & name (optional)”** area. That directly conflicts with the desired Image/GIF-style experience. Brand guidelines should be a visible workflow step, not buried as an optional advanced detail.

## Professional standards the editor should implement

There is no single formal “global video editing standard” governing whether a cut should happen on a gesture or whether a title should animate for 250 ms. Professional post-production is a combination of formal engineering standards, platform delivery requirements, accessibility requirements, brand constraints, and editorial best practices. Fable should keep these categories separate in the implementation rather than describing subjective editing choices as standards.

For audio measurement, **ITU-R BS.1770-5** is a formal international recommendation defining algorithms for programme loudness and true-peak measurement. **EBU R128** is a formal broadcast-oriented loudness recommendation built around BS.1770 measurement and specifies a programme loudness target of **−23 LUFS** for its broadcast context. EBU guidance also specifies maximum true peak of approximately **−1 dBTP** in production, with additional headroom recommended for some lossy distribution chains. citeturn996028search0turn996028search1turn996028search8

LEXNIS should not force −23 LUFS on every social-media export. Instead, it should have explicit output presets. A **Broadcast / EBU** preset can target −23 LUFS according to R128, while a **Web/Social** preset may intentionally use a louder target such as the application's existing −16 LUFS policy, provided this is labeled as a product/platform mastering preset rather than “EBU compliant.” The important requirement is that all targets are measured using a BS.1770-compatible meter and that true peak remains safely below clipping. citeturn996028search0turn996028search1

For SDR color, **ITU-R BT.709** remains the formal HDTV production and programme-exchange reference. LEXNIS should therefore establish an explicit Rec.709 SDR pipeline for normal SDR projects, propagate or intentionally convert primaries, transfer characteristics, matrix coefficients, and range, and validate the final file rather than relying on unspecified FFmpeg defaults. citeturn996028search2turn996028search3

YouTube's current official upload guidance recommends MP4, H.264, progressive scan, 4:2:0 chroma, AAC-LC/compatible audio, 48 kHz audio, Fast Start, and preserving the frame rate at which content was recorded rather than unnecessarily resampling it. YouTube specifically recommends H.264 High Profile and provides resolution/frame-rate-dependent bitrate guidance. citeturn929078search0turn929078search2

That matters directly to the supplied comparison. The reference file is H.264 High Profile with 48 kHz audio, while the WhatsApp-labeled edited derivative is H.264 Baseline with 44.1 kHz audio. Because messaging recompression may have caused that downgrade, Fable should test the direct LEXNIS export. The final LEXNIS export presets should nevertheless explicitly request professional H.264 profile/level, 48 kHz AAC, source-consistent frame rate, `+faststart`, and correctly tagged Rec.709 for SDR. YouTube also recommends uploading videos at their native frame rate and avoiding unnecessary frame-rate resampling. citeturn929078search0turn929078search5

For short-form vertical media, TikTok's current official advertising documentation recognizes 9:16 vertical, 1:1 square, and 16:9 horizontal formats; its own creative guidance strongly favors full-screen 9:16 for vertical short-form experiences and at least 720p-quality footage. TikTok also requires usable audio and legible/high-resolution creative for ads. These are platform requirements or recommendations, not universal editing laws. citeturn929078search3turn929078search7turn929078search9

For captions and on-screen text, WCAG 2.2 requires captions for prerecorded synchronized web media under Success Criterion 1.2.2, and WCAG's normal-text contrast threshold is 4.5:1, with 3:1 permitted for sufficiently large text. WCAG is a web-accessibility standard, not a broadcast subtitle styling specification, so LEXNIS should treat its contrast principles as an accessibility-oriented QA baseline for generated overlays and captions rather than claim that a rendered MP4 is automatically “WCAG certified.” citeturn996028search4turn996028search5

Editorial pacing, cut timing, shot selection, reaction timing, hook construction, emphasis zooms, B-roll placement, kinetic typography, transition restraint, music synchronization, and narrative rhythm are **professional editorial best practices**, not formal ITU/EBU standards. The AI editor must therefore reason about them from the content and creative brief rather than applying fixed global rules.

## Highest-priority improvements

The work should be prioritized around evidence from the supplied output and the current codebase:

1. **Replace placeholder media analysis with measured analysis.** Motion score, speech presence, loudness, true peak, visual sharpness, face/framing information, shot type, silence, voice activity, scene changes, and candidate edit points need actual measurements. No AI editor can make professional decisions if analysis fields are constants.
2. **Make brand guidelines a mandatory-visible Video Editor workflow step.** The underlying controls already exist, but Quick Edit hides them inside an optional collapsed section. Video should mirror Image/GIF: source → guidelines → objective → AI prompt assistant → edit settings → proposed edit → preview → brand/technical QA → export.
3. **Stop treating “professional edit” as a fixed recipe.** Alternating zooms, automatic 0.5-second crossfades, generic title placement, and automatic CTA insertion should become context-sensitive actions selected only when justified by content, brand rules, platform, and user intent.
4. **Introduce an editorial scoring layer.** Each possible cut or retained segment should have explainable scores for speech importance, semantic importance, visual quality, motion, eye contact/face quality where locally measurable, pause confidence, filler confidence, continuity risk, hook value, and brand relevance. The engine should choose edits from these signals rather than trimming every qualifying gap mechanically.
5. **Make captions first-class.** If transcription is unavailable, the UI should clearly explain why captions cannot be generated and offer local model setup or reviewed SRT import. When transcription exists, captions should have timing, CPS/readability checks, line-count limits, word confidence, punctuation review, RTL support, safe-zone checks, contrast measurement, and selectable brand styles. WCAG contrast values can serve as a QA benchmark for text rendering. citeturn996028search4turn996028search5
6. **Add real audio mastering QA.** Analyze integrated LUFS, short-term loudness, loudness range, true peak, clipping, silence, channel configuration, sample rate, and dialogue/music relationship. Export presets must prevent true-peak overs. BS.1770 should be used for measurement, EBU R128 only for the relevant broadcast preset, and social/web targets should be named separately. citeturn996028search0turn996028search1turn996028search8
7. **Upgrade color and export management.** Establish Rec.709 SDR as the explicit normal SDR working/output space; preserve native frame rate unless deliberate conversion is required; add proper H.264 High Profile export presets; keep AAC at 48 kHz for professional web export; and validate output metadata after rendering. citeturn996028search2turn929078search0
8. **Add before/after quality gates.** LEXNIS should never assume an edit is better because it rendered successfully. Compare source and result for duration, frame cadence, clipping, loudness, resolution, bitrate/codec profile, black/frozen frames, captions, branding, safe zones, crop integrity, visible faces, text contrast, and guideline requirements before exposing the export as “finished.”

## Target editing architecture and user experience

The core architecture should remain local-first and non-destructive. The project object and edit operation schema already provide the beginning of an EDL-style system, so the correct evolution is to strengthen that model rather than allowing an AI model to construct arbitrary FFmpeg command strings.

Every AI edit should create a versioned `EditPlan` containing the editorial intent, evidence used, assumptions, proposed operations, confidence, warnings, technical consequences, and brand consequences. Each operation should map to a validated internal command such as trim, split, reorder, crop, transform, caption, title, logo, audio level, fade, transition, speed, color correction, or canvas operation. The AI should never execute shell commands itself.

The analysis pipeline should create a persistent per-asset analysis document. That document should include real shot boundaries, scene-change confidence, frame statistics, motion estimates, face/subject framing where available locally, speech intervals, transcript words and confidence, silence segments, loudness/true-peak measurements, clipping, sample rate, source color metadata, frame rate, resolution, orientation, potential duplicate/frozen frames, and representative thumbnails. It should be cached by source hash so repeated edits do not repeatedly analyze unchanged media.

For a talking-head video like the supplied comparison, the editor should understand that a cut is usually justified by semantic compression, a long pause, filler removal, mistake removal, framing change, emphasis, or narrative transition. It should not create a punch-in simply because four seconds elapsed. Digital zooms should be tied to meaningful beats and limited by a configurable maximum crop so output does not feel mechanically animated.

Brand-guideline ingestion should reuse the Image/GIF system. The user should be able to upload PDF, DOCX, TXT, Markdown, or JSON guidelines once and reuse them across image, GIF, and video projects. Extracted rules should remain reviewable and should distinguish explicit rules from inferred preferences. Video-specific structured fields should include logo rules, logo clear space, title fonts, caption fonts, primary/secondary colors, minimum text contrast policy, lower-third style, allowed transitions, prohibited effects, CTA rules, disclosure requirements, language, subtitle policy, visual tone, animation intensity, platform rules, and music/voice requirements.

The prompt assistant should not merely rewrite the user's sentence. It should generate an editorial brief. For example, “make this professional” should become a structured request containing objective, audience, platform, desired duration, hook, protected content, allowed cuts, brand requirements, caption behavior, pacing preference, CTA, audio treatment, and export target. The user should review that brief before the AI generates its edit plan.

The final render should remain deterministic FFmpeg output generated from the approved timeline. Preview renders can use lower-resolution proxies; final export should rebuild from original assets, not the preview proxy. YouTube's official guidance supports MP4/H.264, 4:2:0, Fast Start, 48 kHz audio, and native recording frame rate as sensible components of a professional web-delivery preset. citeturn929078search0turn929078search2

A post-render validator should reopen the actual MP4 with `ffprobe` and measurement filters. It should verify video dimensions, duration, expected frame rate, H.264 profile, pixel format, color tags, AAC sample rate, stream presence, integrated loudness, true peak, black/frozen intervals, and file readability. It should also sample rendered frames to validate overlays and captions, rather than relying only on timeline coordinates.

## Measurable acceptance criteria

The upgraded editor should not be considered complete merely because a video can be exported. It should pass measurable product, technical, editorial, and regression gates.

For the supplied comparison workflow, the application should be able to ingest the source file, display its actual technical properties, analyze real speech and silence, create an explainable editing plan, show exactly what duration will be removed or added, preserve or deliberately replace the branding according to the selected guideline, render captions when requested and available, and produce a directly downloaded master that can be compared before any WhatsApp or messaging recompression.

For technical mastering, the direct output should have no unexplained true-peak overs; a web/social preset should enforce its declared true-peak ceiling, while the EBU broadcast preset should use the appropriate R128 loudness target and BS.1770 measurement. citeturn996028search0turn996028search1turn996028search8

For standard SDR exports, the pipeline should explicitly emit Rec.709-compatible metadata and verify it after rendering. citeturn996028search2turn996028search3

For a YouTube/web master, the validation suite should confirm MP4, H.264, progressive 4:2:0 output, Fast Start, 48 kHz audio, and source-consistent frame rate unless the user explicitly requested conversion. citeturn929078search0turn929078search2

For vertical social output, 9:16 should be available as a proper reframed canvas rather than a simple center crop when subject-aware reframing is available. TikTok's official materials support 9:16 as the preferred full-screen vertical presentation and recognize 9:16, 1:1, and 16:9 placement ratios. citeturn929078search3turn929078search7

Caption QA should detect lines outside configured safe zones, excessive line length, missing requested captions, low-confidence transcription, missing glyph support, clipping, excessive line count, and insufficient foreground/background contrast. A 4.5:1 contrast target for normal-sized caption text is a useful accessibility-oriented benchmark derived from WCAG, while clearly labeling that as a readability QA policy rather than claiming that the MP4 itself is formally WCAG-certified. citeturn996028search4turn996028search5

Every automatic edit must be undoable. Original source assets must remain unchanged. AI plans must be previewed before commit. Unsupported instructions must be surfaced as unsupported rather than silently ignored. Brand conflicts must require review. Final export must be reproducible from the saved timeline.

## Copy-paste-ready Fable 5.2 implementation prompt

```text
You are Fable 5.2 acting as a senior post-production engineer, senior video editor,
AI media systems engineer, full-stack engineer, QA engineer, and UX architect.

You are working on my EXISTING LEXNIS marketing agency application.

DO NOT build a separate demo.
DO NOT replace the existing application.
DO NOT produce only an implementation plan.
DO NOT claim that something works until you have inspected, implemented, rendered,
measured, and tested it.

Your assignment is to upgrade the existing VIDEO EDITING system to professional
international post-production quality while preserving all existing Image, GIF,
campaign, public-testing, and account functionality.

============================================================
FILES THAT MUST BE INSPECTED FIRST
============================================================

The working materials are:

1. User-designated source/reference video:
   /mnt/data/e96aba6752a648f6b1211ca0633f2795.mp4

2. User-designated LEXNIS-edited comparison:
   /mnt/data/WhatsApp Video 2026-11-15 at 13.25.02.mp4

3. Current repository:
   /mnt/data/marketing-agency-main (3)(1).zip

FIRST ACTION:
Inspect all three files.

Unpack the repository safely.

Use ffprobe / FFmpeg and local frame inspection to compare the two videos.

Do NOT assume the first file is technically pristine/raw merely because the user calls
it the unedited comparison.

Do NOT assume every codec difference in the WhatsApp-named file came from LEXNIS,
because WhatsApp or another transport step may have recompressed it.

Where possible, reproduce an edit using the app and inspect the DIRECT LEXNIS export
before any messaging-platform recompression.

Document evidence before changing code.

============================================================
KNOWN EVIDENCE FROM THE CURRENT COMPARISON
============================================================

Verify these values yourself rather than blindly trusting this prompt.

The first supplied comparison has been observed at approximately:

- 13.04 seconds
- 464 × 832 portrait
- H.264 High Profile
- approximately 59.97 fps
- yuv420p
- BT.709 matrix metadata
- AAC stereo
- 48 kHz audio
- ~2.04 Mbps video bitrate
- ~127 kbps audio
- ~-17.1 LUFS integrated
- ~-2.5 dBTP measured true peak

The second supplied comparison has been observed at approximately:

- 15.71 seconds
- 464 × 832 portrait
- H.264 Baseline Profile
- approximately 59.97 fps average
- yuv420p
- AAC stereo
- 44.1 kHz audio
- ~1.61 Mbps video bitrate
- ~63 kbps audio
- ~-17.3 LUFS integrated
- approximately +0.5 dBTP measured true peak

The second filename indicates a WhatsApp derivative, so profile, bitrate and sample-rate
changes MUST NOT automatically be blamed on LEXNIS.

Frame sampling has also indicated that the user-designated reference contains visible
LEXNIS branding and some burned-in subtitles while corresponding sampled frames of
the supplied edited comparison do not.

Verify this by inspecting the actual files.

The second file is approximately 2.67 seconds longer.

A professional editor must make duration changes explainable.

============================================================
FORMAL STANDARDS VS EDITORIAL BEST PRACTICES
============================================================

Do not describe every recommendation as an international standard.

Implement and label them correctly.

FORMAL / TECHNICAL REFERENCES:

A. ITU-R BS.1770
Use a BS.1770-compatible measurement process for programme loudness and true peak.

B. EBU R128
Provide an explicit Broadcast / EBU mastering preset using the relevant R128 target.
Do NOT apply -23 LUFS indiscriminately to social media.
Social/web loudness targets must be product delivery presets, not falsely labelled
as EBU compliance.

C. ITU-R BT.709 / Rec.709
Use an explicit Rec.709 SDR workflow for normal SDR exports.
Preserve or intentionally convert:
- color primaries
- transfer characteristics
- matrix coefficients
- range
and validate final metadata after render.

D. Accessibility-oriented caption QA
Use WCAG-relevant contrast principles as a readability benchmark where applicable.
Do not claim an MP4 is automatically “WCAG certified.”
Provide captions and subtitle support for accessible synchronized media workflows.

E. Platform-specific delivery
Implement named presets rather than one universal export.

Examples:
- Web / YouTube
- Vertical Social / Reels/TikTok
- Square Social
- Broadcast / EBU
- Source Master
- Custom

For YouTube/web style output, support:
- MP4
- H.264
- progressive
- yuv420p
- High Profile where compatible
- AAC-LC
- 48 kHz
- faststart
- native/source-consistent frame rate unless deliberate conversion is requested

For vertical short-form output:
- proper 9:16 canvas
- high-resolution output when the source supports it
- platform safe-zone overlays
- subject-aware reframe where locally available

EDITORIAL BEST PRACTICES ARE NOT FORMAL STANDARDS.

These include:
- cut timing
- narrative rhythm
- hook strength
- pacing
- emphasis punch-ins
- B-roll timing
- J/L cuts
- music synchronization
- transition restraint
- reaction timing
- title animation
- lower thirds
- CTA timing

Implement these contextually.

Never state that “0.5-second crossfades are a global professional standard” or similar.

============================================================
INSPECT THE CURRENT IMPLEMENTATION
============================================================

Inspect at least:

video_quick_edit.py
video_ai_editor.py
video_analysis.py
video_analysis_schemas.py
video_editor.py
video_ffmpeg.py
video_operations.py
video_projects.py
video_brand_editing.py
video_brand_context.py
video_guideline_api.py
brand_guidelines.py
guideline_api.py
video_captions.py
video_transcription.py
video_variants.py
video_compliance.py
video_revisions.py
video_assets.py
video_jobs.py
video_models.py
public_access.py
server.py

static/js/video-editor.js
static/js/video-studio.js
static/js/video-brand-editor.js
static/js/video-quick-editor.js
static/js/creative-workflow.js
index.html

and all relevant tests.

Trace real calls from UI to API to project model to timeline to FFmpeg render.

============================================================
KNOWN CURRENT IMPLEMENTATION LIMITATIONS TO VERIFY
============================================================

The current repository appears to contain strong foundations but several important
limitations.

VERIFY EACH OF THESE.

1. video_analysis.py currently performs real scene/silence work, but some fields appear
to be placeholders or defaults rather than true analysis.

Examples to inspect:

motion_score = 0.5
speech_present = False
audio peak value initialized around -1.5

Replace placeholder analysis with measured analysis.

2. video_quick_edit.py appears to create repeated/alternating “subtle zooms” according
to timing rules rather than editorial meaning.

Do not use arbitrary alternating zooms as the definition of professional editing.

3. auto polish appears capable of adding generalized transitions such as 0.5 second
crossfades.

Professional editing must select transition type and duration based on context.

Clean cuts should often remain clean cuts.

4. caption generation depends on transcription availability.

If transcription is unavailable:
- state why
- retain SRT import
- provide local model setup
- never silently omit requested captions

5. Video brand guideline controls already appear to exist in video-brand-editor.js,
but Quick Edit appears to move brand/guideline fields into an optional/collapsed area.

This is NOT sufficient.

Brand Guidelines must become a visible first-class workflow step like Image & GIF.

============================================================
PRIMARY PRODUCT OBJECTIVE
============================================================

Make VIDEO EDITING as simple, guided, brand-aware and AI-assisted as the existing
Image & GIF workflow, while making the actual edit significantly more professional.

The normal user should experience:

STEP 1
Source Video

STEP 2
Brand Guidelines

STEP 3
Goal / Creative Brief

STEP 4
AI Prompt Assistant

STEP 5
Professional Edit Settings

STEP 6
AI Analysis + Proposed Edit

STEP 7
Before / After Preview

STEP 8
Brand + Technical QA

STEP 9
Export

The Advanced Timeline remains available but is not required for a beginner.

State must persist when moving backward/forward.

============================================================
BRAND GUIDELINES MUST BE FIRST-CLASS
============================================================

Do not hide guideline upload inside:

“Brand, purpose & name (optional)”

Make it an explicit visible step.

Reuse the same guideline system used by Image & GIF.

Allow:

Upload Guidelines
Select Existing Guidelines
Select Brand Kit
View Extracted Rules
Correct Extracted Rules
Replace Guidelines
Remove Guidelines
Apply Guidelines
Check Compliance

Supported safe formats may include:

PDF
DOCX
TXT
MD
JSON

Reuse the existing safe parser infrastructure.

Do not create a separate incompatible video guideline database.

The same reviewed guideline should work for:

Image
GIF
Video Generation
Video Editing

============================================================
VIDEO-SPECIFIC BRAND RULE MODEL
============================================================

Extend structured brand rules where necessary.

Represent:

brand_name
primary_colors
secondary_colors
background_colors
approved_fonts
fallback_fonts
logo_asset_id
logo_variants
logo_clear_space
logo_minimum_size
logo_placement_preferences
title_style
lower_third_style
caption_style
caption_font
caption_color
caption_background
caption_position
caption_case_policy
animation_style
transition_style
motion_intensity
visual_tone
CTA
CTA_position
disclosures
required_elements
prohibited_elements
prohibited_effects
platform_preferences
language
RTL requirements
music_style
voice_treatment
safe_zone_profile
aspect_ratio_preferences

For every extracted rule distinguish:

EXPLICIT REQUIREMENT
EXPLICIT PREFERENCE
INFERRED SUGGESTION
UNKNOWN
CONFLICT

Do not invent rules and present them as requirements.

============================================================
REPLACE PLACEHOLDER MEDIA ANALYSIS
============================================================

Create a real persistent analysis layer.

Cache by source content hash.

For each asset measure or infer locally where feasible:

duration
width
height
display aspect
pixel aspect
rotation
frame rate
frame-rate mode where detectable
codec
profile
level
pixel format
bit depth
color primaries
transfer
matrix
range
audio codec
sample rate
channels
audio bitrate

SHOT ANALYSIS:

shot boundaries
scene-change confidence
shot duration
representative frame
brightness
contrast
sharpness
motion score
camera movement estimate
face/subject presence where locally available
subject bounding area
headroom
subject centering
candidate crop safety
duplicate/frozen frame regions

AUDIO ANALYSIS:

speech activity
silence
integrated loudness
short-term loudness where useful
true peak
clipping/overs
loudness range
dialogue/music/ambient classification where feasible
channel balance

SPEECH ANALYSIS:

transcript
word timestamps
confidence
language
sentence boundaries
filler candidates
repeated phrases
false starts
recording-direction phrases
semantic sections

Never populate “measured” fields with constants.

If a metric is not measured:
return null / NOT_CHECKED / unavailable.

============================================================
EDITORIAL INTELLIGENCE LAYER
============================================================

Build an editorial scoring system.

Every candidate segment and cut point should be able to carry scores such as:

speech_importance
semantic_importance
hook_value
visual_quality
motion_interest
face_quality
framing_quality
pause_confidence
filler_confidence
continuity_risk
brand_relevance
cta_relevance
cut_confidence

The edit should be explainable.

Example:

CUT:
11.82s → 12.47s

Reason:
Long non-speech pause with no meaningful gesture.

Confidence:
0.94

Effect:
Reduces total duration by 0.65 seconds.

Do not cut pauses mechanically when the speaker is making an intentional dramatic pause.

Do not remove breaths so aggressively that speech sounds unnatural.

============================================================
TALKING-HEAD EDITORIAL MODE
============================================================

Create a professional talking-head mode because the supplied comparison is this type.

It should prioritize:

clear speech
natural rhythm
removal of true recording mistakes
careful filler cleanup
controlled pause tightening
gesture-aware edit points
sentence-aware cuts
subtle emphasis changes
clean captions
brand-safe logo
optional speaker lower third
optional supporting text
clean CTA
balanced audio

PUNCH-INS:

Do not alternate zoom values mechanically.

Only create punch-ins when justified, such as:

new thought
emphasis
semantic beat
cut masking
visual reset after a long static section

Set configurable limits.

Avoid excessive scale that noticeably reduces quality.

Maintain eyes and face within safe framing.

When possible, animate zoom using proper easing.

Do not “pulse” continuously.

============================================================
TRANSITION ENGINE
============================================================

Replace generic crossfade behavior with a contextual transition policy.

Default:
clean cut

Use dissolve/crossfade only when justified by:

passage of time
soft emotional transition
montage
brand-specific instruction
visual continuity requirement

Support a small professional vocabulary first:

CUT
DISSOLVE
FADE TO/FROM BLACK
J-CUT
L-CUT
DIP if justified

Do not add flashy transitions unless requested by brand guideline or user.

Every transition must be represented in the edit plan.

============================================================
CAPTION SYSTEM
============================================================

Upgrade captions into a professional subsystem.

Support:

local Whisper/faster-whisper or existing local ASR
SRT import
VTT export
burned captions
sidecar captions
word confidence
review flags
speaker labels where available
English
Arabic / RTL
brand style
line wrapping
safe zones

Caption QA should evaluate:

max lines
line width
duration
reading speed
characters per second
minimum display time
overlap
missing punctuation where detectable
confidence
glyph support
contrast
safe-zone position

Do not invent transcript text.

Low-confidence words must be flagged.

Provide a transcript/caption review screen before final burn-in.

============================================================
TYPOGRAPHY AND GRAPHICS
============================================================

Titles, lower thirds and captions should be real compositional elements.

Add semantic roles:

hook
headline
speaker_name
speaker_role
supporting_point
metric
disclosure
caption
cta
end_card

Rules should control each role independently.

Implement:

font hierarchy
font fallback
RTL shaping
line wrapping
measured text bounds
margin/padding
safe zones
brand colors
background plate
contrast validation

Do not place every title at 50% / 50%.

Use layout roles.

============================================================
LOGO HANDLING
============================================================

Respect:

clear space
placement
minimum size
safe zone
aspect ratio
opacity requirements
variant rules

Do not stretch logos.

Do not place a dark logo on a dark background if another approved variant is available.

Allow a subtle approved backplate only when brand rules permit it.

============================================================
AUDIO POST-PRODUCTION
============================================================

Implement real audio analysis and mastering.

Measure with BS.1770-compatible tools.

Provide named presets.

Example:

SOCIAL / WEB:
configurable integrated loudness policy
true peak ceiling such as -1.0 to -1.5 dBTP depending on policy
48 kHz AAC master

BROADCAST / EBU:
R128 programme target
appropriate true-peak ceiling
48 kHz

SOURCE MASTER:
preserve source dynamics unless repair is requested

Do not call the social preset “EBU compliant.”

Add:

dialogue normalization
music ducking
fade control
clip gain
mix bus logic
true peak limiter where appropriate
silence/noise analysis

Never allow final output with unexplained true-peak overs above the preset ceiling.

============================================================
COLOR MANAGEMENT
============================================================

Create an explicit Rec.709 SDR pipeline.

Do not rely only on implicit defaults.

At ingest:
read source tags.

At render:
preserve or intentionally convert.

At export:
write and validate appropriate:
color_primaries
color_trc
colorspace
range where appropriate

Do not invent HDR processing.

If HDR is unsupported:
detect it
warn clearly
do not silently treat it as ordinary SDR.

============================================================
FRAME RATE
============================================================

Preserve source frame rate by default when it is sane and supported.

Do not automatically convert:

59.94 → 60
29.97 → 30
24 → 30

unless required by a specific output preset.

Represent deliberate frame-rate conversion explicitly.

Validate final average frame rate and cadence.

============================================================
EXPORT PRESETS
============================================================

Build professional export presets.

1. Source Master
Preserve source dimensions and frame rate.
High quality.
48 kHz if audio is rendered.
Rec.709 SDR when appropriate.

2. Web / YouTube
MP4
H.264
High Profile where compatible
yuv420p
progressive
faststart
AAC-LC
48 kHz
native/source frame rate
quality/bitrate appropriate to resolution

3. Vertical Social
9:16
1080 × 1920 when source quality supports it
otherwise do not falsely upscale as restored detail
H.264
AAC
48 kHz
platform-safe overlays

4. Square Social
1:1

5. Portrait Feed
4:5

6. Broadcast / EBU
explicit loudness/mastering profile
do not pretend this alone certifies station delivery

7. Custom

Do not hardcode a universal low bitrate.

Use quality-based encode or sensible resolution-aware targets.

============================================================
POST-RENDER VALIDATION
============================================================

THIS IS REQUIRED.

After every final render:

reopen the actual output.

Use ffprobe and FFmpeg measurement.

Validate:

file readable
duration
dimensions
aspect
frame rate
frame count sanity
codec
profile
pixel format
audio codec
audio sample rate
audio channels
color metadata
integrated loudness
true peak
black-frame intervals
freeze intervals

Sample actual rendered frames to validate:

logo visible when required
caption visible when required
title visible
safe-zone placement
text not clipped
subject not accidentally cropped
CTA exists where required

Do not mark the job as professionally complete only because FFmpeg returned exit code 0.

============================================================
BEFORE / AFTER QUALITY REPORT
============================================================

For every completed edit provide an explainable report:

SOURCE:
technical properties

EDIT PLAN:
operations and reasons

RESULT:
technical properties

CHANGES:
duration removed/added
cuts
zoom/punch-ins
captions
graphics
brand changes
audio changes
export changes

QA:
PASS
WARNING
FAIL
NOT_CHECKED

Never claim checks that were not performed.

============================================================
AI PROMPT ASSISTANT
============================================================

Make the Video Editor prompt assistant equivalent in usability to Image & GIF.

Visible actions:

Generate Professional Brief
Improve Request
Apply Brand Guidelines
Make More Professional
Optimize for Platform
Simplify
Use Suggested Brief
Edit Manually

The assistant should transform:

“make this professional”

into a structured editable brief, not merely a longer paragraph.

Example fields:

objective
audience
platform
target duration
hook strategy
protected content
allowed trimming
caption policy
brand treatment
pacing
CTA
audio
export target

User must be able to edit it.

============================================================
LOCAL-FIRST AI
============================================================

Core editing must not require paid APIs.

Use existing local infrastructure where possible.

Optional local components may include:

FFmpeg / ffprobe
PySceneDetect
Whisper/faster-whisper
OpenCV
Pillow
existing local LLM / llama.cpp integration

Do not automatically download massive models during application startup.

If AI models are unavailable:
deterministic editing and manual timeline editing must still work.

============================================================
NON-DESTRUCTIVE EDITING
============================================================

Original uploaded media must never be overwritten.

Every change must operate on:

project timeline
EditPlan
validated operation
revision

Maintain:

preview
apply
reject
undo
redo
revision history

AI may only propose supported operations.

AI may never emit arbitrary shell commands for execution.

============================================================
EDL / TIMELINE MODEL
============================================================

Strengthen the existing EditPlan system.

Each operation should contain:

operation_id
operation_type
target
time range
parameters
editorial reason
evidence
confidence
brand impact
technical impact
source = user / rule / AI
reversible = true

Persist the exact approved plan used for each export.

============================================================
VIDEO ANALYSIS → AI PLAN
============================================================

Do not pass raw files blindly to the text model.

Build bounded structured context containing:

technical metadata
shot list
speech segments
transcript summary
important transcript excerpts
brand rules
creative objective
platform rules
timeline state
user instruction

Treat transcript and uploaded guideline text as untrusted content.

Do not let document text override system instructions.

============================================================
BRAND COMPLIANCE ENGINE
============================================================

Upgrade compliance beyond timeline-only checks.

TIMELINE CHECKS:
required title
CTA
logo
font
palette
duration
aspect
language
disclosure

RENDERED CHECKS:
logo visible
caption visible
text clipped
contrast
safe zones
final duration
actual dimensions
actual color tags
actual audio loudness
actual true peak

Return:

PASS
WARNING
FAIL
NOT_CHECKED

Never convert NOT_CHECKED into PASS.

============================================================
PUBLIC TEST MODE
============================================================

Preserve the existing PUBLIC_TEST_MODE functionality.

During public testing:

creative tools remain available
Video Studio remains available
guideline upload remains available
AI prompt assistant remains available
video editing remains available
exports remain available

BUT KEEP:

guest isolation
safe upload limits
resource quotas
job concurrency
timeouts
admin protection
filesystem protection
command safety

Public access does not mean disabling security.

============================================================
SUPPLIED VIDEO REGRESSION TEST
============================================================

Create a regression fixture based on the supplied source/reference video where legally
and practically appropriate for local development.

The test should prove that the editor:

reads actual source properties
does not manufacture duration unexpectedly
explains every cut
preserves frame rate unless conversion requested
produces captions when requested and ASR is available
keeps required branding
does not clip audio
meets selected true-peak ceiling
retains valid Rec.709 SDR metadata where applicable
produces playable MP4
does not create freeze/black errors
keeps original unchanged

If the supplied WhatsApp file is not a direct app export, do not use it as the definitive
codec-quality golden master.

============================================================
AUTOMATED TESTS
============================================================

Add unit tests for:

media measurement
shot detection
silence detection
motion score
audio loudness parsing
true peak parsing
frame-rate handling
brand extraction
caption segmentation
caption QA
operation validation
compliance
export preset building
post-render validation

Add integration tests:

upload video
upload guideline
analyze
generate brief
generate edit plan
preview
apply
render
measure
compare
revise
undo
redo
export

Add browser tests covering the simple workflow.

============================================================
UX TEST
============================================================

A new user must be able to do this without opening Advanced mode:

1. Upload video
2. Upload/select guidelines
3. Describe goal
4. Let AI improve brief
5. Choose edit style/platform
6. Create proposed edit
7. Compare Original / Edited
8. See what changed
9. Request a revision
10. Check brand + technical QA
11. Export

The workflow must be as understandable as Image & GIF.

============================================================
PRIORITY ORDER
============================================================

P0
Inspect comparison files and direct current render behavior.

P0
Make Brand Guidelines a visible first-class Video Editor step.

P0
Replace fake/default analysis metrics with real measurements.

P0
Fix audio true-peak validation and post-render QA.

P1
Upgrade editorial decision logic.

P1
Upgrade captions.

P1
Upgrade professional export/color/frame-rate handling.

P1
Implement rendered-output compliance checks.

P2
Improve motion graphics, lower thirds and contextual transitions.

P2
Improve subject-aware reframing and crop safety.

Do not spend the first phase adding decorative UI while foundational analysis remains
incorrect.

============================================================
ACCEPTANCE CRITERIA
============================================================

The upgrade is complete only when all of the following are true:

- The two supplied videos were inspected.
- The current repo was inspected.
- Direct LEXNIS output was tested when practical.
- Video guidelines are visible without opening a hidden optional details section.
- Guidelines are shared with Image/GIF.
- AI Prompt Assistant is visible and functional.
- Media analysis contains actual measured values.
- No placeholder motion/audio metric is presented as analysis.
- Editing decisions are explainable.
- Punch-ins are contextual rather than alternating blindly.
- Crossfades are not applied indiscriminately.
- Captions work when ASR/import is available.
- Missing captions have explicit diagnostics.
- English and Arabic/RTL remain supported.
- Original media remains immutable.
- Timeline edits are versioned and undoable.
- Direct output obeys selected audio true-peak ceiling.
- Direct output frame rate is intentional and validated.
- Rec.709 SDR metadata is explicit/validated when appropriate.
- Professional export presets exist.
- Post-render validation runs on the actual MP4.
- Brand compliance checks rendered output where technically possible.
- Guest/public test mode remains functional.
- Existing Image/GIF features continue to pass.
- Tests demonstrate real rendered output rather than mocks alone.

============================================================
FINAL DELIVERABLE
============================================================

DO THE IMPLEMENTATION.

Do not stop at analysis.

At completion provide:

1. Repository files changed.
2. Root causes found.
3. Comparison findings from the two videos.
4. Improvements implemented.
5. Exact analysis metrics now measured.
6. Exact editing decisions now supported.
7. Guideline workflow screenshots or DOM-test evidence.
8. Direct-render ffprobe output.
9. Direct-render loudness / true-peak measurements.
10. Export preset definitions.
11. Automated tests run and results.
12. Remaining limitations.
13. Missing optional local models/dependencies.
14. Any feature that remains NOT_CHECKED.

Most importantly:

A successfully rendered MP4 is NOT automatically a professionally edited video.

The system must prove quality through:

content-aware editing
brand adherence
technical mastering
render validation
before/after comparison
and measurable QA.
```

The most important conclusion from the inspected implementation is that LEXNIS already has much of the **infrastructure** needed for a serious editor—structured operations, revisions, FFmpeg rendering, guideline models, transcription hooks, compliance logic, and local-first execution—but the **decision intelligence and verification layers are still too shallow**. The largest quality gain will come from replacing placeholder analysis and fixed recipes with measured media analysis, contextual editorial decisions, visible brand-guideline workflow, and post-render QA rather than simply adding more effects.
