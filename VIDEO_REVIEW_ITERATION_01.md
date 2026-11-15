# Video review — iteration 01

Input: the user-supplied WhatsApp video dated 2026-11-15 at 13.25.02.
The original file in Downloads is unchanged. The completed browser run and checksums
are recorded in `output/video-review/iteration-01/browser-result.json`.

## Review copy

- `output/video-review/iteration-01/edited.mp4`
- Original: 15.706667 seconds, 464×832, approximately 59.97 fps.
- Edited: 13.04 seconds, 464×832, original frame rate, H.264/AAC.
- Two measured pauses were tightened; the recognized recording remarks at the end were removed.
- Five gentle zoom shots, 11 timed caption cues, company logo on a contrasting backplate,
  and normalized dialogue audio.
- English was explicitly selected. Automatic language detection initially chose Arabic;
  that diagnostic was not used for the delivered English-caption edit.
- Captions are a speech-recognition draft. In particular, review the recognized names
  “Mee” and “Ahmad”; the model assigned low confidence to them.

Background replacement is not implemented in this pass. The original office setting is
retained. Native resolution is preserved; upscaling would not restore absent 4K detail.

## General application changes

The editor now defaults to three sections: video/logo, a short request, and the edited
preview/download. Purpose, guideline review, identity details, prompt assistance and the
full timeline remain available as optional/advanced controls. A single action builds and
renders a derived project rather than leaving the player on the unmodified source.
Original/Edited buttons identify the two different files, and the edited result survives reload.

Quick edit uses the selected video, not arbitrary image/logo clips or repeated copies on
an old timeline. Video import no longer silently truncates source clips to ten seconds,
and an initial video sets a matching native portrait/landscape canvas.

Speech recognition is a shared, local pretrained model. The code does not contain this
video's filename, spoken names, dialogue or exact edit timestamps. Cut points come from
recognized word timings; captions are retimed after cuts. Generic end-marker rules apply
only near the end of a recording. Rules and edit reports remain inspectable.

The old live backend had not reloaded, and browser modules could stay stale. The idle
marketing server was restarted without touching the unrelated service on port 8765.
HTML and the JavaScript import graph now carry content versions with no-store headers;
loaded new pages also show an update/reload notice when another UI version appears.

## Local speech setup

The isolated `.venv-asr` environment avoids changing the image/video Torch environment.
It runs faster-whisper 1.2.1 with compatible PyAV 16.1, CPU int8, word timestamps and
an explicitly downloaded local small model. Processing does not upload the video.
The runtime and model are MIT-licensed upstream: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
and [the model card](https://huggingface.co/Systran/faster-whisper-small).
The model revision installed here is `536b0662742c02347bc0e980a01041f333bce120`.

```powershell
python -m venv .venv-asr
.\.venv-asr\Scripts\python.exe -m pip install -r requirements-speech.txt
.\.venv-asr\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', revision='536b0662742c02347bc0e980a01041f333bce120', local_dir='.model-cache/faster-whisper-small', allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.*'])"
```

`AGENCY_ASR_MODEL_DIR` and `AGENCY_ASR_PYTHON` can select other explicitly installed local
paths. Startup never downloads a model. The text edit-planning model remains optional;
this pass uses real speech inference followed by measured timeline rules, not simulated
text-model inference or arbitrary commands.

## Verification

- Three new quick-edit tests pass: general tail/caption timing, current module versions,
  real media export, guest ownership, and preservation of the original project/source.
- Existing Video Studio: 12 tests pass.
- Shared assistant/guideline tests: six pass.
- Public brand/video backend: ten pass.
- Existing guest editor browser test passes with advanced mode selected explicitly.
- The actual supplied video passes the live browser flow: visible logo upload, short request,
  real edited file, before/after comparison, download, reload, mobile layout and no page errors.

To repeat with any authorized input, `scripts/review_video_iteration.py` uses the local
API, and `scripts/test_live_video_review.py` exercises the actual website. Both accept
the source and output folder as arguments; neither contains a fixed test-video path.
