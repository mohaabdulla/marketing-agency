"""Scene-aware lighting correction: measure, propose conservatively, verify on real pixels.

Everything is deterministic FFmpeg/OpenCV. This is a correction pass in the existing Rec.709
SDR path, not colour management, ACES or a LUT pipeline. A proposal is kept only if rendering
it on a real frame keeps the face natural and does not clip the highlights further.
"""
import tempfile
from pathlib import Path

GRADE_FIELDS = ('exposure', 'gamma', 'shadows', 'highlights', 'temperature', 'vignette', 'sharpen', 'denoise')
NEUTRAL = dict(exposure=0.0, gamma=1.0, shadows=0.0, highlights=0.0, temperature=0.0, vignette=0.0, sharpen=0.0, denoise=0.0)


def filters(clip, face=None):
    """FFmpeg filters for the grade values on a clip (a Clip model or a dict). Empty when neutral."""
    get = (lambda key: clip.get(key, NEUTRAL[key])) if isinstance(clip, dict) else (lambda key: getattr(clip, key, NEUTRAL[key]))
    chain = []
    if get('denoise') > 0:
        strength = 1.5 + 4.5 * get('denoise')
        chain.append(f'hqdn3d={strength:.2f}:{strength * .75:.2f}:{strength * 1.5:.2f}:{strength * 1.1:.2f}')
    if get('exposure'):
        chain.append(f'exposure=exposure={get("exposure"):.3f}')
    if get('shadows') or get('highlights'):
        # One master curve: lift the lower quarter and/or pull down the upper quarter.
        low = min(0.42, 0.25 + 0.15 * get('shadows'))
        high = max(0.58, 0.75 - 0.12 * get('highlights'))
        chain.append(f"curves=master='0/0 0.25/{low:.4f} 0.75/{high:.4f} 1/1'")
    if get('gamma') != 1:
        chain.append(f'eq=gamma={get("gamma"):.3f}')
    if get('temperature'):
        chain.append(f'colortemperature=temperature={6500 - 2500 * get("temperature"):.0f}:mix=0.6')
    if get('sharpen') > 0:
        chain.append(f'unsharp=5:5:{0.3 + 0.9 * get("sharpen"):.2f}:5:5:0')
    if get('vignette') > 0:
        # Centred on the frame: FFmpeg's vignette clips to black when its centre is moved far off-centre.
        chain.append(f"vignette=angle={0.12 + 0.5 * get('vignette'):.3f}")
    return chain


def light_stats(frame_bgr, face=None):
    """Measured luminance facts of one frame (values 0..1). Face fields are None without a face box."""
    import cv2
    import numpy as np
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype('float32') / 255.0
    height, width = gray.shape
    stats = dict(mean_luma=round(float(gray.mean()), 4), p05=round(float(np.percentile(gray, 5)), 4), p95=round(float(np.percentile(gray, 95)), 4),
                 clipped_highlights=round(float((gray >= 0.98).mean()), 4), crushed_shadows=round(float((gray <= 0.03).mean()), 4),
                 contrast=round(float(gray.std()), 4), face_luma=None, face_hue=None, face_saturation=None, background_luma=None,
                 backlight_difference=None)
    if face:
        # Inner part of the face box, away from hair and background.
        x0, x1 = int((face['x'] + face['width'] * .2) * width), int((face['x'] + face['width'] * .8) * width)
        y0, y1 = int((face['y'] + face['height'] * .2) * height), int((face['y'] + face['height'] * .85) * height)
        if x1 - x0 > 4 and y1 - y0 > 4:
            region = frame_bgr[y0:y1, x0:x1]
            hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype('float32')
            angles = hsv[:, :, 0] * (2 * np.pi / 180)
            hue = float(np.degrees(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())) % 360)
            mask = np.ones(gray.shape, bool)
            mask[max(0, int(face['y'] * height) - 10):, max(0, int((face['x'] - face['width']) * width)):int((face['x'] + 2 * face['width']) * width)] = False
            background = float(gray[mask].mean()) if mask.any() else None
            stats.update(face_luma=round(float(gray[y0:y1, x0:x1].mean()), 4), face_hue=round(hue, 1),
                         face_saturation=round(float(hsv[:, :, 1].mean() / 255), 4),
                         background_luma=round(background, 4) if background is not None else None)
            if background is not None:
                stats['backlight_difference'] = round(background - stats['face_luma'], 4)
    return stats


def diagnose(stats):
    """Plain findings from the measured stats."""
    findings = []
    if stats['backlight_difference'] is not None and stats['backlight_difference'] > 0.15 and stats['face_luma'] < 0.5:
        findings.append(dict(code='backlit_subject', message=f"The background is brighter than the face (face {stats['face_luma']:.2f}, background {stats['background_luma']:.2f})."))
    if stats['face_luma'] is not None and stats['face_luma'] < 0.33:
        findings.append(dict(code='dark_face', message=f"The face is dark (mean luminance {stats['face_luma']:.2f})."))
    if stats['clipped_highlights'] > 0.03:
        findings.append(dict(code='clipped_highlights', message=f"{stats['clipped_highlights']:.0%} of the frame is clipped white (windows or lights)."))
    if stats['crushed_shadows'] > 0.05:
        findings.append(dict(code='crushed_shadows', message=f"{stats['crushed_shadows']:.0%} of the frame is crushed black."))
    if stats['contrast'] < 0.12:
        findings.append(dict(code='low_contrast', message=f"Low overall contrast (luminance spread {stats['contrast']:.2f})."))
    return findings


def propose(stats, strength=1.0):
    """Conservative grade from the findings; `strength` scales it (style profile or retry)."""
    grade = dict(NEUTRAL)
    codes = {f['code'] for f in diagnose(stats)}
    face = stats['face_luma']
    if 'backlit_subject' in codes or 'dark_face' in codes:
        # Lift the midtones where the face sits (gamma) and open the shadows; the highlight
        # roll-off below keeps the bright window from clipping as a result.
        need = max(0.0, 0.52 - face) if face is not None else 0.08
        grade['gamma'] = round(1 + min(0.24, need * 2.2) * strength, 3)
        grade['shadows'] = round(min(0.5, need * 2.0) * strength, 3)
    elif 'crushed_shadows' in codes:
        grade['shadows'] = round(0.3 * strength, 3)
    if 'clipped_highlights' in codes or 'backlit_subject' in codes:
        grade['highlights'] = round(min(0.7, 0.35 + stats['clipped_highlights'] * 3) * strength, 3)
    return grade


def is_neutral(grade):
    return all(abs(grade.get(key, NEUTRAL[key]) - NEUTRAL[key]) < 1e-6 for key in GRADE_FIELDS)


def apply_to_frame(source, seconds, grade, face=None):
    """Render one graded frame of the source with FFmpeg (the same filters the export uses)."""
    import cv2
    from video_ffmpeg import ffmpeg
    from video_storage import DATA
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='grade-') as tmp:
        out = Path(tmp) / 'frame.png'
        chain = filters(grade, face) or ['null']
        ffmpeg(['-ss', f'{max(0.0, seconds):.3f}', '-protocol_whitelist', 'file,pipe', '-i', str(source), '-frames:v', '1', '-vf', ','.join(chain), str(out)], timeout=60)
        return cv2.imread(str(out))


def hue_difference(a, b):
    return abs((a - b + 180) % 360 - 180)


def verify(before, after):
    """Compare measured stats before/after a grade. Returns (ok, reasons, changes)."""
    reasons = []
    changes = dict(face_luma=None, face_hue_shift=None, clipped_highlights=round(after['clipped_highlights'] - before['clipped_highlights'], 4),
                   mean_luma=round(after['mean_luma'] - before['mean_luma'], 4))
    if after['clipped_highlights'] > before['clipped_highlights'] + 0.01:
        reasons.append(f"clipped highlights would rise from {before['clipped_highlights']:.1%} to {after['clipped_highlights']:.1%}")
    if after['crushed_shadows'] > before['crushed_shadows'] + 0.02:
        reasons.append(f"crushed shadows would rise from {before['crushed_shadows']:.1%} to {after['crushed_shadows']:.1%}")
    if before['face_luma'] is not None and after['face_luma'] is not None:
        changes['face_luma'] = round(after['face_luma'] - before['face_luma'], 4)
        changes['face_hue_shift'] = round(hue_difference(after['face_hue'], before['face_hue']), 1)
        if changes['face_hue_shift'] > 8:
            reasons.append(f"skin hue would shift {changes['face_hue_shift']:.0f}°")
        if after['face_luma'] > 0.72:
            reasons.append(f"the face would become too bright ({after['face_luma']:.2f})")
        if after['face_saturation'] > before['face_saturation'] * 1.35 + 0.02:
            reasons.append('skin saturation would rise sharply')
    return not reasons, reasons, changes


def scene_correction(source, seconds, face=None, strength=1.0):
    """Measure a representative frame, propose a grade and keep the strongest version that passes
    the pixel check. Returns a report; `grade` is neutral when nothing is needed or nothing passed."""
    from video_measure import frame_at
    frame = frame_at(source, seconds)
    if frame is None:
        return dict(status='NOT_MEASURED', reason='A representative frame could not be decoded (OpenCV unavailable).', grade=dict(NEUTRAL))
    before = light_stats(frame, face)
    findings = diagnose(before)
    report = dict(status='NO_CORRECTION_NEEDED', measured_at=round(seconds, 2), before=before, findings=findings, grade=dict(NEUTRAL),
                  face_measured=face is not None, attempts=[])
    if not findings:
        report['reason'] = 'Measured exposure, highlights, shadows and contrast are within normal ranges.'
        return report
    for factor in (1.0, 0.6, 0.35):
        grade = propose(before, strength * factor)
        if is_neutral(grade):
            break
        after = light_stats(apply_to_frame(source, seconds, grade, face), face)
        ok, reasons, changes = verify(before, after)
        report['attempts'].append(dict(strength=round(strength * factor, 2), grade=grade, accepted=ok, rejected_because=reasons))
        if ok:
            report.update(status='CORRECTED', grade=grade, after=after, changes=changes)
            return report
    report.update(status='REJECTED', reason='Every tested correction changed skin or highlights too much, so none was applied.')
    return report
