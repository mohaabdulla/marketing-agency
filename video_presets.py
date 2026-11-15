"""Named delivery presets: canvas, encoder, colour tags and audio mastering targets.

What is a formal reference and what is a product choice is stated per preset:
- loudness and true peak are *measured* per ITU-R BS.1770 (FFmpeg ebur128) for every preset;
- only "broadcast-ebu" uses the EBU R128 programme target (-23 LUFS). It is a mastering
  profile, not a station delivery certification;
- the social/web targets are product delivery choices and are never labelled EBU compliant;
- SDR output is encoded and tagged as ITU-R BT.709 limited range.
"""

REC709 = dict(color_primaries='bt709', color_transfer='bt709', color_space='bt709', color_range='tv')

PRESETS = {
    'source-master': dict(
        label='Source master', aspect=None, max_edge=1920, crf=16, x264_preset='slow', audio_bitrate='256k',
        loudness=None, true_peak_ceiling=-1.0,
        note='Keeps source framing, frame rate and dynamics. Loudness is not normalised; peaks above the ceiling are lowered.'),
    'web-youtube': dict(
        label='Web / YouTube', aspect=None, max_edge=1920, crf=18, x264_preset='medium', audio_bitrate='192k',
        loudness=dict(integrated=-16.0, range=11.0), true_peak_ceiling=-1.5,
        note='MP4, H.264 High, yuv420p, progressive, fast start, AAC-LC 48 kHz, source frame rate. -16 LUFS is a product web target.'),
    'vertical-social': dict(
        label='Vertical social · 9:16', aspect='9:16', max_edge=1920, crf=18, x264_preset='medium', audio_bitrate='192k',
        loudness=dict(integrated=-16.0, range=9.0), true_peak_ceiling=-1.5,
        note='Full-screen 9:16 for Reels/TikTok/Shorts. The canvas never exceeds the source resolution, so no detail is invented.'),
    'square-social': dict(
        label='Square social · 1:1', aspect='1:1', max_edge=1080, crf=18, x264_preset='medium', audio_bitrate='192k',
        loudness=dict(integrated=-16.0, range=9.0), true_peak_ceiling=-1.5, note='1:1 feed placement.'),
    'portrait-feed': dict(
        label='Portrait feed · 4:5', aspect='4:5', max_edge=1350, crf=18, x264_preset='medium', audio_bitrate='192k',
        loudness=dict(integrated=-16.0, range=9.0), true_peak_ceiling=-1.5, note='4:5 feed placement.'),
    'broadcast-ebu': dict(
        label='Broadcast loudness · EBU R128', aspect=None, max_edge=1920, crf=16, x264_preset='slow', audio_bitrate='256k',
        loudness=dict(integrated=-23.0, range=15.0), true_peak_ceiling=-2.0,
        note='EBU R128 programme loudness target (-23 LUFS) with extra true-peak headroom for the lossy AAC encode. '
             'A mastering profile only: station delivery specifications must still be checked.'),
}
DEFAULT = 'web-youtube'


def preset(name):
    return dict(PRESETS.get(name) or PRESETS[DEFAULT], id=name if name in PRESETS else DEFAULT)


def loudnorm_filter(spec):
    """Single-pass EBU R128 normalisation filter for presets that normalise, else None."""
    target = spec['loudness']
    if not target:
        return None
    return f"loudnorm=I={target['integrated']}:TP={spec['true_peak_ceiling']}:LRA={target['range']}"


def video_encode_args(spec, high=True):
    """H.264 High profile, 4:2:0, progressive, explicit Rec.709 SDR tags, fast start."""
    args = ['-c:v', 'libx264', '-profile:v', 'high', '-preset', spec['x264_preset'] if high else 'veryfast',
            '-crf', str(spec['crf'] if high else 23), '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    for flag, key in (('-color_primaries', 'color_primaries'), ('-color_trc', 'color_transfer'),
                      ('-colorspace', 'color_space'), ('-color_range', 'color_range')):
        args += [flag, REC709[key]]
    return args


def audio_encode_args(spec):
    return ['-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', spec['audio_bitrate'], '-ar', '48000', '-ac', '2']


def canvas_for(source_width, source_height, aspect=None, max_edge=1920):
    """Even canvas inside the source resolution. An aspect change crops; it never upscales."""
    width, height = source_width, source_height
    if aspect:
        a, b = (int(x) for x in aspect.split(':'))
        if width * b > height * a:          # source is wider than the target: keep height
            width = height * a / b
        else:
            height = width * b / a
    ratio = min(1.0, max_edge / max(width, height))
    even = lambda value: max(128, int(round(value * ratio / 2)) * 2)
    return even(width), even(height)


def public():
    return [dict(id=key, label=value['label'], aspect=value['aspect'], note=value['note'],
                 loudness_target_lufs=value['loudness']['integrated'] if value['loudness'] else None,
                 true_peak_ceiling_dbtp=value['true_peak_ceiling'],
                 video='MP4 · H.264 High · yuv420p · progressive · Rec.709 SDR tags · fast start',
                 audio='AAC-LC · 48 kHz · stereo · ' + value['audio_bitrate']) for key, value in PRESETS.items()]
