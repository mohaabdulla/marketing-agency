"""Private local audio processing; optional Whisper uses existing local weights only."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from html import escape
from .database import repository
from .services import service
from .schemas import RecordInput
from . import assets
from .audio_schemas import Subtitles


def capabilities():
    from video_ffmpeg import binary
    directory = Path(os.environ.get('AGENCY_ASR_MODEL_DIR', '')) if os.environ.get('AGENCY_ASR_MODEL_DIR') else None
    installed = bool(directory and all((directory / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')))
    runtime = importlib.util.find_spec('faster_whisper') is not None
    return dict(ffmpeg=bool(binary('ffmpeg')), ffprobe=bool(binary('ffprobe')),
                asr=dict(runtime_installed=runtime, model_installed=installed, available=runtime and installed,
                         engine='faster-whisper / CTranslate2', languages=['en', 'ar'],
                         reason='Uses AGENCY_ASR_MODEL_DIR with local_files_only=True on CPU int8. No automatic downloads. '
                                'Review the selected model license; inference is verified only by a successful transcription.',
                         verified=False),
                tts=dict(available=False, reason='No reviewed local TTS model is configured. Import a licensed voiceover as an audio asset. Voice cloning is unavailable.'))


def source(client, key):
    item = service.get(client, key, 'assets')
    if item['archived'] or item['data']['asset_type'] not in {'audio', 'video'}:
        raise ValueError('Choose an active registered audio or video asset')
    path = assets.stored_path(item['data']['stored_name'])
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 ** 2), b''):
            digest.update(chunk)
    if digest.hexdigest() != item['data']['sha256']:
        raise ValueError('The source file failed its checksum check')
    return item, path


@assets.serialized_store
def private_asset(client, path, name, parent, note):
    facts = assets.inspect(path, path.name)
    filename = facts['sha256'] + facts['ext']
    target = assets.store() / filename
    if not target.exists():
        # The temporary render directory and final store share a volume.
        path.replace(target)
    data = dict(asset_type='audio', origin='generated', parent_asset_id=parent['id'],
                parent_asset_version=parent['version'],
                sha256=facts['sha256'], size=facts['size'], mime=facts['mime'], stored_name=filename,
                original_url='', width=None, height=None, duration_seconds=facts['duration_seconds'],
                notes=note)
    return service.save(client, 'assets', RecordInput(name=name[:160], project_id=parent['project_id'],
                                                     campaign_id=parent['campaign_id'], data=data))


def render(client, project_id, task):
    from video_ffmpeg import ffmpeg, probe, Cancelled as MediaCancelled
    project = service.get(client, project_id, 'audio-projects')
    d = project['data']
    parent, path = source(client, d['asset_id'])
    meta = probe(path)
    if not meta['has_audio'] or not 0 < meta['duration'] <= 3600:
        raise ValueError('Source must have audio and last at most one hour')
    end = d['end_seconds'] if d['end_seconds'] is not None else meta['duration']
    if end > meta['duration'] + .01 or d['start_seconds'] >= meta['duration']:
        raise ValueError('Trim range exceeds the source duration')
    if (end - d['start_seconds']) * 192000 + 4096 > assets.MAX_ASSET:
        raise ValueError('PCM output would exceed 256 MB; choose a shorter trim range')
    task.check()
    task.update(state='running', stage='Rendering private PCM audio')
    with tempfile.TemporaryDirectory(prefix='audio-', dir=repository.home / 'work') as folder:
        output = Path(folder) / 'render.wav'
        filters = []
        if d['normalize']:
            filters.append('loudnorm=I=-16:TP=-1.5:LRA=11')
        if d['gain_db']:
            filters.append('volume=' + str(d['gain_db']) + 'dB')
        args = ['-protocol_whitelist', 'file,pipe', '-ss', str(d['start_seconds']), '-i', str(path),
                '-t', str(end - d['start_seconds']), '-vn', '-map', '0:a:0']
        if filters:
            args += ['-af', ','.join(filters)]
        args += ['-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', '-fs', str(256 * 1024 ** 2), str(output)]
        try:
            ffmpeg(args, task, timeout=300)
        except MediaCancelled:
            task.check()
            raise
        task.check()
        return private_asset(client, output, project['name'] + ' · audio', parent,
                             f'FFmpeg render from {parent["id"]} v{parent["version"]}; audio project {project_id} v{project["version"]}. '
                             'Single-pass loudnorm is a processing target, not a verified loudness measurement.')


def captions(data, format):
    def stamp(seconds):
        ms = round(seconds * 1000)
        hours, ms = divmod(ms, 3600000)
        minutes, ms = divmod(ms, 60000)
        secs, ms = divmod(ms, 1000)
        return f'{hours:02}:{minutes:02}:{secs:02}{"," if format == "srt" else "."}{ms:03}'
    lines = ['WEBVTT', ''] if format == 'vtt' else []
    for i, cue in enumerate(data['cues'], 1):
        text = cue['text'].replace('\n\n', '\n')
        # WebVTT treats tags as markup: encode all operator text as literal text.
        if format == 'vtt':
            text = escape(text)
        lines.extend([str(i), stamp(cue['start_seconds']) + ' --> ' + stamp(cue['end_seconds']), text, ''])
    return '\n'.join(lines)


def transcribe(client, asset_id, language, task):
    from video_ffmpeg import probe, stop_process
    if not capabilities()['asr']['available']:
        raise ValueError('Local Whisper runtime and weights must be explicitly installed first')
    item, path = source(client, asset_id)
    meta = probe(path)
    if not meta['has_audio'] or not 0 < meta['duration'] <= 1800:
        raise ValueError('Transcription accepts audio/video up to 30 minutes')
    task.update(state='running', stage='Transcribing locally on CPU')
    model = str(Path(os.environ['AGENCY_ASR_MODEL_DIR']).resolve())
    with tempfile.TemporaryDirectory(prefix='asr-', dir=repository.home / 'work') as folder:
        output = Path(folder) / 'transcript.json'
        args = [sys.executable, str(Path(__file__).with_name('asr_worker.py')), model, str(path), str(output), language]
        with (Path(folder) / 'diagnostics.log').open('wb') as log:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, shell=False,
                                       start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            start = time.monotonic()
            try:
                while process.poll() is None:
                    task.check()
                    if time.monotonic() - start > 600:
                        raise ValueError('Local transcription exceeded ten minutes')
                    time.sleep(.1)
                task.check()
                if process.returncode or not output.is_file() or output.stat().st_size > 2 * 1024 ** 2:
                    raise ValueError('Local transcription failed; check the installed model/runtime')
            finally:
                if process.poll() is None:
                    stop_process(process)
        data = Subtitles(asset_id=asset_id, language=language, cues=json.loads(output.read_text(encoding='utf-8')),
                         timing_origin='local-asr', reviewed=False, notes='Local faster-whisper CPU int8 draft. Check words and timings against the source.').model_dump(mode='json')
        return service.save(client, 'subtitles', RecordInput(name=item['name'][:130] + ' · transcript',
                            project_id=item['project_id'], campaign_id=item['campaign_id'], data=data), file_change=True)
