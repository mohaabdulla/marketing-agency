"""Post-render validation: reopen the exported file, measure it, and compare it with the plan.

Every check has one of four results. NOT_CHECKED is never turned into PASS, and a check only
says PASS when the value was read or measured from the rendered file itself.
"""
import hashlib
import tempfile
from pathlib import Path
from video.storage import DATA, read
from video.assets import path_for, ingest, annotate
from video.ffmpeg import ffmpeg, probe
from video.presets import preset, audio_encode_args, REC709
from video import measure as video_measure

PASS, WARNING, FAIL, NOT_CHECKED = 'PASS', 'WARNING', 'FAIL', 'NOT_CHECKED'


def _check(checks, key, label, status, measured=None, expected=None, detail=''):
    checks.append(dict(id=key, label=label, status=status, measured=measured, expected=expected, detail=detail))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _match(frame_gray, expected_rgba, left, top):
    """Pearson correlation between an expected overlay and the frame, over the overlay's opaque pixels."""
    import numpy as np
    height, width = expected_rgba.shape[:2]
    if left < 0 or top < 0 or top + height > frame_gray.shape[0] or left + width > frame_gray.shape[1]:
        return None
    region = frame_gray[top:top + height, left:left + width].astype('float64')
    mask = expected_rgba[:, :, 3] > 200
    if mask.sum() < 50:
        return None
    rgb = expected_rgba[:, :, :3].astype('float64')
    gray = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    a, b = gray[mask], region[mask]
    if a.std() < 1e-6 or b.std() < 1e-6:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _logo_check(checks, output, project, width, height):
    logos = [c for c in project.clips if c.kind == 'overlay']
    required = bool(logos)
    if not required:
        _check(checks, 'logo_visible', 'Logo visible in rendered frames', NOT_CHECKED, detail='The timeline has no logo overlay.')
        return
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        _check(checks, 'logo_visible', 'Logo visible in rendered frames', NOT_CHECKED, detail='OpenCV is not installed.')
        return
    clip = logos[0]
    with Image.open(path_for(clip.asset_id)).convert('RGBA') as logo:
        if clip.logo_backplate:           # same plate the renderer draws
            pad = max(8, round(logo.width * .05))
            plate = Image.new('RGBA', (logo.width + pad * 2, logo.height + pad * 2), (7, 17, 28, 215))
            plate.alpha_composite(logo, (pad, pad))
            logo = plate
        target_w = max(2, round(width * clip.scale / 2) * 2)
        target_h = max(2, round(logo.height * target_w / logo.width / 2) * 2)
        expected = np.array(logo.resize((target_w, target_h), Image.LANCZOS))
    left, top = round((width - target_w) * clip.x), round((height - target_h) * clip.y)
    frame = video_measure.frame_at(output, clip.start + min(clip.duration / 2, 1.5))
    if frame is None:
        _check(checks, 'logo_visible', 'Logo visible in rendered frames', NOT_CHECKED, detail='A rendered frame could not be decoded.')
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = max((score for dx in (-2, 0, 2) for dy in (-2, 0, 2)
                if (score := _match(gray, expected, left + dx, top + dy)) is not None), default=None)
    margin = min(left, top, width - left - target_w, height - top - target_h) / max(width, height)
    box = dict(x=left, y=top, width=target_w, height=target_h)
    if best is None:
        _check(checks, 'logo_visible', 'Logo visible in rendered frames', NOT_CHECKED, measured=box, detail='The logo region could not be compared.')
    else:
        _check(checks, 'logo_visible', 'Logo visible in rendered frames', PASS if best >= 0.6 else WARNING if best >= 0.3 else FAIL,
               measured=dict(correlation=round(best, 3), box=box), expected='correlation ≥ 0.6 with the logo artwork at its planned position',
               detail='Compared the rendered frame with the logo artwork at the planned position.')
    _check(checks, 'logo_safe_zone', 'Logo inside the edge safe margin', PASS if margin >= 0.02 else WARNING,
           measured=round(margin, 4), expected='≥ 2% of the longer side from every edge')
    stretched = abs((target_w / target_h) - (logo.width / logo.height)) / (logo.width / logo.height)
    _check(checks, 'logo_aspect', 'Logo aspect ratio preserved', PASS if stretched < 0.03 else FAIL, measured=round(stretched, 4), expected='< 3% distortion')


def _caption_checks(checks, output, project, width, height, captions_requested):
    from video.captions import render_caption_image, caption_qa, track_style, cue_style
    tracks = [t for t in getattr(project, 'caption_tracks', []) if t.get('burn_in', True) and t.get('segments') and t.get('kind', 'captions') == 'captions']
    if not tracks:
        _check(checks, 'captions_present', 'Captions rendered', FAIL if captions_requested else NOT_CHECKED,
               detail='Captions were requested but none were created (speech recognition unavailable or no speech found). Import a reviewed SRT or install the local speech model.'
               if captions_requested else 'Captions were not requested.')
        return
    track = tracks[0]
    style = track_style(track)
    issues, stats = caption_qa(track['segments'], style, width, height,max_cps=track.get('max_cps',20),track=track)
    worst = FAIL if any(i['severity'] == FAIL for i in issues) else WARNING if issues else PASS
    _check(checks, 'caption_readability', 'Caption timing, reading speed, line count and safe margins', worst, measured=stats,
           expected='≤ 20 characters/second, ≥ 0.7 s per cue, no overlap, no truncated lines, inside safe margins',
           detail='; '.join(i['message'] for i in issues[:8]) or 'All cues are within the configured readability guidelines.')
    if track.get('reviewed', False):
        _check(checks, 'caption_review', 'Recognised captions reviewed by a person', PASS, detail='Marked as reviewed by the operator.')
    elif track.get('source') == 'whisper':
        _check(checks, 'caption_review', 'Recognised captions reviewed by a person', WARNING,
               detail='These captions come from local speech recognition and have not been reviewed. Names and uncommon words are often misheard.')
    try:
        import cv2
        import numpy as np
    except ImportError:
        _check(checks, 'captions_visible', 'Captions visible in rendered frames', NOT_CHECKED, detail='OpenCV is not installed.')
        return
    scores, ratios = [], []
    segments = track['segments']
    for seg in [segments[i] for i in sorted({0, len(segments) // 2, len(segments) - 1})]:
        style=cue_style(track,seg)
        frame = video_measure.frame_at(output, (seg['start'] + seg['end']) / 2)
        if frame is None:
            continue
        image = render_caption_image(seg['text'].strip(), width, height, style)
        box = [max(0, int(v)) for v in image.info['caption_layout']['box']]
        expected = np.array(image)[box[1]:box[3], box[0]:box[2]]
        score = _match(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), expected, box[0], box[1])
        if score is not None:
            scores.append(score)
        # Contrast measured in the rendered frame: text pixels against the pixels around them in the caption box.
        region = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)[box[1]:box[3], box[0]:box[2]]
        rgba = expected
        fill = tuple(int(style.fill[i:i + 2], 16) for i in (1, 3, 5))
        text_mask = (np.abs(rgba[:, :, :3].astype(int) - np.array(fill)).sum(axis=2) < 60) & (rgba[:, :, 3] > 200)
        around = ~text_mask
        if text_mask.sum() > 20 and around.sum() > 20 and region.shape[:2] == text_mask.shape:
            ratios.append(video_measure.contrast_ratio(np.median(region[text_mask], axis=0), np.median(region[around], axis=0)))
    if scores:
        best = sum(scores) / len(scores)
        _check(checks, 'captions_visible', 'Captions visible in rendered frames', PASS if best >= 0.5 else WARNING if best >= 0.25 else FAIL,
               measured=dict(mean_correlation=round(best, 3), frames=len(scores)), expected='the caption artwork appears at its planned position',
               detail='Sampled frames at the middle of the first, middle and last cue.')
    else:
        _check(checks, 'captions_visible', 'Captions visible in rendered frames', NOT_CHECKED, detail='Caption frames could not be compared.')
    if ratios:
        low = min(ratios)
        _check(checks, 'caption_contrast', 'Caption text contrast (readability benchmark)', PASS if low >= 4.5 else WARNING if low >= 3 else FAIL,
               measured=dict(minimum_ratio=low, frames=len(ratios)), expected='≥ 4.5:1',
               detail='Contrast ratio measured in rendered frames using the WCAG formula as a readability benchmark; this is not a WCAG certification of the video.')
    else:
        _check(checks, 'caption_contrast', 'Caption text contrast (readability benchmark)', NOT_CHECKED, detail='Text pixels could not be isolated in the sampled frames.')


def _designed_graphics_checks(checks,output,project,width,height):
    import cv2
    import numpy as np
    from video.captions import CaptionStyle,render_caption_image,cue_style
    artwork=[]
    for clip in project.clips:
        if clip.kind=='title' and clip.graphic_style:
            style=CaptionStyle.model_validate({k:v for k,v in clip.graphic_style.items() if k not in {'canvas_width','canvas_height'}})
            artwork.append((clip.text_role,clip.text,clip.start,clip.start+clip.duration,style))
    for track in project.caption_tracks:
        if track.get('kind')=='lower-third':
            artwork += [('lower-third',s['text'],s['start'],s['end'],cue_style(track,s)) for s in track.get('segments',[])]
    for index,(role,text,start,end,style) in enumerate(artwork[:8]):
        image=render_caption_image(text,width,height,style)
        box=image.info['caption_layout']['box'];x0,y0,x1,y1=[max(0,round(v)) for v in box]
        frame=video_measure.frame_at(output,(start+end)/2)
        if frame is None:continue
        score=_match(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),np.array(image)[y0:y1,x0:x1],x0,y0)
        _check(checks,f'graphic_visible_{index}',f'{role.replace("_"," ").title()} visible at the designed position',
               PASS if score is not None and score>=.5 else WARNING if score is None else FAIL,
               measured=dict(correlation=round(score,3) if score is not None else None,box=box),
               detail='Measured against the actual rendered pixels at the center of the graphic display interval.')
        expected=np.array(image)[y0:y1,x0:x1]
        region=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)[y0:y1,x0:x1]
        fill=np.array([int(style.fill[i:i+2],16) for i in (1,3,5)])
        text_mask=(np.abs(expected[:,:,:3].astype(int)-fill).sum(axis=2)<45)&(expected[:,:,3]>220)
        around=(expected[:,:,3]>100)&~text_mask
        if text_mask.sum()>15 and around.sum()>15:
            ratio=video_measure.contrast_ratio(np.median(region[text_mask],axis=0),np.median(region[around],axis=0))
            _check(checks,f'graphic_contrast_{index}',f'{role.replace("_"," ").title()} readable contrast',PASS if ratio>=4.5 else WARNING if ratio>=3 else FAIL,
                   measured=ratio,expected='at least 4.5:1 as a readability benchmark',detail='Measured text and surrounding plate pixels from the actual export; not a formal accessibility certification.')


def validate(output_asset, project, *, source_asset=None, source_sha_before=None, cuts=None, captions_requested=None, audio_expected=True):
    """Measure the rendered file and compare it with the timeline, preset and source."""
    from video.editor import primary_layout
    checks = []
    spec = preset(project.delivery_preset)
    output = path_for(output_asset['id'])
    try:
        meta = probe(output)
    except Exception:
        _check(checks, 'readable', 'Exported file opens and decodes', FAIL, detail='ffprobe could not read the file.')
        return _summary(checks, spec, None, None)
    _check(checks, 'readable', 'Exported file opens and decodes', PASS, measured=f'{meta["duration"]:.3f}s')
    planned = primary_layout(project)[1]
    drift = abs(meta['duration'] - planned)
    _check(checks, 'duration', 'Duration matches the approved timeline', PASS if drift <= 0.15 else FAIL,
           measured=round(meta['duration'], 3), expected=round(planned, 3), detail=f'{drift:.3f}s difference')
    size_ok = (meta['width'], meta['height']) == (project.canvas.width, project.canvas.height)
    _check(checks, 'dimensions', 'Frame size matches the canvas', PASS if size_ok else FAIL,
           measured=f'{meta["width"]}×{meta["height"]}', expected=f'{project.canvas.width}×{project.canvas.height}')
    expected_fps = float(project.canvas.fps)
    if project.canvas.fps_mode == 'original':
        first = next(c for c in project.clips if c.kind == 'video')
        expected_fps = read('assets', first.asset_id).get('fps') or expected_fps
    fps_ok = abs(meta['fps'] - expected_fps) <= 0.02
    _check(checks, 'frame_rate', 'Frame rate is the intended rate', PASS if fps_ok else FAIL,
           measured=dict(fps=round(meta['fps'], 4), rational=meta.get('fps_rational')), expected=round(expected_fps, 4),
           detail='Source frame rate preserved.' if project.canvas.fps_mode == 'original' else 'Fixed project frame rate.')
    frames = meta.get('frame_count')
    if frames:
        expected_frames = meta['duration'] * meta['fps']
        _check(checks, 'frame_count', 'Frame count is consistent with duration × rate', PASS if abs(frames - expected_frames) <= max(2, expected_frames * 0.02) else WARNING,
               measured=frames, expected=round(expected_frames))
    else:
        _check(checks, 'frame_count', 'Frame count is consistent with duration × rate', NOT_CHECKED, detail='The container does not report a frame count.')
    codec_ok = meta['video_codec'] == 'h264' and meta.get('video_profile') == 'High' and meta.get('pix_fmt') == 'yuv420p'
    _check(checks, 'video_codec', 'H.264 High profile, 4:2:0, progressive', PASS if codec_ok and meta.get('field_order') in (None, 'progressive') else FAIL,
           measured=f'{meta["video_codec"]} {meta.get("video_profile")} {meta.get("pix_fmt")} {meta.get("field_order") or "field order not reported"}',
           expected='h264 High yuv420p progressive')
    tags = {key: meta.get(key) for key in REC709}
    _check(checks, 'color_metadata', 'Rec.709 SDR colour tags written', PASS if tags == REC709 else FAIL, measured=tags, expected=REC709)
    if source_asset is not None:
        hdr = source_asset.get('color_transfer') in {'smpte2084', 'arib-std-b67'} or source_asset.get('color_primaries') == 'bt2020'
        _check(checks, 'hdr_source', 'Source dynamic range handled', FAIL if hdr else PASS,
               measured=dict(transfer=source_asset.get('color_transfer'), primaries=source_asset.get('color_primaries')),
               detail='The source is tagged HDR and was encoded as SDR without tone mapping; colours are not trustworthy.' if hdr
               else 'The source is SDR (or untagged) and is encoded as Rec.709 SDR.')
    fast = video_measure.faststart(output)
    _check(checks, 'faststart', 'MP4 fast start (index before media data)', NOT_CHECKED if fast is None else PASS if fast else FAIL, measured=fast)

    loud = None
    if audio_expected and meta['has_audio']:
        audio_ok = meta['audio_codec'] == 'aac' and meta.get('audio_sample_rate') == 48000 and meta.get('audio_channels') == 2
        _check(checks, 'audio_format', 'AAC-LC, 48 kHz, stereo', PASS if audio_ok else FAIL,
               measured=f'{meta["audio_codec"]} {meta.get("audio_profile")} {meta.get("audio_sample_rate")} Hz {meta.get("audio_channels")}ch', expected='aac LC 48000 Hz 2ch')
        try:
            loud = video_measure.loudness(output)
        except Exception:
            loud = None
        peak = loud and loud.get('true_peak_dbtp')
        ceiling = spec['true_peak_ceiling']
        if peak is None:
            _check(checks, 'true_peak', 'True peak under the preset ceiling', NOT_CHECKED, expected=f'≤ {ceiling} dBTP', detail='True peak could not be measured.')
        else:
            # 0.1 dB tolerance: the meter reports one decimal place.
            _check(checks, 'true_peak', 'True peak under the preset ceiling', PASS if peak <= ceiling + 0.1 else FAIL, measured=f'{peak:+.1f} dBTP',
                   expected=f'≤ {ceiling} dBTP', detail='Measured per ITU-R BS.1770 on the exported file.')
        integrated = loud and loud.get('integrated_lufs')
        target = spec['loudness']
        if integrated is None:
            _check(checks, 'loudness', 'Integrated loudness', NOT_CHECKED, detail='Loudness could not be measured (very short or silent audio).')
        elif target and project.normalize_audio:
            off = abs(integrated - target['integrated'])
            _check(checks, 'loudness', 'Integrated loudness near the preset target', PASS if off <= 1.0 else WARNING if off <= 2.5 else FAIL,
                   measured=f'{integrated:.1f} LUFS', expected=f'{target["integrated"]} LUFS ± 1 LU',
                   detail=('EBU R128 programme target.' if spec['id'] == 'broadcast-ebu' else 'Product web/social target; not an EBU compliance claim.')
                   + (' The programme sits below target because raising it further would push peaks past the true-peak ceiling; '
                      'the ceiling takes priority.' if peak is not None and integrated < target['integrated'] and peak >= ceiling - 0.6
                      else ' Normalisation is approximate on short clips.'))
        else:
            _check(checks, 'loudness', 'Integrated loudness', NOT_CHECKED, measured=f'{integrated:.1f} LUFS',
                   detail='This export does not normalise loudness, so there is no target to compare against. The measured value is reported.')
    elif audio_expected:
        _check(checks, 'audio_format', 'Audio stream present', FAIL, detail='The export has no audio stream.')
    else:
        _check(checks, 'audio_format', 'Audio stream', NOT_CHECKED, detail='This export was rendered without audio.')

    try:
        intervals = video_measure.black_and_frozen(output)
        fades = sum(c.fade_in + c.fade_out for c in project.clips if c.kind == 'video')
        black = [b for b in intervals['black'] if b['duration'] > 0.25]
        unexpected = [b for b in black if not (b['start'] < 0.6 and fades) and not (b['end'] > meta['duration'] - 0.6 and fades)]
        _check(checks, 'black_frames', 'No unexpected black intervals', PASS if not unexpected else WARNING, measured=black,
               detail='Black at the very start or end is expected when the timeline fades in or out.')
        _check(checks, 'frozen_frames', 'No frozen picture intervals (≥ 1.5 s)', PASS if not intervals['frozen'] else WARNING, measured=intervals['frozen'],
               detail='A still image clip or a motionless shot also reads as frozen; review the listed times.')
    except Exception:
        _check(checks, 'black_frames', 'No unexpected black intervals', NOT_CHECKED, detail='Detection failed.')
        _check(checks, 'frozen_frames', 'No frozen picture intervals (≥ 1.5 s)', NOT_CHECKED, detail='Detection failed.')

    _logo_check(checks, output, project, meta['width'], meta['height'])
    _caption_checks(checks, output, project, meta['width'], meta['height'], captions_requested)
    _designed_graphics_checks(checks,output,project,meta['width'],meta['height'])

    if source_asset is not None:
        if cuts is not None:
            removed = sum(c['end'] - c['start'] for c in cuts)
            explained = abs((source_asset['duration'] - removed) - meta['duration'])
            _check(checks, 'duration_explained', 'Every second of duration change is explained by a listed cut', PASS if explained <= 0.2 else FAIL,
                   measured=dict(source=round(source_asset['duration'], 3), removed_by_cuts=round(removed, 3), result=round(meta['duration'], 3)),
                   expected='source − cuts = result (± 0.2 s)', detail=f'{len(cuts)} cut(s); {explained:.3f}s unexplained.')
        if source_sha_before:
            same = sha256(path_for(source_asset['id'])) == source_sha_before
            _check(checks, 'source_unchanged', 'Original source file unchanged', PASS if same else FAIL, detail='SHA-256 compared before and after the edit.')
    return _summary(checks, spec, meta, loud)


def _summary(checks, spec, meta, loud):
    counts = {status: sum(c['status'] == status for c in checks) for status in (PASS, WARNING, FAIL, NOT_CHECKED)}
    overall = FAIL if counts[FAIL] else WARNING if counts[WARNING] else PASS
    return dict(overall=overall, counts=counts, checks=checks,
                preset=dict(id=spec['id'], label=spec['label'], note=spec['note'],
                            loudness_target_lufs=spec['loudness']['integrated'] if spec['loudness'] else None,
                            true_peak_ceiling_dbtp=spec['true_peak_ceiling']),
                result=meta, loudness=loud,
                scope='Technical and visibility checks on the rendered file. Editorial quality, wording and legal clearance need a person.')


def _lower_peak(asset, gain_db, spec, job):
    """Re-encode only the audio with a fixed gain reduction; the video stream is copied bit-exact."""
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix='peak-') as tmp:
        fixed = Path(tmp) / 'export.mp4'
        ffmpeg(['-protocol_whitelist', 'file,pipe', '-i', str(path_for(asset['id'])), '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
                '-af', f'volume={gain_db:.2f}dB', *audio_encode_args(spec), '-movflags', '+faststart', str(fixed)], job, timeout=300)
        replacement = ingest(fixed, 'export.mp4', job)
    for leftover in (DATA / 'assets').glob(asset['id'] + '.*'):
        leftover.unlink(missing_ok=True)
    return replacement


def master(project, job, *, source_asset=None, source_sha_before=None, cuts=None, captions_requested=None, audio=True):
    """Render, measure the real file, lower any true-peak over, then report."""
    from video.editor import render
    result = render(project, job, audio=audio)
    spec = preset(project.delivery_preset)
    job.update(state='encoding', phase='Measuring the exported file')
    safety = None
    if audio and result.get('has_audio'):
        try:
            measured = video_measure.loudness(path_for(result['id']), job)
        except Exception:
            measured = {}
        peak, integrated = measured.get('true_peak_dbtp'), measured.get('integrated_lufs')
        ceiling, target = spec['true_peak_ceiling'], spec['loudness']
        gain = reason = None
        if peak is not None and peak > ceiling + 0.1:
            gain = ceiling - peak - 0.3
            reason = f'True peak {peak:+.1f} dBTP exceeded the {ceiling} dBTP ceiling after encoding; level lowered.'
        elif target and project.normalize_audio and integrated is not None and peak is not None and abs(integrated - target['integrated']) > 0.7:
            # Second, measured pass: single-pass normalisation is approximate on short clips. A fixed
            # gain moves the programme toward the target, never past the true-peak ceiling.
            gain = min(target['integrated'] - integrated, ceiling - 0.3 - peak)
            reason = (f'Measured {integrated:.1f} LUFS against a {target["integrated"]} LUFS target; fixed gain applied, '
                      f'limited by the {ceiling} dBTP true-peak ceiling.')
            if abs(gain) < 0.3:
                gain = None
        if gain is not None:
            job.update(state='encoding', phase='Adjusting audio level to the measured target')
            result = _lower_peak(result, gain, spec, job)
            safety = dict(applied=True, measured_before_dbtp=peak, measured_before_lufs=integrated, gain_db=round(gain, 2),
                          reason=reason + ' Audio re-encoded once more; video stream copied untouched.')
    report = validate(result, project, source_asset=source_asset, source_sha_before=source_sha_before, cuts=cuts,
                      captions_requested=captions_requested, audio_expected=audio)
    report['true_peak_safety_pass'] = safety or dict(applied=False)
    return annotate(result, qa_report=report)
