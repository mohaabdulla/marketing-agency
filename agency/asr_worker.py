"""Bounded parent launches this worker only with an explicit local Whisper model path."""
import json
import sys
from pathlib import Path
from faster_whisper import WhisperModel

model_path, source, destination, language = sys.argv[1:]
model = WhisperModel(model_path, device='cpu', compute_type='int8', cpu_threads=4,
                     num_workers=1, local_files_only=True)
segments, info = model.transcribe(source, language='ar' if language.startswith('ar') else 'en',
                                  beam_size=3, vad_filter=True, condition_on_previous_text=False)
cues = []
for segment in segments:
    text = segment.text.strip()
    if text and segment.end > segment.start:
        cues.append(dict(start_seconds=round(segment.start, 3), end_seconds=round(segment.end, 3), text=text[:2000]))
    if len(cues) > 2000:
        raise ValueError('Transcript exceeds the 2,000 cue limit')
Path(destination).write_text(json.dumps(cues, ensure_ascii=False), encoding='utf-8')
