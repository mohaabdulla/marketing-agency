# Video editing upgrade — 2026-11-15

Scope: the Quick Edit path and final MP4 export of the existing Video Studio. Image, GIF,
campaign, agency and public-test features were not redesigned.

## 1. What the two supplied videos actually are

Measured locally with ffprobe and FFmpeg `ebur128` (ITU-R BS.1770):

| | `e96aba…2795.mp4` | `WhatsApp Video 2026-11-15 at 13.25.02.mp4` |
| --- | --- | --- |
| Duration | 13.04 s | 15.71 s |
| Picture | 464×832, H.264 **High**, 35325/589 (59.97) fps, yuv420p, progressive | 464×832, H.264 **Baseline**, 59.97 fps |
| Colour tags | matrix bt709 only (primaries/transfer **missing**) | bt709 primaries/transfer/matrix |
| Audio | AAC-LC 48 kHz stereo, 127 kb/s | AAC-LC 44.1 kHz stereo, 63 kb/s |
| Loudness | −17.0 LUFS, LRA 6.2 LU | −17.3 LUFS, LRA 12.4 LU |
| True peak | −2.5 dBTP | **+0.5 dBTP** |
| Branding | LEXNIS logo + burned captions | none |

The brief that came with these files had the roles reversed. Frame inspection shows the
13.04 s file is the **LEXNIS export** (logo, captions, tightened, 48 kHz, peaks under control)
and the 15.71 s WhatsApp file is the **raw recording** (no branding, 44.1 kHz, true peak over
0 dBTP). So the edit *removed* 2.67 s and added branding; it did not add duration or lose
branding, and the true-peak over belongs to the source, not to the LEXNIS encoder.

Real defects found in the previous export and code:

1. Colour primaries and transfer tags were not written (only the matrix was).
2. A caption mis-hearing ("Khawar Mee and Ahmad") shipped without any review flag.
3. `video_analysis.py` reported constants as analysis: `motion_score = 0.5`,
   `speech_present = False`, `peak_db = -1.5`, and assumed 48 kHz stereo.
4. Quick Edit alternated zoom pairs (1.00→1.035, 1.07→1.09) on a timer, and "professional"
   in the instruction made the polish step add a fade in *and* out to every clip, i.e. a dip
   at every cut.
5. Auto Polish added a 0.5 s crossfade between all clips; an unrecognised instruction was
   answered with an unrelated 0.3 s transition.
6. Frame rate was passed to FFmpeg as a rounded decimal instead of the source's rational.
7. Loudness normalisation was single-pass and unverified; nothing reopened the exported file.
8. Brand guideline controls sat inside a collapsed "Brand, purpose & name (optional)" section.

## 2. What changed

### Measured analysis (`video_measure.py`, `video_analysis.py`, analysis version 2)

Read from the file: codec, profile, level, pixel format, bit depth, field order, exact frame
rate rational, nominal rate and variable-frame-rate flag, frame count, bitrates, colour
range/matrix/transfer/primaries, HDR flag, sample/display aspect, rotation, orientation,
audio codec/sample rate/channels/bitrate.

Measured: integrated loudness, loudness range and true peak (BS.1770); silence intervals and
share; per shot: mean luma change between sampled frames and a motion score scaled from it,
Laplacian sharpness, brightness, contrast, audio-activity ratio, and a frontal face box with
headroom and centring (OpenCV Haar, accepted only when it reappears in 2 of 3 frames); black
intervals and frozen intervals for the whole file.

A value that could not be measured is `null` and listed in `not_measured`. `speech_present`
is only true/false when a transcript exists; otherwise it is `null`. Analysis is cached by
content hash.

### Editorial decisions (`video_quick_edit.py`)

- **Cuts** carry reason, evidence, confidence and seconds removed. A pause inside a sentence
  is tightened above 0.65 s (0.32 s kept); a pause after a finished sentence is left alone up
  to 1.0 s and then keeps 0.5 s. When silence was measured and the gap is not actually quiet,
  the pause is kept. Fillers are cut only at ≥ 60% recognition confidence. Low-confidence
  cuts are listed for review.
- **Punch-ins** are held framings, not continuous zooms. Framing changes only across a cut or
  at a new sentence after the current framing was held ≥ 4 s. Maximum scale is a setting
  (3%, 6% default, 10%) and drops to 3% when the detected face has little headroom. Without
  word timings no punch-in is added, and the report says why.
- **Transitions**: clean cuts by default; one short fade in and out at the ends. Dissolves
  only when the brand transition rules ask for them. Unrecognised instructions change nothing
  and say so.
- **Captions**: cues that flash by are joined to a neighbour; cues are held ≥ 0.8 s where
  possible; each cue keeps its word confidences. If captions were requested and none could be
  made, the report states the exact reason (no audio, speech model not installed, or no words
  found) and QA fails the "Captions rendered" check.
- The decision list also records the transition policy, captions, logo and audio mastering.

These are editorial practices implemented as rules, not international standards.

### Delivery presets (`video_presets.py`, `GET /api/video/export-presets`)

All presets: MP4, H.264 High, yuv420p, progressive, Rec.709 limited-range tags, fast start,
AAC-LC 48 kHz stereo, source frame rate as its exact rational. Canvases crop to the aspect and
never exceed the source resolution.

| Preset | Aspect | CRF / x264 | Loudness target | True-peak ceiling |
| --- | --- | --- | --- | --- |
| `source-master` | source | 16 / slow | not normalised | −1.0 dBTP |
| `web-youtube` (default) | source | 18 / medium | −16 LUFS | −1.5 dBTP |
| `vertical-social` | 9:16 | 18 / medium | −16 LUFS | −1.5 dBTP |
| `square-social` | 1:1 | 18 / medium | −16 LUFS | −1.5 dBTP |
| `portrait-feed` | 4:5 | 18 / medium | −16 LUFS | −1.5 dBTP |
| `broadcast-ebu` | source | 16 / slow | −23 LUFS (EBU R128) | −2.0 dBTP |

Loudness and true peak are *measured* per BS.1770 for every preset. Only `broadcast-ebu` uses
the R128 programme target, and it is a mastering profile, not a station delivery
certification. The −16 LUFS targets are product choices and are not labelled EBU compliant.

### Post-render validation (`video_qa.py`)

Every final MP4 (Quick Edit and `/api/video/export`) is reopened and measured. After the
render, a measured second audio pass applies a fixed gain when the programme is off target or
over the ceiling; the ceiling always wins, and the video stream is copied untouched.

Checks, each PASS / WARNING / FAIL / NOT_CHECKED: file readable; duration vs timeline; frame
size; frame rate vs intended; frame count; codec/profile/pixel format/progressive; colour
tags; HDR source handling; fast start; audio format; true peak vs ceiling; integrated
loudness vs target; black intervals; frozen intervals; logo visible (correlation of the
rendered frame with the logo artwork at its planned position), logo safe margin and aspect;
caption readability (reading speed, minimum time, overlap, truncated lines, safe margins,
low-confidence words); captions reviewed; captions visible in sampled frames; caption
contrast measured in rendered frames (WCAG formula used as a readability benchmark, not a
WCAG certification); duration change fully explained by the listed cuts; source file SHA-256
unchanged. NOT_CHECKED is never converted to PASS.

### Guided workflow (`static/js/video-quick-editor.js`)

Quick Edit is now eight visible steps: Source → Brand guidelines & logo → Goal & brief → AI
prompt assistant → Edit settings → Before / after with "What changed" → Brand & technical QA →
Export. The guideline controls are the same shared guideline system as Image & GIF and are
no longer inside a collapsed optional section. Settings add the delivery preset and the
largest punch-in. The Advanced editor is unchanged.

## 3. Direct export of the supplied raw recording

Quick Edit, English, `web-youtube`, LEXNIS logo; local faster-whisper captions.

- 15.707 s → 13.74 s. One cut: 13.74–15.707 s, "Trailing recording instruction", closing
  phrase "Okay, that's it.", confidence 48% (listed for review). 0.000 s unexplained.
- Two framing changes (6% punch-in at 5.36 s, back at 9.40 s), both at new sentences.
- 8 caption cues from 46 recognised words; flagged as an unreviewed draft. The name line is
  still mis-heard ("Khawar Mee and Ahmad"): recognition cannot be trusted for names.
- ffprobe: H.264 High, yuv420p, progressive, 464×832, 35325/589 fps (source rate), 824
  frames, bt709 primaries/transfer/matrix, limited range, fast start; AAC-LC 48 kHz stereo.
- Loudness: −17.4 LUFS integrated, true peak −1.8 dBTP (source +0.5 dBTP). Single-pass result
  was −18.1 LUFS / −2.5 dBTP; the measured pass added +0.7 dB, limited by the −1.5 dBTP
  ceiling. The programme stays 1.4 LU under the −16 target because the ceiling takes priority.
- QA: 20 PASS, 3 WARNING, 0 FAIL, 0 NOT_CHECKED. Warnings: loudness under target (peak
  limited), two cues above 20 characters/second, captions not reviewed by a person.

The earlier LEXNIS export of the same recording was 13.04 s, 0.70 s shorter. The old rule
trimmed every gap over 0.65 s; the new rules leave pauses after finished sentences alone up to
1.0 s. Which exact pauses the earlier export removed was not reconstructed.

## 4. Tests

- `scripts/test_video_mastering.py`: 10 passed, 1 skipped by default. Parsing, measured
  analysis vs constants, cut rules, punch-in rules, caption cues and QA, transition defaults,
  presets, and three real-render integration tests (direct export measured and explained;
  broadcast preset and missing-caption diagnosis; validator failing a non-conforming file and
  the export endpoint's safety pass). The skipped test runs the same checks on real footage
  when `LEXNIS_VIDEO_REGRESSION_SOURCE` points to a local file; it passed on the supplied raw
  recording. That footage shows a real person and is not committed.
- `scripts/test_video_guided_edit_browser.py`: passed. Real server and browser: eight steps
  in order, guideline controls visible outside any collapsed section, guideline and logo
  upload, preset list, real export, decision list, QA table, downloaded file re-probed,
  no horizontal scroll at 390 px. Screenshots in `output/video-guided-edit/`.
- Existing: `test_video_studio.py` 12 passed, `test_quick_video_edit.py` 3 passed,
  `test_public_brand_video.py` 10 passed (guest/public mode). Full regression run: see the
  final section of the session report.

## 5. Not done / limits

- No AI text planner was added to Quick Edit; decisions are measured rules. Semantic
  importance, hook value and "intentional dramatic pause" are approximated by sentence
  punctuation and measured silence only.
- Face detection is a Haar cascade: frontal faces only, no tracking. It limits punch-in size;
  it does not reframe. Subject-aware 9:16 reframing is **not** implemented: aspect changes
  are centre crops.
- J-cuts, L-cuts, dip transitions, lower-third layouts, B-roll and music synchronisation are
  not implemented. Speaker name/role titles use the existing title system.
- Loudness is corrected with single-pass `loudnorm` plus one measured gain pass, not a true
  two-pass linear normalisation, and the correction re-encodes the AAC audio a second time.
  Short-term loudness, dialogue/music classification and denoise are not measured or applied.
- HDR sources are detected and fail QA; there is no tone mapping. Colour is converted to and
  tagged as Rec.709 via swscale; there is no ICC or LUT management.
- Variable-frame-rate sources export at their average rate.
- Caption contrast and visibility are sampled at three cues, not every frame. Logo visibility
  is checked on one frame. Clear-space, minimum-size and variant rules from guidelines are not
  yet enforced beyond the 2% edge margin and aspect check.
- The WebM path and preview renders are not validated. `video_engine.py` AI-generation
  renders do not run the validator.
- The extended brand-rule model in the brief (explicit/inferred/conflict status per rule,
  lower-third and caption style fields) was not added; the existing guideline schema is used.
- Speech recognition needs the optional local faster-whisper runtime (`.venv-asr`). Without
  it captions are reported as missing, with SRT import in the Advanced editor as the fallback.
- OpenCV and PySceneDetect are optional; without OpenCV the visual metrics and the rendered
  logo/caption checks report NOT_CHECKED.
