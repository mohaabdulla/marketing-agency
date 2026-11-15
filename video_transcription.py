"""Managed video transcription using an explicitly installed local CPU speech model."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from video_storage import ROOT,DATA,read,atomic
from video_assets import path_for
from video_ffmpeg import Cancelled,stop_process

LOCK=threading.Lock()


@contextmanager
def speech_slot(job):
    started=time.monotonic()
    while not LOCK.acquire(timeout=.2):
        if job and job.cancelled():raise Cancelled()
        if time.monotonic()-started>600:raise ValueError('Speech queue wait exceeded ten minutes')
    try:yield
    finally:LOCK.release()


def config():
    model=Path(os.environ.get('AGENCY_ASR_MODEL_DIR',str(ROOT/'.model-cache/faster-whisper-small')))
    runtime=Path(os.environ.get('AGENCY_ASR_PYTHON',str(ROOT/('.venv-asr/Scripts/python.exe' if os.name=='nt' else '.venv-asr/bin/python'))))
    return model,runtime


def status():
    model,runtime=config()
    ready=runtime.is_file() and all((model/name).is_file() for name in ('model.bin','config.json','tokenizer.json'))
    return dict(available=ready,engine='Local faster-whisper CPU int8',
                reason='Local speech captions are available; review recognized words.' if ready else 'Install the optional local speech runtime and model to generate captions. Existing SRT import remains available.')


def transcribe(asset_id,language='auto',job=None):
    asset=read('assets',asset_id)
    if not asset.get('has_audio'):raise ValueError('This source has no audio')
    if not 0<asset['duration']<=300:raise ValueError('Transcription supports videos up to five minutes')
    if language not in {'auto','en','ar','ar-BH'}:raise ValueError('Choose English, Arabic or automatic language')
    if not status()['available']:raise ValueError(status()['reason'])
    model,runtime=config();source=path_for(asset_id)
    hasher=hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):hasher.update(chunk)
    digest=hasher.hexdigest()
    fingerprint=str((model/'model.bin').stat().st_mtime_ns)+':'+str((model/'model.bin').stat().st_size)
    cache=DATA/'transcripts';cache.mkdir(exist_ok=True)
    key=cache/(asset_id+'-'+language+'.json')
    if key.is_file():
        value=json.loads(key.read_text(encoding='utf-8'))
        if value.get('source_sha256')==digest and value.get('model_fingerprint')==fingerprint:return value
    with speech_slot(job),tempfile.TemporaryDirectory(dir=DATA/'work',prefix='speech-') as temp:
        output=Path(temp)/'transcript.json'
        if job:job.update(state='running',phase='Recognizing speech locally')
        with (Path(temp)/'speech.log').open('wb') as log:
            process=subprocess.Popen([str(runtime),str(ROOT/'scripts/transcribe_video_worker.py'),str(model.resolve()),str(source),str(output),language],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,shell=False,start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if job and job.cancelled():raise Cancelled()
                    if time.monotonic()-started>600:raise ValueError('Local speech recognition exceeded ten minutes')
                    time.sleep(.1)
                if process.returncode or not output.is_file():raise ValueError('Local speech recognition failed; check the speech runtime installation')
                if output.stat().st_size>2*1024**2:raise ValueError('Transcript exceeds its size budget')
                value=json.loads(output.read_text(encoding='utf-8'))
            finally:
                if process.poll() is None:stop_process(process)
        value.update(asset_id=asset_id,source_sha256=digest,model_fingerprint=fingerprint,engine='faster-whisper',reviewed=False)
        atomic(key,value)
        return value
