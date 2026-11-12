"""CPU timeline renderer. Sources are immutable; all intermediates are job scoped."""
import math
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, features
from video_storage import DATA, space
from video_assets import path_for, ingest
from video_ffmpeg import ffmpeg


def primary_layout(project):
    cursor = 0.
    result = []
    previous = None
    for clip in (c for c in project.clips if c.kind == 'video'):
        overlap = min(clip.transition, clip.duration / 2, previous.duration / 2 if previous else 0)
        result.append((clip, cursor - overlap, overlap))
        cursor += clip.duration - overlap
        previous = clip
    if not result or cursor > 300:
        raise ValueError('Add primary clips; maximum timeline duration is 300 seconds')
    return result, cursor


def validate_sources(project):
    from video_storage import read
    layout, duration = primary_layout(project)
    for c in project.clips:
        if c.kind == 'title':
            continue
        item = read('assets', c.asset_id)
        if c.kind == 'audio' and not item.get('has_audio'):
            raise ValueError('Audio tracks require media with an audio stream')
        if c.kind in {'video', 'overlay'} and item['kind'] == 'audio':
            raise ValueError('Visual tracks require image or video assets')
        if c.kind == 'overlay' and item['kind'] != 'image':
            raise ValueError('Logo overlays require a still image')
        if item['duration'] and c.trim + c.duration * c.speed > item['duration'] + .1:
            raise ValueError('Trim and duration exceed the source length')
        if c.kind != 'video' and c.start + c.duration > duration + .1:
            raise ValueError('Overlay or audio extends beyond the primary timeline')
        path_for(c.asset_id)
    return duration


def title_image(clip, path, width):
    size = max(16, round(clip.font_size * width / 1280))
    candidates = {
        'sans': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
        'arabic': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
        'serif': ['C:/Windows/Fonts/times.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'],
    }[clip.font]
    font_path = next((p for p in candidates if Path(p).is_file()), None)
    if not font_path:
        raise ValueError('Install DejaVu fonts or Arial for title rendering')
    font = ImageFont.truetype(font_path, size)
    text = clip.text
    rtl = any('\u0600' <= c <= '\u06ff' for c in text)
    kwargs = {}
    if rtl:
        if features.check_feature('raqm'):
            kwargs = {'direction': 'rtl', 'language': 'ar'}
        else:
            try:
                import arabic_reshaper
                from bidi.algorithm import get_display
                text = get_display(arabic_reshaper.reshape(text))
            except ImportError as exc:
                raise ValueError('Arabic titles require Pillow RAQM or arabic-reshaper and python-bidi') from exc
    im = Image.new('RGBA', (width, max(100, size * 14)))
    draw = ImageDraw.Draw(im)
    # Wrap before rendering; no user text reaches an FFmpeg filter expression.
    lines = []
    for line in text.splitlines():
        words, current = line.split(), ''
        for word in words:
            candidate = (current + ' ' + word).strip()
            if draw.textlength(candidate, font=font, **kwargs) > width - 40 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    text = '\n'.join(lines)
    bounds = draw.multiline_textbbox((0, 0), text, font=font, align='center', **kwargs)
    draw.multiline_text(((width - bounds[2]) / 2, 10 - bounds[1]), text, font=font, fill=clip.color,
                        align='center', stroke_width=1, **kwargs)
    im.crop((0, 0, width, min(im.height, bounds[3] - bounds[1] + 24))).save(path)


def atempo(speed):
    values = []
    while speed < .5:
        values.append('atempo=0.5')
        speed /= .5
    while speed > 2:
        values.append('atempo=2')
        speed /= 2
    return ','.join(values + [f'atempo={speed}'])


def render(project, job, container='mp4', audio=True, preview=False):
    from video_storage import read
    layout, duration = primary_layout(project)
    validate_sources(project)
    space(int(duration * 2_000_000))
    w, h, fps = project.canvas.width, project.canvas.height, project.canvas.fps
    if project.canvas.fps_mode == 'original':
        fps = read('assets', layout[0][0].asset_id).get('fps') or fps
        if not 1 <= fps <= 60:
            raise ValueError('Original frame rate must be between 1 and 60 fps')
    if preview:
        ratio = min(1, 480 / max(w, h))
        w, h = round(w * ratio / 2) * 2, round(h * ratio / 2) * 2
    with tempfile.TemporaryDirectory(dir=DATA / 'work', prefix=job.id + '-') as tmp:
        tmp = Path(tmp)
        intermediates = []
        for i, (c, _, _) in enumerate(layout):
            job.update(state='encoding', progress={'completed_clips': i, 'total_clips': len(layout)}, phase='Normalizing clips')
            src = path_for(c.asset_id)
            meta = read('assets', c.asset_id)
            still = meta['kind'] == 'image'
            inputs = ['-loop', '1', '-framerate', str(fps)] if still else ['-ss', str(c.trim)]
            inputs += ['-protocol_whitelist', 'file,pipe', '-i', str(src)]
            if not meta.get('has_audio'):
                inputs += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            filters = [f'setpts=(PTS-STARTPTS)/{c.speed}', f'crop=iw*{1-2*c.crop}:ih*{1-2*c.crop}',
                       f'scale={w}:{h}:force_original_aspect_ratio=increase', f'crop={w}:{h}', 'setsar=1', f'fps={fps}']
            if c.zoom != 1 or c.zoom_start != 1 or c.pan:
                filters += [f"zoompan=z='{c.zoom_start}+({c.zoom}-{c.zoom_start})*on/{max(1,round(c.duration*fps)-1)}':x='iw/2-iw/zoom/2+({c.pan})*(iw-iw/zoom)*(on/{max(1,round(c.duration*fps)-1)}-0.5)':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}"]
            if c.rotation:
                filters += [f'rotate={c.rotation}*PI/180:c=black']
            if c.scale != 1 or c.x != .5 or c.y != .5:
                # Canvas-relative transform: scale, pad then crop to output size.
                sw, sh = max(2, round(w*c.scale/2)*2), max(2, round(h*c.scale/2)*2)
                pw, ph = max(w, sw), max(h, sh)
                filters += [f'scale={sw}:{sh}', f'pad={pw}:{ph}:(ow-iw)*{c.x}:(oh-ih)*{c.y}',
                            f'crop={w}:{h}:(iw-ow)*{c.x}:(ih-oh)*{c.y}']
            filters += [f'eq=brightness={c.brightness}:contrast={c.contrast}:saturation={c.saturation}']
            if c.fade_in:
                filters += [f'fade=t=in:st=0:d={c.fade_in}']
            if c.fade_out:
                filters += [f'fade=t=out:st={max(0,c.duration-c.fade_out)}:d={c.fade_out}']
            filters += ['format=yuv420p']
            out = tmp / f'clip-{i}.mp4'
            ffmpeg(inputs + ['-map', '0:v:0', '-map', '0:a:0' if meta.get('has_audio') else '1:a:0',
                             '-vf', ','.join(filters), '-af', atempo(c.speed) + f',volume={c.volume},aresample=48000,apad',
                             '-t', str(c.duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                             '-c:a', 'aac', '-ac', '2', '-ar', '48000', str(out)], job)
            intermediates.append(out)
        args, graph = [], []
        for p in intermediates:
            args += ['-i', str(p)]
        vlabel, alabel = '0:v', '0:a'
        elapsed = layout[0][0].duration
        for i in range(1, len(layout)):
            c, _, overlap = layout[i]
            nv, na = f'v{i}', f'a{i}'
            if overlap:
                graph += [f'[{vlabel}][{i}:v]xfade=transition=fade:duration={overlap}:offset={elapsed-overlap}[{nv}]',
                          f'[{alabel}][{i}:a]acrossfade=d={overlap}[{na}]']
            else:
                graph += [f'[{vlabel}][{alabel}][{i}:v][{i}:a]concat=n=2:v=1:a=1[{nv}][{na}]']
            vlabel, alabel = nv, na
            elapsed += c.duration - overlap
        index = len(intermediates)
        for n, c in enumerate(x for x in project.clips if x.kind in {'overlay', 'title'}):
            source = path_for(c.asset_id) if c.kind == 'overlay' else tmp / f'title-{n}.png'
            if c.kind == 'title':
                title_image(c, source, w)
            args += ['-loop', '1', '-framerate', str(fps), '-i', str(source)]
            filters = f'scale={max(2,round(w*c.scale/2)*2)}:-2,format=rgba,colorchannelmixer=aa={c.opacity}'
            if c.rotation:
                filters += f',rotate={c.rotation}*PI/180:c=none:ow=rotw(iw):oh=roth(ih)'
            if c.fade_in:
                filters += f',fade=t=in:st={c.start}:d={c.fade_in}:alpha=1'
            if c.fade_out:
                filters += f',fade=t=out:st={max(c.start,c.start+c.duration-c.fade_out)}:d={c.fade_out}:alpha=1'
            graph += [f'[{index}:v]{filters}[ov{n}]',
                      f"[{vlabel}][ov{n}]overlay=x=(W-w)*{c.x}:y=(H-h)*{c.y}:enable='between(t,{c.start},{c.start+c.duration})':eof_action=pass[vo{n}]"]
            vlabel = f'vo{n}'
            index += 1
        audio_labels = [alabel]
        if audio:
            for n, c in enumerate(x for x in project.clips if x.kind == 'audio'):
                args += ['-ss', str(c.trim), '-i', str(path_for(c.asset_id))]
                graph += [f'[{index}:a]{atempo(c.speed)},atrim=duration={c.duration},asetpts=PTS-STARTPTS,'
                          f'volume={c.volume},afade=t=in:d={max(.001,c.fade_in)},'
                          f'afade=t=out:st={max(0,c.duration-c.fade_out)}:d={max(.001,c.fade_out)},'
                          f'adelay={round(c.start*1000)}:all=1[au{n}]']
                audio_labels.append(f'au{n}')
                index += 1
        if len(audio_labels) > 1:
            graph += [''.join(f'[{x}]' for x in audio_labels) + f'amix=inputs={len(audio_labels)}:normalize=0:duration=longest[mix]']
            alabel = 'mix'
        dest = tmp / ('preview.mp4' if preview else f'export.{container}')
        if graph:
            # Passed as one argv value, never through a shell. Titles are PNG inputs.
            # filter_complex_script was removed in newer FFmpeg builds.
            args += ['-filter_complex', ';'.join(graph)]
        def mapped(label):
            return label if ':' in label else f'[{label}]'
        args += ['-map', mapped(vlabel)]
        args += ['-map', mapped(alabel), '-c:a', 'aac' if container == 'mp4' else 'libopus'] if audio else ['-an']
        args += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-movflags', '+faststart'] if container == 'mp4' else ['-c:v', 'libvpx-vp9', '-crf', '32', '-b:v', '0', '-deadline', 'realtime', '-cpu-used', '6']
        args += ['-pix_fmt', 'yuv420p', '-r', str(fps), '-t', str(duration), str(dest)]
        job.update(state='encoding', progress=None, phase='Compositing timeline')
        ffmpeg(args, job, timeout=1200)
        return ingest(dest, dest.name, job)
