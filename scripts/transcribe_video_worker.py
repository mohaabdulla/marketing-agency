"""Local-only speech worker; parent bounds duration, output and process lifetime."""
import json
import sys
from pathlib import Path
from faster_whisper import WhisperModel

model_dir,source,destination,language=sys.argv[1:]
model=WhisperModel(model_dir,device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
segments,info=model.transcribe(source,language=None if language=='auto' else language.split('-')[0],
    beam_size=5,vad_filter=True,word_timestamps=True,condition_on_previous_text=False)
cues=[]
for segment in segments:
    if segment.no_speech_prob>.8 and segment.avg_logprob<-1:continue
    words=[dict(start=round(w.start,3),end=round(w.end,3),word=w.word.strip(),probability=round(w.probability,3)) for w in segment.words or [] if w.word.strip()]
    cues.append(dict(start=round(segment.start,3),end=round(segment.end,3),text=segment.text.strip(),words=words))
    if len(cues)>2000 or sum(len(c['words']) for c in cues)>6000:raise ValueError('Transcript exceeds budget')
Path(destination).write_text(json.dumps(dict(language=info.language,language_probability=info.language_probability,segments=cues),ensure_ascii=False),encoding='utf-8')
