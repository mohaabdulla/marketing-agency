"""Editorial, brand and platform review of an edit. Separate from technical delivery QA.

Technical QA (video_qa) answers "is this a correct file?". This module answers the questions an
editor would ask, as far as they can be measured: does speech start promptly, is the pacing
static, is the face clear of graphics, did the lighting correction help, were names confirmed,
does the frame respect the platform's interface. Checks that need human or semantic judgement
are reported as NOT_CHECKED, never as PASS. There is no single "professional" score.
"""
import video_measure
import video_platforms
from video_assets import path_for

PASS, WARNING, FAIL, NOT_CHECKED = 'PASS', 'WARNING', 'FAIL', 'NOT_CHECKED'


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def review(output_asset, project, source_asset, report, face=None, job=None):
    from video_captions import render_caption_image, track_style
    checks = []

    def add(category, key, label, status, measured=None, detail='', basis='MEASURED'):
        checks.append(dict(category=category, id=key, label=label, status=status, measured=measured, detail=detail, basis=basis))

    width, height = project.canvas.width, project.canvas.height
    duration = report['edited_duration']
    track = next((t for t in project.caption_tracks if t.get('segments') and t.get('kind', 'captions') == 'captions'), None)
    lower = next((t for t in project.caption_tracks if t.get('kind') == 'lower-third'), None)
    cues = track['segments'] if track else []
    platform = video_platforms.profile(report['platform_profile']['id'])

    # ---- hook
    if cues:
        first = cues[0]['start']
        add('Hook', 'speech_start', 'Speech starts promptly', PASS if first <= 1.0 else WARNING if first <= 2.0 else FAIL, f'{first:.2f}s',
            f'First words: "{cues[0]["text"][:60]}".')
    else:
        add('Hook', 'speech_start', 'Speech starts promptly', NOT_CHECKED, detail='No transcript: speech timing was not measured.', basis='NOT_MEASURED')
    add('Hook', 'hook_strength', 'Opening idea is compelling', NOT_CHECKED,
        detail='Whether the first three seconds make a strong hook is a judgement for a person (or the optional semantic planner); it is not scored here.',
        basis='NOT_MEASURED')

    # ---- story
    proposed = report.get('proposed_cuts', [])
    add('Story', 'pending_cuts', 'No edit decision is waiting for approval', WARNING if proposed else PASS, len(proposed),
        '; '.join(f'{c["reason"]} at {c["start"]:.2f}s ({c["confidence"]:.0%} confidence)' for c in proposed) or 'Every applied cut met the confidence threshold.')
    risky = [c for c in report['cuts'] if c['confidence'] < 0.8]
    add('Story', 'cut_confidence', 'Applied cuts rest on strong evidence', WARNING if risky else PASS if report['cuts'] else NOT_CHECKED,
        [f'{c["start"]:.2f}s {c["confidence"]:.0%}' for c in risky],
        'Cuts between 60% and 80% confidence are applied but should be watched.' if risky else 'No cuts were made.' if not report['cuts'] else 'All applied cuts are at or above 80% confidence.')
    add('Story', 'key_message', 'Key message retained', NOT_CHECKED, detail='Semantic importance of each sentence is not measured without the semantic planner.', basis='NOT_MEASURED')

    # ---- pacing
    videos = [c for c in project.clips if c.kind == 'video']
    events, position = [], 0.0
    for index, clip in enumerate(videos):
        if index and (abs(clip.trim - (videos[index - 1].trim + videos[index - 1].duration)) > 0.05 or clip.zoom != videos[index - 1].zoom):
            events.append(position)
        position += clip.duration
    gaps = [b - a for a, b in zip([0.0] + events, events + [duration])]
    longest = max(gaps) if gaps else duration
    add('Pacing', 'static_interval', 'No overlong visually static stretch', PASS if longest <= 8 else WARNING, f'{longest:.1f}s',
        'Longest stretch without a cut or framing change. Over about 8 seconds a talking-head shot starts to feel static on social platforms (an editorial guideline, not a rule).')
    density = len(events) / max(duration, 1) * 10
    add('Pacing', 'edit_density', 'Edit density is reasonable', PASS if density <= 6 else WARNING, f'{density:.1f} changes per 10s',
        'More than about six cuts or framing changes per ten seconds reads as over-edited for organic content.')
    intervals = [b - a for a, b in zip(events, events[1:])]
    regular = len(intervals) >= 2 and max(intervals) - min(intervals) < 0.25
    add('Pacing', 'repetitive_pattern', 'Framing changes do not follow a fixed rhythm', WARNING if regular else PASS if events else NOT_CHECKED,
        [round(x, 2) for x in intervals], 'Evenly spaced changes look mechanical.' if regular else 'No framing changes.' if not events else 'Changes are tied to content, not a timer.')
    purposes = [d for d in report['decisions'] if d['type'] in ('PUNCH_IN', 'PUNCH_OUT')]
    add('Pacing', 'framing_purpose', 'Every framing change states its purpose and evidence', PASS if all(d.get('purpose') and d.get('evidence') for d in purposes) else FAIL,
        len(purposes), 'No framing changes were made.' if not purposes else '; '.join(d['purpose'] for d in purposes))

    # ---- framing: face against graphics
    caption_box = None
    if track:
        longest_cue = max(cues, key=lambda c: len(c['text']))
        caption_box = render_caption_image(longest_cue['text'].strip(), width, height, track_style(track)).info['caption_layout']['box']
    logo = next((c for c in project.clips if c.kind == 'overlay'), None)
    logo_box = None
    if logo:
        from PIL import Image
        with Image.open(path_for(logo.asset_id)) as image:
            lw = max(2, round(width * logo.scale / 2) * 2)
            lh = round(image.height * lw / image.width)
            if logo.logo_backplate:
                lh = round((image.height + 2 * max(8, round(image.width * .05))) * lw / (image.width + 2 * max(8, round(image.width * .05))))
        logo_box = [round((width - lw) * logo.x), round((height - lh) * logo.y), round((width - lw) * logo.x) + lw, round((height - lh) * logo.y) + lh]
    if face:
        face_box = [face['x'] * width, face['y'] * height, (face['x'] + face['width']) * width, (face['y'] + face['height']) * height]
        graphics = [('captions', caption_box), ('logo', logo_box)]
        if lower:
            graphics.append(('lower third', render_caption_image(lower['segments'][0]['text'], width, height, track_style(lower)).info['caption_layout']['box']))
        for title in (c for c in project.clips if c.kind == 'title'):
            # Titles are centred horizontally; their height follows the renderer's font scaling.
            size = max(16, round(title.font_size * width / 1280)) * 1.6
            top = (height - size) * title.y
            graphics.append((f'title "{title.text[:24]}"', [width * .1, top, width * .9, top + size]))
        covered = [name for name, box in graphics if box and _overlap(face_box, box) > 0]
        add('Framing', 'face_clear', 'Face is not covered by captions, titles or logo', FAIL if covered else PASS, covered or None,
            'Checked against the detected face position in the source framing.')
        add('Framing', 'headroom', 'Headroom is sensible', PASS if 0.04 <= face['headroom'] <= 0.45 else WARNING, f'{face["headroom"]:.0%} of frame above the face')
    else:
        add('Framing', 'face_clear', 'Face is not covered by captions, titles or logo', NOT_CHECKED, detail='No face was detected, so overlap could not be checked.', basis='NOT_MEASURED')
        add('Framing', 'headroom', 'Headroom is sensible', NOT_CHECKED, detail='No face was detected.', basis='NOT_MEASURED')

    # ---- colour / light, measured on the rendered file against the source
    lighting = report.get('lighting') or {}
    try:
        import video_grade
        first = videos[0]
        offset = min(1.0, first.duration / 2)
        before = video_grade.light_stats(video_measure.frame_at(path_for(source_asset['id']), first.trim + offset), face)
        after_frame = video_measure.frame_at(path_for(output_asset['id']), offset)
        # The export is the same framing at clip start unless punched in; the face box is approximate after a zoom.
        after = video_grade.light_stats(after_frame, face if first.zoom == 1 else None)
    except Exception:
        before = after = None
    if before and after:
        if after['face_luma'] is not None and before['face_luma'] is not None:
            delta = after['face_luma'] - before['face_luma']
            add('Colour & light', 'face_exposure', 'Face exposure', PASS if 0.35 <= after['face_luma'] <= 0.7 else WARNING,
                dict(source=before['face_luma'], export=after['face_luma'], change=round(delta, 3)),
                'Mean luminance of the face region in a rendered frame (0–1). Captions and graphics are not in this region.')
            shift = video_grade.hue_difference(after['face_hue'], before['face_hue'])
            add('Colour & light', 'skin_shift', 'Skin colour stays natural', PASS if shift <= 8 else WARNING, f'{shift:.0f}° hue shift', 'Hue shift of the face region between source and export.')
        else:
            add('Colour & light', 'face_exposure', 'Face exposure', NOT_CHECKED, detail='No face region to measure.', basis='NOT_MEASURED')
        clip_change = after['clipped_highlights'] - before['clipped_highlights']
        add('Colour & light', 'highlights', 'No extra highlight clipping introduced', PASS if clip_change <= 0.01 else WARNING,
            dict(source=before['clipped_highlights'], export=after['clipped_highlights']), 'Share of the frame at pure white.')
    else:
        add('Colour & light', 'face_exposure', 'Face exposure', NOT_CHECKED, detail='Frames could not be decoded for measurement.', basis='NOT_MEASURED')
    add('Colour & light', 'lighting_correction', 'Lighting correction', PASS if lighting.get('status') in ('CORRECTED', 'NO_CORRECTION_NEEDED') else WARNING if lighting.get('status') == 'REJECTED' else NOT_CHECKED,
        lighting.get('status'), '; '.join(f['message'] for f in lighting.get('findings', [])) or lighting.get('reason', ''))

    # ---- background
    background = report.get('background') or {}
    asked = next((r for r in report['request_fulfilment'] if r['request'] == 'background'), None)
    if asked:
        add('Background', 'request', 'Background request', PASS if asked['status'] == 'FULFILLED' else WARNING, asked['status'], asked['detail'])
    mask = background.get('mask')
    if project.background and mask:
        add('Background', 'mask_stability', 'Subject mask is stable over time', PASS if mask['stable'] else WARNING,
            dict(temporal_iou=mask['temporal_iou'], abrupt_changes=mask['coverage_jumps']), 'Frame-to-frame overlap of the subject mask; low values show as edge flicker.')
    else:
        add('Background', 'mask_stability', 'Subject mask is stable over time', NOT_CHECKED, detail='No subject-mask treatment was rendered.', basis='NOT_MEASURED')

    # ---- captions
    review_state = report.get('caption_review') or {}
    if not cues:
        add('Captions', 'review', 'Caption review', FAIL if report.get('captions_requested') else NOT_CHECKED, detail=report.get('caption_diagnostic') or 'Captions are off.')
    elif review_state.get('unresolved'):
        add('Captions', 'review', 'Caption review', FAIL, [f'{n["heard"]} {n["confidence"]:.0%}' for n in review_state['unresolved']],
            'CAPTION REVIEW REQUIRED: these likely names were recognised with low confidence. Confirm or correct them; the system does not guess.')
    elif report.get('caption_state') == 'reviewed':
        add('Captions', 'review', 'Caption review', PASS, detail='Marked as reviewed by the operator.', basis='USER_SUPPLIED')
    else:
        add('Captions', 'review', 'Caption review', WARNING, detail='Draft from speech recognition. Read every cue against the audio before publishing.')
    if cues:
        speeds = [len(' '.join(c['text'].split())) / max(0.01, c['end'] - c['start']) for c in cues]
        fast = [f'{c["start"]:.1f}s' for c, s in zip(cues, speeds) if s > 20]
        add('Captions', 'reading_speed', 'Reading speed within 20 characters per second', WARNING if fast else PASS, f'max {max(speeds):.0f} cps',
            ('Too fast at ' + ', '.join(fast) + '. ' if fast else '') + '20 cps is a professional subtitling reference, used here as a guideline.')

    # ---- brand
    add('Brand', 'logo', 'Brand logo present', PASS if logo else NOT_CHECKED, detail='' if logo else 'No logo was selected.')
    cta = next((c for c in project.clips if c.kind == 'title' and c.text_role == 'cta'), None)
    rules = project.brand_rules or {}
    if rules.get('cta'):
        add('Brand', 'cta', 'Approved call to action present', PASS if cta else WARNING, cta.text[:60] if cta else None, 'The reviewed guideline specifies a call to action.')
    else:
        add('Brand', 'cta', 'Approved call to action present', NOT_CHECKED, detail='The guideline does not specify a call to action.')

    # ---- audio (editorial; level compliance lives in technical QA)
    if output_asset.get('has_audio'):
        try:
            signal = video_measure.audio_quality(path_for(output_asset['id']), job)
            add('Audio', 'signal_clipping', 'Decoded audio stays below full scale', WARNING if signal['near_full_scale_share'] > .0001 else PASS,
                signal['near_full_scale_share'], 'Measured on an 8 kHz mono proxy; true-peak delivery QA remains the authoritative peak check.')
            candidates = [h for h in signal['hum_candidates'] if h['possible_hum']]
            add('Audio', 'hum_indicator', 'No strong mains-hum candidate', WARNING if candidates else PASS, signal['hum_candidates'],
                'Spectral indicator only: strong 50/60 Hz bins compared with nearby frequencies. Listen before applying a notch.')
            add('Audio', 'quiet_level', 'Quiet-block signal level', WARNING if signal['quiet_block_level_dbfs'] > -30 else PASS,
                signal['quiet_block_level_dbfs'], signal['limitations'])
        except ValueError:
            add('Audio', 'signal_analysis', 'Audio signal indicators', NOT_CHECKED, detail='Signal analysis could not be completed.', basis='NOT_MEASURED')
    add('Audio', 'dialogue_processing', 'Dialogue clarity processing', PASS if project.dialogue_polish else NOT_CHECKED,
        detail='High-pass filter and gentle compression applied.' if project.dialogue_polish else 'Not applied. Noise floor, sibilance and spectral balance are not measured.',
        basis='MEASURED' if project.dialogue_polish else 'NOT_MEASURED')
    music = [c for c in project.clips if c.kind == 'audio' and c.audio_role == 'music']
    add('Audio', 'music_balance', 'Music sits under dialogue', NOT_CHECKED if not music else PASS if all(c.ducking_priority > 0 or c.volume <= .5 for c in music) else WARNING,
        detail='No music track.' if not music else 'Music is ducked or kept at half level or lower.')

    # ---- platform
    short_side = min(width, height)
    add('Platform', 'resolution', f'Resolution suits {platform["label"]}', PASS if short_side >= platform['minimum_short_side'] else WARNING, f'{width}×{height}',
        '' if short_side >= platform['minimum_short_side'] else
        f'Below the {platform["minimum_short_side"]}-pixel short side commonly recommended. The source is {source_asset["width"]}×{source_asset["height"]}; '
        'scaling up would fit the canvas but cannot restore detail.')
    a, b = (int(x) for x in platform['aspect'].split(':'))
    add('Platform', 'aspect', f'Aspect ratio suits {platform["label"]}', PASS if abs(width / height - a / b) < 0.03 else WARNING, f'{width}:{height}', f'Profile aspect {platform["aspect"]}.')
    for name, box in (('Captions', caption_box), ('Logo', logo_box)):
        if not box:
            continue
        share = video_platforms.outside_share(box, platform, width, height)
        add('Platform', name.lower() + '_safe_zone', f'{name} clear of the {platform["label"]} interface area', PASS if share <= 0.02 else WARNING if share <= 0.3 else FAIL,
            f'{share:.0%} of the element is in an obstructed region',
            f'{platform["basis"]}: approximate interface regions (top {platform["top"]:.0%}, bottom {platform["bottom"]:.0%}, left {platform["left"]:.0%}, right {platform["right"]:.0%}), not an official specification.',
            basis='PRODUCT_DEFAULT')

    categories = {}
    for check in checks:
        current = categories.setdefault(check['category'], dict(status=NOT_CHECKED, counts={PASS: 0, WARNING: 0, FAIL: 0, NOT_CHECKED: 0}))
        current['counts'][check['status']] += 1
    for value in categories.values():
        counts = value['counts']
        value['status'] = FAIL if counts[FAIL] else WARNING if counts[WARNING] else PASS if counts[PASS] else NOT_CHECKED
    statuses = [c['status'] for c in checks]
    caption_gate = ('NOT_APPLICABLE' if not cues and not report.get('captions_requested') else 'REQUIRED' if (review_state.get('unresolved') or not cues)
                    else 'DONE' if report.get('caption_state') == 'reviewed' else 'RECOMMENDED')
    technical = (output_asset.get('qa_report') or {}).get('overall')
    blockers = []
    if technical == FAIL:
        blockers.append('Technical delivery QA has failures')
    if caption_gate == 'REQUIRED':
        blockers.append('Caption review is required')
    if caption_gate == 'RECOMMENDED':
        blockers.append('Captions have not been reviewed by a person')
    if proposed:
        blockers.append('A proposed cut awaits approval')
    if FAIL in statuses:
        blockers.append('Editorial review has failed checks')
    return dict(
        editorial_status='NEEDS REVIEW' if FAIL in statuses or WARNING in statuses else 'PASS',
        technical_status=technical, caption_review=caption_gate,
        brand_status=categories.get('Brand', {}).get('status', NOT_CHECKED),
        publish_readiness='DRAFT' if blockers else 'READY', blockers=blockers,
        categories=categories, checks=checks, platform_profile=report['platform_profile'],
        methodology='Each line is one measured or declared check. Categories roll up to the worst result among their checks. '
                    'There is no overall score; NOT_CHECKED means the system cannot judge that point.',
        scope='Editorial checks approximate an editor\'s questions with measurements. Taste, story quality and hook strength still need a person.')
