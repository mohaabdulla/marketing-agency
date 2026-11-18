"""Offline AI narration for storyboard videos.

Engines, all local and free, discovered at runtime (nothing is downloaded automatically):
  * Piper (MIT engine; each voice model carries its own licence card) - set PIPER_BIN to the piper
    executable and PIPER_VOICES to a folder of ``*.onnx`` voices with their ``.onnx.json`` configs.
    Piper publishes Arabic voices (for example ar_JO-kareem), so this is the route to Arabic narration.
  * Windows speech (System.Speech) - the voices that ship with Windows; no extra install.

Each scene's narration is recorded separately and fitted to that scene: speech starts shortly after
the cut and must end before the next one. Speech that is a little too long is sped up (at most
MAX_TEMPO); anything longer fails with a message naming the scene, because cutting a sentence off
mid-word is never acceptable in client work. There is deliberately no synthetic-tone fallback.

Every recording comes with word timings, so subtitles can follow the voice: Windows speech reports
each word as it is spoken (SpeakProgress); for Piper the words are spread over the voiced audio.
"""
import difflib
import json
import os
import re
import subprocess
import tempfile
import time
import wave
from functools import lru_cache
from pathlib import Path

from video.ffmpeg import Cancelled, ffmpeg, stop_process
from video.storage import DATA

LEAD = .2          # seconds of quiet after each cut before the narrator speaks
TAIL = .25         # seconds of quiet left before the next cut
MAX_TEMPO = 1.3    # beyond this speech sounds rushed; ask the person to shorten the line instead
TIMEOUT = 90

SAPI_LIST = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
  [pscustomobject]@{ name = $_.VoiceInfo.Name; culture = $_.VoiceInfo.Culture.Name; gender = [string]$_.VoiceInfo.Gender }
} | ConvertTo-Json -Compress
'''
# Records every line in one process and reports each word as it is spoken. SpeakProgress positions are
# computed for 16 kHz audio whatever output format is requested (measured: 24 kHz output reports times
# 1.5x too late), so lines are recorded at 16 kHz, which is also these voices' native rate.
SAPI_BATCH = r'''
param([string]$Job)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Speech.AudioFormat;
using System.Speech.Synthesis;
using System.Text;
using System.Threading;

public static class LexnisNarrator {
    public static string SpeakAll(string voice, int rate, string[] texts, string[] outputs) {
        var result = new StringBuilder();
        var words = new List<string>();
        using (var synth = new SpeechSynthesizer()) {
            synth.SelectVoice(voice);
            synth.Rate = rate;
            synth.SpeakProgress += (sender, e) => {
                lock (words) words.Add(e.AudioPosition.TotalMilliseconds.ToString("0.0", CultureInfo.InvariantCulture)
                    + "\t" + e.CharacterPosition + "\t" + e.CharacterCount);
            };
            var format = new SpeechAudioFormatInfo(16000, AudioBitsPerSample.Sixteen, AudioChannel.Mono);
            for (int i = 0; i < texts.Length; i++) {
                lock (words) words.Clear();
                synth.SetOutputToWaveFile(outputs[i], format);
                synth.Speak(texts[i]);
                synth.SetOutputToNull();
                Thread.Sleep(30);
                result.Append('#').Append(i).Append('\n');
                lock (words) foreach (var line in words) result.Append(line).Append('\n');
            }
        }
        return result.ToString();
    }
}
'@
$spec = [IO.File]::ReadAllText($Job, [Text.Encoding]::UTF8) | ConvertFrom-Json
$timings = [LexnisNarrator]::SpeakAll([string]$spec.voice, [int]$spec.rate, [string[]]@($spec.texts), [string[]]@($spec.outputs))
[IO.File]::WriteAllText([string]$spec.timings, $timings, (New-Object System.Text.UTF8Encoding $false))
'''
FRAME = .01            # voice-activity analysis step, seconds
PAUSE = .12            # silence this long ends a word early (a real pause, not the next word's onset)


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60]


def _process(args, job=None, stdin=None, timeout=TIMEOUT):
    """Run a local speech engine without a shell, honouring job cancellation and a time limit."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                   stdout=log, stderr=log, shell=False, creationflags=flags)
        if stdin is not None:
            process.stdin.write(stdin.encode('utf-8'))
            process.stdin.close()
        started = time.monotonic()
        try:
            while process.poll() is None:
                if job and job.cancelled():
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    raise ValueError('The narrator voice took too long to respond')
                time.sleep(.05)
            log.seek(0)
            output = log.read(256 * 1024).decode('utf-8', errors='replace')
            if process.returncode:
                (DATA / 'work').mkdir(parents=True, exist_ok=True)
                (DATA / 'work/last-voice-error.log').write_text(output, encoding='utf-8')
                raise ValueError('The narrator voice could not record this line; see local video diagnostics')
            return output
        finally:
            if process.poll() is None:
                stop_process(process)


def _powershell():
    root = os.environ.get('SystemRoot', r'C:\Windows')
    exe = Path(root) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return str(exe) if exe.is_file() else None


@lru_cache(maxsize=1)
def _windows_voices():
    if os.name != 'nt' or not _powershell():
        return []
    try:
        raw = _process([_powershell(), '-NoProfile', '-NonInteractive', '-Command', SAPI_LIST], timeout=30).strip()
        items = json.loads(raw) if raw else []
    except (ValueError, OSError):
        return []
    items = items if isinstance(items, list) else [items]
    voices = []
    for item in items:
        name = str(item.get('name', ''))
        short = name.replace('Microsoft ', '').replace(' Desktop', '')
        voices.append(dict(id='windows-' + _slug(short), name=f'{short} (Windows, {item.get("culture", "")})',
                           language=str(item.get('culture', '')).split('-')[0].lower(), locale=item.get('culture', ''),
                           gender=str(item.get('gender', '')).lower(), engine='windows', engine_voice=name,
                           licence='Microsoft Windows speech voice: check Microsoft terms before commercial broadcast use'))
    return voices


def _piper_voices():
    exe, folder = os.getenv('PIPER_BIN'), os.getenv('PIPER_VOICES')
    if not exe or not folder or not Path(exe).is_file() or not Path(folder).is_dir():
        return []
    voices = []
    for model in sorted(Path(folder).glob('*.onnx')):
        config = model.with_suffix('.onnx.json')
        if not config.is_file():
            continue
        try:
            meta = json.loads(config.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        code = str((meta.get('language') or {}).get('code') or model.stem.split('-')[0])
        voices.append(dict(id='piper-' + _slug(model.stem), name=f'{model.stem} (Piper)', language=code.split('_')[0].lower(),
                           locale=code.replace('_', '-'), gender='', engine='piper', engine_voice=str(model),
                           licence='See the MODEL_CARD published with this Piper voice'))
    return voices


def voices(language=None, refresh=False):
    if refresh:
        _windows_voices.cache_clear()
    found = _piper_voices() + _windows_voices()
    return [v for v in found if not language or v['language'] == language]


def public_voices(language=None):
    """Voice list for the browser; local file paths stay on the server."""
    return [{k: v for k, v in voice.items() if k != 'engine_voice'} for voice in voices(language)]


def voice(voice_id, language):
    match = next((v for v in voices() if v['id'] == voice_id), None)
    if not match:
        raise ValueError('That narrator voice is not installed on this computer')
    if match['language'] != language:
        names = {'ar': 'Arabic', 'en': 'English'}
        raise ValueError(f'The {match["name"]} voice does not speak {names.get(language, language)}; choose a matching narrator')
    return match


def wav_seconds(path):
    with wave.open(str(path), 'rb') as audio:
        return audio.getnframes() / float(audio.getframerate())


_DOMAIN = re.compile(r'\b(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,24})((?:/[^\s,;!?)]*)?)', re.I)
_EMAIL = re.compile(r'\b([\w.+-]+)@((?:[a-z0-9-]+\.)+[a-z]{2,24})\b', re.I)
SPOKEN = {
    'en': dict(dot=' dot ', slash=' slash ', at=' at ', words=[(r'\s*&\s*', ' and '), (r'(\d)\s*%', r'\1 percent'), (r'\b24/7\b', 'twenty four seven'),
                                                          (r'\bAI\b', 'A.I.'), (r'\bB2B\b', 'B to B'), (r'\bB2C\b', 'B to C'), (r'\be\.g\.', 'for example'),
                                                          (r'\bi\.e\.', 'that is'), (r'\betc\.', 'etcetera'), (r'(?<=\d)\s*\+(?=\s|$)', ' plus')]),
    'ar': dict(dot=' دوت ', slash=' سلاش ', at=' آت ', words=[(r'\s*&\s*', ' و '), (r'(\d)\s*%', r'\1 بالمئة'), (r'\b24/7\b', 'على مدار الساعة')]),
}


def spoken_text(text, language='en'):
    """Rewrite what a speech engine reads badly: web addresses, emails, symbols and common abbreviations.
    Subtitles keep the original text; only the narrator hears this version."""
    rules = SPOKEN.get(language, SPOKEN['en'])
    text = re.sub(r'\s+', ' ', text).strip()
    text = _EMAIL.sub(lambda m: m.group(1).replace('.', rules['dot']) + rules['at'] + m.group(2).replace('.', rules['dot']), text)

    def address(match):
        path = match.group(2).strip('/')
        spoken = match.group(1).replace('.', rules['dot'])
        return spoken + (rules['slash'] + path.replace('/', rules['slash']).replace('-', ' ') if path else '')
    text = _DOMAIN.sub(address, text)
    for pattern, replacement in rules['words']:
        text = re.sub(pattern, replacement, text)
    return re.sub(r'\s+', ' ', text).strip()


def fit(spoken, duration):
    """How much a recorded line must be sped up to fit its scene, and whether that is acceptable."""
    room = max(.1, duration - LEAD - TAIL)
    tempo = max(1.0, spoken / room)
    return round(tempo, 3), tempo <= MAX_TEMPO


# ------------------------------------------------------------------ word timings

def _voiced(path):
    """Per-FRAME voice-activity flags of a 16-bit WAV: energy within 35 dB of the loudest frame."""
    import numpy as np
    with wave.open(str(path), 'rb') as audio:
        rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        raw = audio.readframes(audio.getnframes())
    if width != 2:
        raise ValueError('The narrator voice wrote an unexpected audio format')
    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)
    if channels > 1:
        samples = samples[:len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    hop = max(1, int(rate * FRAME))
    count = len(samples) // hop
    if not count:
        return []
    rms = np.sqrt((samples[:count * hop].reshape(count, hop) ** 2).mean(axis=1) + 1e-9)
    level = 20 * np.log10(rms / 32768)
    return (level > max(-50.0, float(level.max()) - 35.0)).tolist()


def _speech_span(voiced, seconds):
    """First and last voiced moment, so engine silence before and after a line can be trimmed."""
    on = [i for i, flag in enumerate(voiced) if flag]
    if not on:
        raise ValueError('The narrator voice produced no audio')
    return max(0.0, on[0] * FRAME - .03), min(seconds, (on[-1] + 1) * FRAME + .05)


def _tokens(text):
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r'\S+', text)]


def _norm(token):
    return re.sub(r'[^\w]', '', token.casefold())


def _engine_starts(tokens, events, seconds):
    """Start time of each spoken token from the engine's word events (character offsets into the text).
    The engine reports a number and the words around it as one group ("120 clinics run"), with one event
    per spoken word ("one", "hundred", "twenty", ...). Inside a group, ordinary words take one event each
    in order and numbers take the spare events; with too few events, tokens are spread by position."""
    groups = []
    for moment, position, count in events:
        if not groups or (position, count) != (groups[-1]['position'], groups[-1]['count']):
            groups.append(dict(position=position, count=count, moments=[]))
        groups[-1]['moments'].append(moment)
    members = {}
    for index, (first_char, _, _) in enumerate(tokens):
        group = max((k for k, g in enumerate(groups) if g['position'] <= first_char), default=0)
        members.setdefault(group, []).append(index)
    starts = [0.0] * len(tokens)
    for group, indexes in members.items():
        moments = groups[group]['moments']
        numeric = [any(c.isdigit() for c in tokens[i][2]) for i in indexes]
        plain = len(indexes) - sum(numeric)
        if len(moments) >= len(indexes):
            per_number = (len(moments) - plain) / max(1, sum(numeric))
            cursor = 0.0
            for i, number in zip(indexes, numeric):
                starts[i] = moments[min(len(moments) - 1, int(round(cursor)))]
                cursor += per_number if number else 1
        else:
            position, count = groups[group]['position'], groups[group]['count']
            following = groups[group + 1]['moments'][0] if group + 1 < len(groups) else seconds
            for i in indexes:
                share = min(1.0, max(0.0, (tokens[i][0] - position) / max(count, 1)))
                starts[i] = moments[0] + share * max(0.0, following - moments[0])
    for k in range(1, len(starts)):
        starts[k] = max(starts[k], starts[k - 1] + .02)
    return starts


def _estimate_starts(tokens, voiced):
    """Without engine events, spread words over the voiced audio by length; pauses fall between sentences."""
    moments = [i * FRAME for i, flag in enumerate(voiced) if flag]
    weights = [len(token) + (3 if re.search(r'[.!?؟]$', token) else 1 if re.search(r'[,;:،]$', token) else 0) for _, _, token in tokens]
    total, cumulative, starts = sum(weights) or 1, 0, []
    for weight in weights:
        starts.append(moments[min(len(moments) - 1, int(cumulative / total * len(moments)))])
        cumulative += weight
    return starts


def _word_ends(starts, voiced, limit):
    """A word ends where the next begins, or earlier where the voice stops for at least PAUSE."""
    ends = []
    for index, start in enumerate(starts):
        boundary = starts[index + 1] if index + 1 < len(starts) else limit
        end, run, frame = boundary, 0, int((start + .08) / FRAME)
        while frame < min(int(boundary / FRAME), len(voiced)):
            run = run + 1 if not voiced[frame] else 0
            if run * FRAME >= PAUSE:
                end = (frame - run + 1) * FRAME
                break
            frame += 1
        ends.append(max(start + .05, min(end, boundary)))
    return ends


def word_timings(display, spoken, events, seconds, voiced):
    """The words shown on screen, each with the time it is spoken in the recording.
    Display and spoken text differ where addresses and symbols were rewritten for the voice
    ("northwind.health" -> "northwind dot health"); a token alignment maps one onto the other."""
    tokens = _tokens(spoken)
    shown = [token for _, _, token in _tokens(display)]
    if not tokens or not shown:
        return []
    if events:
        top = max(moment for moment, _, _ in events)
        if top > seconds:  # defensive: positions reported in another time base
            events = [(moment * (seconds - .05) / top, position, count) for moment, position, count in events]
        starts = _engine_starts(tokens, events, seconds)
    else:
        starts = _estimate_starts(tokens, voiced)
    ends = _word_ends(starts, voiced, _speech_span(voiced, seconds)[1])
    heard = [dict(start=round(s, 3), end=round(e, 3)) for s, e in zip(starts, ends)]
    words = [None] * len(shown)
    matcher = difflib.SequenceMatcher(None, [_norm(t) for t in shown], [_norm(t) for _, _, t in tokens], autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == 'equal':
            for k in range(a1 - a0):
                words[a0 + k] = dict(word=shown[a0 + k], **heard[b0 + k])
        elif a1 > a0:
            begin = heard[b0]['start'] if b1 > b0 else (heard[b0 - 1]['end'] if b0 else 0.0)
            finish = heard[b1 - 1]['end'] if b1 > b0 else begin + .05
            lengths = [len(shown[k]) for k in range(a0, a1)]
            cursor = begin
            for k, length in zip(range(a0, a1), lengths):
                span = (finish - begin) * length / sum(lengths)
                words[k] = dict(word=shown[k], start=round(cursor, 3), end=round(cursor + max(.02, span), 3))
                cursor += span
    return words


# ------------------------------------------------------------------ recording

def _windows_batch(texts, chosen, outputs, job):
    work = Path(outputs[0]).parent
    script, spec, timings = work / 'narrator.ps1', work / 'narrator.json', work / 'narrator-timings.txt'
    script.write_text(SAPI_BATCH, encoding='utf-8-sig')
    spec.write_text(json.dumps(dict(voice=chosen['engine_voice'], rate=0, texts=texts, outputs=[str(o) for o in outputs],
                                    timings=str(timings))), encoding='utf-8')
    _process([_powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Job', str(spec)],
             job, timeout=30 + 15 * len(texts))
    events, current = [[] for _ in texts], None
    for line in timings.read_text(encoding='utf-8').splitlines():
        if line.startswith('#'):
            current = int(line[1:])
            continue
        parts = line.split('\t')
        if current is not None and len(parts) == 3:
            events[current].append((float(parts[0]) / 1000, int(parts[1]), int(parts[2])))
    return events


def record(texts, chosen, outputs, job=None, language=None):
    """Record each line to its WAV path. Returns, per line, the path, length, voiced span and word timings."""
    language = language or chosen['language']
    spoken = [spoken_text(text, language) for text in texts]
    outputs = [Path(path) for path in outputs]
    if chosen['engine'] == 'windows':
        events = _windows_batch(spoken, chosen, outputs, job)
    elif chosen['engine'] == 'piper':
        events = []
        for text, out in zip(spoken, outputs):
            _process([os.environ['PIPER_BIN'], '--model', chosen['engine_voice'], '--output_file', str(out)], job, stdin=text)
            events.append(None)
    else:
        raise ValueError('Unsupported narrator engine')
    lines = []
    for text, said, out, heard in zip(texts, spoken, outputs, events):
        if not out.is_file() or wav_seconds(out) < .2:
            raise ValueError('The narrator voice produced no audio')
        seconds, voiced = wav_seconds(out), _voiced(out)
        lines.append(dict(path=out, seconds=seconds, speech=_speech_span(voiced, seconds), spoken_text=said,
                          words=word_timings(text, said, heard, seconds, voiced)))
    return lines


def speak(text, chosen, out, job=None, language=None):
    """Record one line with a local engine to a WAV file."""
    return record([text], chosen, [out], job, language)[0]['path']


def preview(text, voice_id, language, duration=None):
    """Record one line for the person to hear before approving; nothing is stored."""
    import base64
    chosen = voice(voice_id, language)
    (DATA / 'work').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='voice-preview-') as work:
        line = record([text], chosen, [Path(work) / 'preview.wav'], language=language)[0]
        spoken = line['speech'][1] - line['speech'][0]
        data = line['path'].read_bytes()
    result = dict(audio='data:audio/wav;base64,' + base64.b64encode(data).decode('ascii'), voice=chosen['name'],
                  spoken_seconds=round(spoken, 2), heard_as=line['spoken_text'])
    if duration:
        tempo, ok = fit(spoken, duration)
        result.update(needed_tempo=tempo, fits=ok, message=(
            'Fits the scene.' if tempo <= 1.001 else f'Will be read {round((tempo - 1) * 100)}% faster to fit the scene.' if ok
            else f'Too long: it takes about {spoken:.1f} seconds to say, but the scene is {duration:g} seconds. Shorten it or give the scene more time.'))
    return result


def fit_timings(texts, durations, language, voice_id):
    """Scene lengths that follow the narration: each line gets the time it needs to be said at a natural
    pace, and the remaining time is shared out in proportion, keeping the video's total length."""
    chosen = voice(voice_id, language)
    total = round(sum(durations), 3)
    (DATA / 'work').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='voice-fit-') as work:
        lines = record(texts, chosen, [Path(work) / f'fit-{i}.wav' for i in range(len(texts))], language=language)
    spoken = [line['speech'][1] - line['speech'][0] for line in lines]
    natural = [max(2.0, s + LEAD + TAIL + .15) for s in spoken]
    minimum = [max(2.0, s / MAX_TEMPO + LEAD + TAIL) for s in spoken]
    if sum(minimum) > total + .01:
        raise ValueError(f'The narration needs at least {sum(minimum):.1f} seconds, but the video is {total:g} seconds. '
                         'Shorten the narration or make the video longer.')
    if sum(natural) <= total:
        proposed = [n + (total - sum(natural)) * n / sum(natural) for n in natural]
    else:
        squeeze = (sum(natural) - total) / (sum(natural) - sum(minimum))
        proposed = [n - squeeze * (n - m) for n, m in zip(natural, minimum)]
    rounded = [round(p, 1) for p in proposed]
    largest = max(range(len(rounded)), key=lambda k: rounded[k])
    rounded[largest] = round(rounded[largest] + total - sum(rounded), 3)
    return dict(durations=rounded, spoken_seconds=[round(s, 2) for s in spoken], total=total, voice=chosen['name'],
                note='Lengths follow how long each line takes to say; the total stays the same. Review the timing before rendering.')


def narrate(scenes, language, voice_id, total, work, job=None):
    """Record and place every scene's narration on one track that is exactly ``total`` seconds long.
    The report carries every word's time on that track, for subtitles that follow the voice."""
    chosen = voice(voice_id, language)
    work = Path(work)
    if job:
        job.update(state='running', phase='Recording AI narration', progress={'completed_scenes': 0, 'total_scenes': len(scenes)})
    lines = record([scene['voiceover'] for scene in scenes], chosen, [work / f'narration-{i}.wav' for i in range(len(scenes))], job, language)
    if job and job.cancelled():
        raise Cancelled()
    placed, words = [], []
    for index, (scene, line) in enumerate(zip(scenes, lines)):
        begin, finish = line['speech']
        spoken = finish - begin
        tempo, ok = fit(spoken, scene['duration'])
        if not ok:
            raise ValueError(f'Scene {index + 1} narration takes about {spoken:.1f} seconds to say, but the scene is '
                             f'{scene["duration"]:g} seconds long. Shorten the narration or give the scene more time.')
        start = round(scene['start'] + LEAD, 3)
        end = round(start + spoken / tempo, 3)
        placed.append(dict(scene=index + 1, path=line['path'], trim=[round(begin, 3), round(finish, 3)], start=start, tempo=round(tempo, 3),
                           end=end, recorded_seconds=round(spoken, 2)))
        for word in line['words']:
            at = lambda moment: round(min(end, max(start, start + (moment - begin) / tempo)), 3)
            words.append(dict(word=word['word'], start=at(word['start']), end=at(word['end']), scene=index + 1))
    args, chains = [], []
    for n, part in enumerate(placed):
        args += ['-i', str(part['path'])]
        speed = f'atempo={part["tempo"]:.3f},' if part['tempo'] > 1.001 else ''
        chains.append(f'[{n}:a]atrim=start={part["trim"][0]}:end={part["trim"][1]},asetpts=PTS-STARTPTS,aresample=48000,'
                      f'aformat=channel_layouts=mono,{speed}adelay={int(part["start"] * 1000)}:all=1[v{n}]')
    mix = ''.join(f'[v{n}]' for n in range(len(placed)))
    chains.append(f'{mix}amix=inputs={len(placed)}:normalize=0:duration=longest,apad=whole_dur={total},atrim=0:{total}[out]')
    out = work / 'ai-narration.wav'
    ffmpeg([*args, '-filter_complex', ';'.join(chains), '-map', '[out]', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(out)], job, timeout=120)
    report = dict(voice_id=chosen['id'], voice=chosen['name'], engine=chosen['engine'], licence=chosen['licence'],
                  lead_seconds=LEAD, scenes=[{k: v for k, v in part.items() if k != 'path'} for part in placed], words=words,
                  word_timing='engine word events' if chosen['engine'] == 'windows' else 'estimated from the voiced audio')
    return out, report
