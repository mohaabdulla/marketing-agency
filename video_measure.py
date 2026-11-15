"""Measurements taken from the actual media. Nothing here returns a default in place of a
measurement: a value that could not be measured is None and callers must treat it as unknown.

Loudness and true peak use FFmpeg's ebur128 filter, an implementation of ITU-R BS.1770.
"""
import re
from pathlib import Path
from video_ffmpeg import run


def audio_quality(path, job=None):
    """Local signal indicators, not a speech-intelligibility or source-separation score.

    The quiet-block level is an estimate: speech and music may contaminate it. A narrow
    50/60 Hz spectral spike is only a possible mains hum, never a confirmed diagnosis.
    """
    import hashlib
    import json
    import tempfile
    import wave
    import numpy as np
    from video_storage import DATA, atomic
    from video_ffmpeg import ffmpeg, Cancelled
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    cache = DATA / 'analysis' / ('audio-v1-' + digest.hexdigest() + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='signal-') as folder:
        wav = Path(folder) / 'mono.wav'
        ffmpeg(['-i', str(path), '-map', '0:a:0', '-vn', '-t', '300', '-ac', '1', '-ar', '8000', '-c:a', 'pcm_s16le', str(wav)], job, timeout=120)
        with wave.open(str(wav)) as handle:
            samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype('float32') / 32768
    if not len(samples):
        raise ValueError('No audio samples could be decoded')
    def db(value):
        return round(float(20 * np.log10(max(1e-9, value))), 2)
    blocks = samples[:len(samples) // 800 * 800].reshape(-1, 800)
    rms = np.sqrt(np.mean(blocks ** 2, axis=1)) if len(blocks) else np.array([0.])
    hum = {50: [], 60: []}
    window = np.hanning(8000)
    for offset in range(0, len(samples) - 7999, 8000):
        if job and job.cancelled():
            raise Cancelled()
        power = np.abs(np.fft.rfft(samples[offset:offset + 8000] * window)) ** 2
        for frequency in hum:
            band = float(power[frequency - 1:frequency + 2].sum())
            neighbour = float(np.concatenate((power[frequency - 8:frequency - 3], power[frequency + 4:frequency + 9])).mean()) * 3
            hum[frequency].append((10 * np.log10(max(band, 1e-12) / max(neighbour, 1e-12)), band / max(float(power.sum()), 1e-12)))
    peaks = []
    for frequency, values in hum.items():
        if values:
            prominence, share = np.median(np.array(values), axis=0)
            peaks.append(dict(frequency_hz=frequency, prominence_db=round(float(prominence), 2), power_share=round(float(share), 5),
                              possible_hum=bool(prominence > 15 and share > .005)))
    result = dict(quiet_block_level_dbfs=db(float(np.percentile(rms, 10))), rms_dbfs=db(float(np.sqrt(np.mean(samples ** 2)))),
                  sample_peak_dbfs=db(float(np.max(np.abs(samples)))), near_full_scale_share=round(float((np.abs(samples) >= .999).mean()), 7),
                  hum_candidates=peaks, measurement='8 kHz mono proxy, 100 ms RMS blocks and 1 Hz spectral bins',
                  limitations='Quiet-block level is not an isolated noise floor. Hum flags require listening; dialogue intelligibility is not measured.')
    atomic(cache, result)
    return result

_NUMBER = r'(-?\d+(?:\.\d+)?|-?inf|nan)'


def _float(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float('inf') else None


def _tool(args, timeout=180, job=None):
    return run(['-hide_banner', '-nostdin', '-nostats', '-protocol_whitelist', 'file,pipe', *args], job, timeout)


def parse_loudness(log):
    """Parse the ebur128 summary block. Returns None for any figure that is absent."""
    summary = log[log.rfind('Summary:'):] if 'Summary:' in log else ''

    def find(pattern):
        match = re.search(pattern, summary)
        return _float(match.group(1)) if match else None

    return dict(integrated_lufs=find(r'I:\s+' + _NUMBER + r' LUFS'),
                loudness_range_lu=find(r'LRA:\s+' + _NUMBER + r' LU'),
                true_peak_dbtp=find(r'Peak:\s+' + _NUMBER + r' dBFS'),
                method='ITU-R BS.1770 (FFmpeg ebur128, true peak by oversampling)')


def loudness(path, job=None):
    """Integrated loudness, loudness range and true peak of the first audio stream."""
    return parse_loudness(_tool(['-i', str(path), '-map', '0:a:0', '-af', 'ebur128=peak=true', '-f', 'null', '-'], job=job))


def parse_intervals(log, start_key, end_key, until=None):
    """Pair start/end markers. An interval still open at the end of the file (FFmpeg prints no
    end marker for a picture that stays frozen to the last frame) is closed at `until`."""
    starts = [_float(x) for x in re.findall(start_key + r'[:=]\s*' + _NUMBER, log)]
    ends = [_float(x) for x in re.findall(end_key + r'[:=]\s*' + _NUMBER, log)]
    if until is not None and len(starts) == len(ends) + 1:
        ends.append(until)
    return [dict(start=round(a, 3), end=round(b, 3), duration=round(b - a, 3))
            for a, b in zip(starts, ends) if a is not None and b is not None and b > a]


def black_and_frozen(path, job=None):
    """Black intervals (>=0.25 s, nearly all pixels dark) and frozen-picture intervals (>=1.5 s)."""
    log = _tool(['-i', str(path), '-map', '0:v:0', '-vf', 'blackdetect=d=0.25:pic_th=0.98:pix_th=0.10,freezedetect=n=0.003:d=1.5',
                 '-an', '-f', 'null', '-'], job=job)
    from video_ffmpeg import probe
    duration = probe(path)['duration']
    return dict(black=parse_intervals(log, 'black_start', 'black_end', duration),
                frozen=parse_intervals(log, r'freeze_start', r'freeze_end', duration))


def frame_at(path, seconds):
    """One decoded frame (BGR ndarray) or None. OpenCV is optional."""
    try:
        import cv2
    except ImportError:
        return None
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000)
        ok, frame = capture.read()
        return frame if ok else None
    finally:
        capture.release()


def visual_profile(path, shots, sample_fps=4.0, job=None):
    """Per-shot motion, sharpness and face framing from decoded frames.

    motion_mean_abs_diff: mean absolute luma change between consecutive sampled frames (0..1).
    motion_score: that value scaled so 0.06 (a busy handheld or fast-moving shot) maps to 1.0.
    sharpness_laplacian_var: variance of the Laplacian of the shot's middle frame (higher = sharper).
    face: largest frontal face found by OpenCV's Haar cascade in the middle frame, with headroom
    and horizontal centring as fractions of the frame; None when no face was found.
    Returns None when OpenCV is unavailable so callers record these fields as not measured.
    """
    try:
        import cv2
    except ImportError:
        return None
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'))
    results = []
    try:
        for shot in shots:
            start, end = shot['start'], shot['end']
            step = max(1.0 / sample_fps, (end - start) / 240)       # at most 240 samples per shot
            previous, diffs, t = None, [], start
            while t < end - 1e-3:
                if job and job.cancelled():
                    from video_ffmpeg import Cancelled
                    raise Cancelled()
                capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, frame = capture.read()
                if not ok:
                    break
                gray = cv2.cvtColor(cv2.resize(frame, (160, max(2, round(160 * frame.shape[0] / frame.shape[1])))), cv2.COLOR_BGR2GRAY)
                if previous is not None:
                    diffs.append(float(cv2.absdiff(gray, previous).mean()) / 255.0)
                previous = gray
                t += step
            entry = dict(motion_mean_abs_diff=None, motion_score=None, sharpness_laplacian_var=None, face=None, frames_sampled=len(diffs) + (1 if previous is not None else 0))
            if diffs:
                mean = sum(diffs) / len(diffs)
                entry.update(motion_mean_abs_diff=round(mean, 5), motion_score=round(min(1.0, mean / 0.06), 3))
            capture.set(cv2.CAP_PROP_POS_MSEC, (start + end) / 2 * 1000)
            ok, frame = capture.read()
            if ok:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                entry['sharpness_laplacian_var'] = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2)
                height, width = gray.shape
                # A Haar hit in one frame is often a tie or a window; keep only a box that
                # reappears at about the same place in at least two sampled frames of the shot.
                # Six samples: a speaker who gestures or looks away in some frames is still found.
                votes = []
                for moment in (start + (end - start) * f for f in (0.08, 0.25, 0.4, 0.55, 0.7, 0.9)):
                    capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
                    ok, sample = capture.read()
                    if not ok or cascade.empty():
                        continue
                    found = cascade.detectMultiScale(cv2.equalizeHist(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)), scaleFactor=1.08,
                                                     minNeighbors=8, minSize=(max(24, width // 10), max(24, width // 10)))
                    votes.append([tuple(int(v) for v in f) for f in found])

                def overlap(a, b):
                    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
                    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
                    return ix * iy / float(a[2] * a[3] + b[2] * b[3] - ix * iy)

                confirmed = [box for i, boxes in enumerate(votes) for box in boxes
                             if sum(any(overlap(box, other) > 0.3 for other in others) for j, others in enumerate(votes) if j != i) >= 1]
                if confirmed:
                    x, y, w, h = max(confirmed, key=lambda f: f[2] * f[3])
                    entry['face'] = dict(x=round(x / width, 4), y=round(y / height, 4), width=round(w / width, 4), height=round(h / height, 4),
                                         headroom=round(y / height, 4), center_offset_x=round((x + w / 2) / width - 0.5, 4),
                                         detector='OpenCV Haar frontal face, confirmed in at least 2 of 6 sampled frames')
            results.append(entry)
    finally:
        capture.release()
    return results


def audio_activity(start, end, silence_segments):
    """Fraction of [start, end) that is not inside a detected silence interval."""
    span = max(1e-6, end - start)
    silent = sum(max(0.0, min(end, s['end']) - max(start, s['start'])) for s in silence_segments)
    return round(max(0.0, 1.0 - silent / span), 3)


def faststart(path):
    """True when the MP4 'moov' atom precedes 'mdat' (progressive download), None if unreadable."""
    try:
        with open(path, 'rb') as handle:
            offset, size_total = 0, Path(path).stat().st_size
            while offset < size_total:
                handle.seek(offset)
                header = handle.read(16)
                if len(header) < 8:
                    return None
                size, kind = int.from_bytes(header[:4], 'big'), header[4:8]
                if size == 1:
                    size = int.from_bytes(header[8:16], 'big')
                if kind == b'moov':
                    return True
                if kind == b'mdat':
                    return False
                if size < 8:
                    return None
                offset += size
    except OSError:
        return None
    return None


def contrast_ratio(rgb_a, rgb_b):
    """WCAG relative-luminance contrast ratio between two sRGB colours (1..21)."""
    def luminance(rgb):
        channels = []
        for value in rgb[:3]:
            c = value / 255.0
            channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    a, b = sorted((luminance(rgb_a), luminance(rgb_b)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)
