"""CPU timeline renderer. Sources are immutable; all intermediates are job scoped."""
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, features
from video.storage import DATA, space
from video.assets import path_for, ingest
from video.ffmpeg import ffmpeg


REC709_FRAMES = 'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv'


def entrance(start, height, intensity):
    """Fixed cubic ease-out, built only from validated timeline numbers."""
    amount = height * {'minimal': .015, 'balanced': .03, 'expressive': .05}[intensity]
    return f"{amount:.3f}*pow(1-min(1,max(0,(t-{start:.4f})/0.35)),3)"


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
    from video.storage import read
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


def title_image(clip, path, width,height=None):
    if clip.graphic_style:
        from video.captions import CaptionStyle,render_caption_image
        height=height or min(1920,round(clip.graphic_style['canvas_height']*width/clip.graphic_style['canvas_width']))
        style=CaptionStyle.model_validate({k:v for k,v in clip.graphic_style.items() if k not in {'canvas_height','canvas_width'}})
        render_caption_image(clip.text,width,height,style).save(path)
        return
    size = max(16, round(clip.font_size * width / 1280))
    candidates = {
        'sans': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
        'arabic': ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
        'serif': ['C:/Windows/Fonts/times.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'],
    }[clip.font]
    from video.fonts import path as named_font
    font_path = named_font(clip.font_family) or next((p for p in candidates if Path(p).is_file()), None)
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


def trim_layer(path, width, height):
    """Crop a full-frame transparent layer (title or subtitle artwork) to its visible pixels, in place.
    Returns the crop's top-left corner, or None when the file is not full-frame or is empty."""
    with Image.open(path) as opened:
        if opened.size != (width, height) or opened.mode != 'RGBA':
            return None
        layer = opened.copy()
    box = layer.getchannel('A').getbbox()
    if not box:
        return None
    x0, y0 = max(0, box[0] - 2), max(0, box[1] - 2)
    layer.crop((x0, y0, min(width, box[2] + 2), min(height, box[3] + 2))).save(path)
    return x0, y0


def card_layers(source, crop, width, height, size, backdrop_path, card_path):
    """The two still layers of a framed picture, built once: a blurred cover of the frame, and the whole
    picture (fitted into ``size`` of the frame) on a soft drop shadow, as an RGBA card."""
    from PIL import ImageFilter, ImageOps
    with Image.open(source) as opened:
        picture = ImageOps.exif_transpose(opened).convert('RGB')
    if crop:
        dx, dy = round(picture.width * crop), round(picture.height * crop)
        picture = picture.crop((dx, dy, picture.width - dx, picture.height - dy))
    cover = ImageOps.fit(picture, (width, height), Image.Resampling.LANCZOS)
    cover.filter(ImageFilter.GaussianBlur(max(8, width / 60))).save(backdrop_path)
    # Fitted inside size x frame, enlarging small pictures as well as reducing large ones.
    ratio = min(width * size / picture.width, height * size / picture.height)
    card = picture.resize((max(2, round(picture.width * ratio)), max(2, round(picture.height * ratio))), Image.Resampling.LANCZOS)
    pad = max(4, round(height * .05))
    shadow = Image.new('RGBA', (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 140), (pad, pad, pad + card.width, pad + card.height))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad / 3))
    shadow.paste(card, (pad, pad - pad // 4))
    # Even dimensions for the 4:2:0 conversion.
    even = Image.new('RGBA', (shadow.width // 2 * 2 + 2, shadow.height // 2 * 2 + 2), (0, 0, 0, 0))
    even.alpha_composite(shadow)
    even.save(card_path)


def camera_filters(c, anchors, fps, w, h):
    """A clip's zoom and pan as a sub-pixel crop (perspective filter, bicubic), then one resample to the
    output size. Same framing rules as before: the window is centred on the zoom anchor, pans across the
    spare width and never leaves the picture. Without zoom_ease the move runs at one speed for the clip."""
    from video.tracking import expression
    frames = max(1, round(c.duration * fps) - 1)
    step = f'min(1,max(0,in/{max(1, c.zoom_ease * fps):.4f}))' if c.zoom_ease else f'min(1,in/{frames})'
    ease = f'({step}*{step}*(3-2*{step}))' if c.zoom_ease else step
    z = f'({c.zoom_start}+({c.zoom}-{c.zoom_start})*{ease})'
    time = f'(in/{fps:.7f})'
    zx, zy = expression(anchors, 'x', time, c.zoom_x), expression(anchors, 'y', time, c.zoom_y)
    x = f'min(max(0,W*({zx})-W/{z}/2+({c.pan})*(W-W/{z})*({step}-0.5)),W-W/{z})'
    y = f'min(max(0,H*({zy})-H/{z}/2),H-H/{z})'
    right, bottom = f'{x}+W/{z}', f'{y}+H/{z}'
    return [f"perspective=x0='{x}':y0='{y}':x1='{right}':y1='{y}':x2='{x}':y2='{bottom}':x3='{right}':y3='{bottom}'"
            ':interpolation=cubic:eval=frame', f'scale={w}:{h}:flags=lanczos']


def render(project, job, container='mp4', audio=True, preview=False):
    from video.storage import read
    layout, duration = primary_layout(project)
    validate_sources(project)
    space(int(duration * 2_000_000))
    w, h, fps = project.canvas.width, project.canvas.height, project.canvas.fps
    high = project.export_quality == 'high' and not preview
    from video.presets import preset, video_encode_args, audio_encode_args, loudnorm_filter
    spec = preset(project.delivery_preset)
    # The frame rate is passed to FFmpeg as the source's exact rational (for example 30000/1001),
    # so 29.97/59.94 material is never silently rounded to 30/60.
    fps_arg = str(fps)
    if project.canvas.fps_mode == 'original':
        first = read('assets', layout[0][0].asset_id)
        fps = first.get('fps') or fps
        if not 1 <= fps <= 60:
            raise ValueError('Original frame rate must be between 1 and 60 fps')
        fps_arg = first.get('fps_rational') or str(fps)
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
            inputs = ['-loop', '1', '-framerate', fps_arg] if still else ['-ss', str(c.trim)]
            inputs += ['-protocol_whitelist', 'file,pipe', '-i', str(src)]
            if not meta.get('has_audio'):
                inputs += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            from video.tracking import expression
            anchors=[p.model_dump() for p in c.reframe_keyframes]
            anchor_x=expression(anchors,'x','t',c.zoom_x);anchor_y=expression(anchors,'y','t',c.zoom_y)
            # Camera moves use the perspective filter, which samples the picture at fractional pixel
            # positions (bicubic). zoompan snaps its window to whole pixels, so a slow move advanced in
            # uneven steps (measured 0.12-0.79 px a frame for a steady 0.47 px move) even on a 3x frame.
            # The working frame is enlarged by the deepest zoom so the move never magnifies the source.
            moving = c.zoom_start != c.zoom or bool(c.pan) or bool(anchors)
            deepest = max(c.zoom_start, c.zoom, 1)
            oversample = 1 if not moving or preview else min(deepest, 2, 5760 / max(w, h))
            ww, wh = max(2, round(w * oversample / 2) * 2), max(2, round(h * oversample / 2) * 2)
            filters = [f'setpts=(PTS-STARTPTS)/{c.speed}', f'crop=iw*{1-2*c.crop}:ih*{1-2*c.crop}',
                       # Explicit Rec.709 limited-range SDR working space for every clip.
                       f'scale={ww}:{wh}:force_original_aspect_ratio=increase:out_color_matrix=bt709:out_range=tv' + (':flags=lanczos' if moving and not preview else ''),
                       f"crop={ww}:{wh}:x='min(max(0,iw*({anchor_x})-{ww}/2),iw-{ww})':y='min(max(0,ih*({anchor_y})-{wh}/2),ih-{wh})'", 'setsar=1', f'fps={fps_arg}']
            if not still and (getattr(c, 'smooth_motion', False) or getattr(project, 'frame_interpolation', False)):
                # Frame-rate conversion and slow motion: new in-between frames are built from the source frames.
                # This replaces the fps filter; after it the frames are already duplicated and nothing is left to
                # interpolate. Motion-compensated for exports, a cheap blend for previews.
                mi_mode = 'blend' if preview else 'mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'
                filters[-1] = f'minterpolate=fps={fps_arg}:mi_mode={mi_mode}'
            if c.zoom != 1 or c.zoom_start != 1 or c.pan:
                filters += camera_filters(c, anchors, fps, w, h)
            elif oversample != 1:
                filters += [f'scale={w}:{h}:flags=lanczos']
            if c.rotation:
                filters += [f'rotate={c.rotation}*PI/180:c=black']
            if c.scale != 1 or c.x != .5 or c.y != .5:
                # Canvas-relative transform: scale, pad then crop to output size.
                sw, sh = max(2, round(w*c.scale/2)*2), max(2, round(h*c.scale/2)*2)
                pw, ph = max(w, sw), max(h, sh)
                filters += [f'scale={sw}:{sh}', f'pad={pw}:{ph}:(ow-iw)*{c.x}:(oh-ih)*{c.y}',
                            f'crop={w}:{h}:(iw-ow)*{c.x}:(ih-oh)*{c.y}']
            filters += [f'eq=brightness={c.brightness}:contrast={c.contrast}:saturation={c.saturation}']
            from video.grade import filters as grade_filters
            filters += grade_filters(c)
            if getattr(project, 'unified_grade', None) or getattr(project, 'global_denoise', 0.0) > 0:
                from video.grade import unified_grade_filters
                filters += unified_grade_filters(getattr(project, 'unified_grade', None), getattr(project, 'global_denoise', 0.0))
            if c.fade_in:
                filters += [f'fade=t=in:st=0:d={c.fade_in}']
            if c.fade_out:
                filters += [f'fade=t=out:st={max(0,c.duration-c.fade_out)}:d={c.fade_out}']
            # Frame properties carry the colour description into the encoder; encoder flags alone
            # are dropped when the source frames are untagged.
            filters += ['format=yuv420p', REC709_FRAMES]
            out = tmp / f'clip-{i}.mp4'
            video_args = ['-map', '0:v:0', '-vf', ','.join(filters)]
            treatment = project.background if not still else None
            regional=project.color_pipeline if project.color_pipeline and project.color_pipeline.regional and project.color_pipeline.source_asset_id==c.asset_id and not still else None
            if treatment or regional:
                if not treatment:
                    from video.projects import BackgroundTreatment
                    treatment=BackgroundTreatment(blur=0,dim=0,desaturate=0,mask_fps=regional.mask_fps)
                # Subject kept, background treated: composited at source size before any reframing.
                from video.segmentation import cached_mask
                found = cached_mask(c.asset_id, treatment.mask_fps)
                if not found:
                    raise ValueError('Create the subject mask for this video before rendering a background treatment')
                sw, sh = meta['width'] // 2 * 2, meta['height'] // 2 * 2
                mask_index = 1 if meta.get('has_audio') else 2
                inputs += ['-ss', str(c.trim), '-protocol_whitelist', 'file,pipe', '-i', str(found[0])]
                # Pull the matte edge slightly inside the subject, then feather it: the blurred
                # background never shows through as a bright rim around hair and shoulders.
                feather = max(1.0, min(sw, sh) / 380)
                graph_parts = [f'[{mask_index}:v]scale={sw}:{sh}:flags=bicubic,format=gray,erosion,gblur=sigma={feather:.2f},format=gbrp[mk]']
                if treatment.mode == 'replace':
                    replacement=read('assets',treatment.replacement_asset_id)
                    repeat=['-loop','1','-framerate',fps_arg] if replacement['kind']=='image' else ['-stream_loop','-1']
                    inputs += repeat+['-protocol_whitelist', 'file,pipe', '-i', str(path_for(treatment.replacement_asset_id))]
                    graph_parts += [f'[{mask_index + 1}:v]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},setsar=1,format=gbrp[bgp]',
                                    f'[0:v]scale={sw}:{sh},setsar=1,format=gbrp[fgp]']
                elif treatment.blur or treatment.dim or treatment.desaturate:
                    # Blur only real background: the subject is excluded before blurring and the result is
                    # renormalised, so no dark or bright smear of the person leaks into the area around them.
                    sigma = 1.5 + 16 * treatment.blur * min(sw, sh) / 720
                    graph_parts += [f'[{mask_index}:v]scale={sw}:{sh}:flags=bicubic,format=gray,dilation,dilation,negate,format=gbrp,split[inv1][inv2]',
                                    f'[0:v]scale={sw}:{sh},setsar=1,split[fg0][bg0]',
                                    '[bg0]format=gbrp[bgc]', '[bgc][inv1]blend=all_mode=multiply[pre]',
                                    f'[pre]gblur=sigma={sigma:.2f}[preb]', f'[inv2]gblur=sigma={sigma:.2f}[invb]',
                                    # Native divide (255*A/B, clipped). A per-pixel expression here cost ~0.3 s a frame.
                                    # Where B is near zero the pixel is deep inside the subject and the matte covers it.
                                    '[preb][invb]blend=all_mode=divide[bgfill]',
                                    f'[bgfill]format=yuv444p,eq=brightness={-treatment.dim}:saturation={1 - treatment.desaturate},format=gbrp[bgp]',
                                    '[fg0]format=gbrp[fgp]']
                else:
                    graph_parts += [f'[0:v]scale={sw}:{sh},setsar=1,format=gbrp,split[fgp][bgp]']
                if regional:
                    from video.grade import regional_filters
                    graph_parts=[part.replace('[fgp]','[subject_ungraded]').replace('[bgp]','[background_ungraded]') for part in graph_parts]
                    fg=regional_filters(regional.subject) or ['null']
                    bg=regional_filters(regional.background) or ['null']
                    graph_parts += ['[subject_ungraded]'+','.join(fg)+',format=gbrp[fgp]', '[background_ungraded]'+','.join(bg)+',format=gbrp[bgp]']
                graph_parts += ['[bgp][fgp][mk]maskedmerge,' + ','.join(filters) + '[vout]']
                video_args = ['-filter_complex', ';'.join(graph_parts), '-map', '[vout]']
            if still and c.fit == 'blur-fill' and video_args[0] == '-map':
                # Show the whole still over a blurred, slightly dimmed copy of itself instead of
                # cropping away most of a portrait in a landscape frame (or the reverse).
                # The picture sits as a framed card with a soft drop shadow, and the blurred backdrop moves
                # further than the card during a camera move (parallax), which reads as depth rather than a
                # flat picture being zoomed.
                # The static layers (blurred backdrop; card with its shadow) are built once as images, so each frame
                # only moves them. Rebuilding blur and shadow for every frame took ~100 s per 6 s scene.
                tagged = 'out_color_matrix=bt709:out_range=tv'
                # A side card (split layout) is a little smaller and sits lower, clear of the corner logo.
                side = c.card_x != .5
                drop = round(wh * .06) if side else 0
                backdrop_png, card_png = tmp / f'fit-{i}-backdrop.png', tmp / f'fit-{i}-card.png'
                card_layers(src, c.crop, ww, wh, .74 if side else .88, backdrop_png, card_png)
                inputs[inputs.index(str(src))] = str(backdrop_png)
                inputs += ['-loop', '1', '-framerate', fps_arg, '-i', str(card_png)]
                card_input = 2 if not meta.get('has_audio') else 1
                # The blurred backdrop is moved at half size (blur hides the difference, at a quarter of the cost).
                hw, hh = max(2, ww // 4 * 2), max(2, wh // 4 * 2)
                parallax = ''
                if moving and not preview and not anchors:
                    d = c.zoom - c.zoom_start
                    behind = c.model_copy(update=dict(zoom_start=round(1.06 + max(0., -2 * d), 4), zoom=round(1.06 + max(0., 2 * d), 4),
                                                      pan=max(-1., min(1., c.pan * 1.5)), zoom_ease=c.zoom_ease))
                    parallax = ',' + ','.join(camera_filters(behind, [], fps, hw, hh))
                video_args = ['-filter_complex',
                              f"[0:v]scale={hw}:{hh}:{tagged},format=yuv420p,eq=brightness=-0.12:saturation=0.85,setsar=1,fps={fps_arg}{parallax},scale={ww}:{wh}[fit_bg];"
                              f"[{card_input}:v]scale=iw:ih:{tagged},format=yuva420p,setsar=1[fit_card];"
                              f"[fit_bg][fit_card]overlay=W*{c.card_x}-w/2:(H-h)/2+{drop},{','.join(filters[4:])}[vout]", '-map', '[vout]']
            from video.audio import dialogue_filters
            voice=','+','.join(dialogue_filters(project)) if meta.get('has_audio') and dialogue_filters(project) else ''
            ffmpeg(inputs + [*video_args, '-map', '0:a:0' if meta.get('has_audio') else '1:a:0',
                             '-af', atempo(c.speed) + f',volume={c.volume}{voice},aresample=48000,apad',
                             '-t', str(c.duration), *video_encode_args(dict(spec, crf=min(spec['crf'], 16), x264_preset='fast'), high),
                             '-c:a', 'aac', '-b:a', '256k', '-ac', '2', '-ar', '48000', str(out)], job)
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
                t_type = getattr(c, 'transition_type', 'fade') or 'fade'
                if t_type == 'smooth':
                    t_type = 'smoothleft'
                graph += [f'[{vlabel}][{i}:v]xfade=transition={t_type}:duration={overlap}:offset={elapsed-overlap}[{nv}]',
                          f'[{alabel}][{i}:a]acrossfade=d={overlap}[{na}]']
            else:
                graph += [f'[{vlabel}][{alabel}][{i}:v][{i}:a]concat=n=2:v=1:a=1[{nv}][{na}]']
            vlabel, alabel = nv, na
            elapsed += c.duration - overlap
        index = len(intermediates)
        for n, c in enumerate(x for x in project.clips if x.kind in {'overlay', 'title'}):
            source = path_for(c.asset_id) if c.kind == 'overlay' else tmp / f'title-{n}.png'
            if c.kind == 'title':
                title_image(c, source, w,h)
            elif c.logo_backplate:
                with Image.open(source).convert('RGBA') as logo:
                    pad=max(8,round(logo.width*.05))
                    plate=Image.new('RGBA',(logo.width+pad*2,logo.height+pad*2),(7,17,28,215))
                    plate.alpha_composite(logo,(pad,pad))
                    source=tmp/f'logo-plate-{n}.png';plate.save(source)
            # A looped still is only decoded while it is on screen: it starts at its own time (setpts) and
            # ends after its duration (eof_action=pass). Looping every layer for the whole video made
            # the final pass decode and blend ~25 full-frame layers per frame (8+ minutes for 30 s).
            # Full-frame title artwork is cropped to its visible area, so only that area is blended each frame.
            offset = (trim_layer(source, w, h) if c.kind == 'title' and c.scale == 1 and not c.rotation
                      and c.motion in ('none', 'fade', 'slide-up') else None)
            args += ['-loop', '1', '-framerate', fps_arg, '-t', f'{c.duration + 2 / fps:.4f}', '-i', str(source)]
            resize = '' if offset else f'scale={max(2,round(w*c.scale/2)*2)}:-2,'
            filters = f'setpts=PTS+{c.start:.4f}/TB,{resize}format=rgba,colorchannelmixer=aa={c.opacity}'
            if c.rotation:
                filters += f',rotate={c.rotation}*PI/180:c=none:ow=rotw(iw):oh=roth(ih)'
            if c.fade_in:
                filters += f',fade=t=in:st={c.start}:d={c.fade_in}:alpha=1'
            if c.fade_out:
                filters += f',fade=t=out:st={max(c.start,c.start+c.duration-c.fade_out)}:d={c.fade_out}:alpha=1'
            y_expr = f'(H-h)*{c.y}'
            x_expr=f'(W-w)*{c.x}'
            if c.graphic_style and c.motion!='none':
                from video.motion import preset as motion_preset
                box=[v*w/project.canvas.width for v in c.layout_box]
                extra,mx,my=motion_preset(c.motion,c.start,c.start+c.duration,box,w,h,project.motion_intensity,bool(c.fade_in or c.fade_out))
                if extra:filters+=','+','.join(extra)
                x_expr=mx;y_expr=my
            elif c.motion == 'slide-up':
                y_expr += '+' + entrance(c.start, h, project.motion_intensity)
            if offset:
                # Positions of the full-frame artwork (always 0,0 plus any motion), moved to the cropped area.
                moved = c.graphic_style and c.motion != 'none'
                x_expr = f'{offset[0]}+({x_expr})' if moved else str(offset[0])
                y_expr = (f'{offset[1]}+({y_expr})' if moved else
                          f'{offset[1]}+' + entrance(c.start, h, project.motion_intensity) if c.motion == 'slide-up' else str(offset[1]))
            graph += [f'[{index}:v]{filters}[ov{n}]',
                      f"[{vlabel}][ov{n}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{c.start},{c.start+c.duration})':eof_action=pass[vo{n}]"]
            vlabel = f'vo{n}'
            index += 1

        # Render first-class burnt-in caption tracks if present
        for t_idx, track in enumerate(getattr(project, 'caption_tracks', [])):
            if track.get('burn_in', True):
                from video.captions import render_caption_image, track_style, cue_style
                style = track_style(track)
                for s_idx, seg in enumerate(track.get('segments', [])):
                    s_text = seg.get('text', '').strip()
                    s_start = float(seg.get('start', 0.0))
                    s_end = float(seg.get('end', s_start + 2.0))
                    if s_text and s_end > s_start:
                        cap_img = render_caption_image(s_text, w, h, cue_style(track,seg))
                        cap_path = tmp / f'cap-{t_idx}-{s_idx}.png'
                        cap_img.save(cap_path)
                        args += ['-loop', '1', '-framerate', fps_arg, '-t', f'{s_end - s_start + 2 / fps:.4f}', '-i', str(cap_path)]
                        cap_filter, y_expr = f'setpts=PTS+{s_start:.4f}/TB,format=rgba', '0'
                        x_expr='0'
                        if track.get('kind') == 'lower-third' and track.get('motion','none')!='none':
                            from video.motion import preset as motion_preset
                            box=cap_img.info['caption_layout']['box']
                            extra,x_expr,y_expr=motion_preset(track['motion'],s_start,s_end,box,w,h,project.motion_intensity)
                            if extra:cap_filter+=','+','.join(extra)
                        else:
                            offset = trim_layer(cap_path, w, h)
                            if offset:
                                x_expr, y_expr = str(offset[0]), str(offset[1])
                        graph += [f'[{index}:v]{cap_filter}[capov{t_idx}_{s_idx}]',
                                  f"[{vlabel}][capov{t_idx}_{s_idx}]overlay=x='{x_expr}':y='{y_expr}':enable='between(t,{s_start},{s_end})':eof_action=pass[vo_c{t_idx}_{s_idx}]"]
                        vlabel = f'vo_c{t_idx}_{s_idx}'
                        index += 1

        audio_labels = [alabel]
        if audio:
            music_labels = []
            effect_labels = []
            dialogue_labels = [alabel]
            for n, c in enumerate(x for x in project.clips if x.kind == 'audio'):
                args += ['-ss', str(c.trim), '-i', str(path_for(c.asset_id))]
                au_label = f'au{n}'
                cleanup=','.join(dialogue_filters(project))+',' if c.audio_role in {'dialogue','voiceover'} and dialogue_filters(project) else ''
                graph += [f'[{index}:a]{atempo(c.speed)},{cleanup}atrim=duration={c.duration},asetpts=PTS-STARTPTS,'
                          f'volume={c.volume},afade=t=in:d={max(.001,c.fade_in)},'
                          f'afade=t=out:st={max(0,c.duration-c.fade_out)}:d={max(.001,c.fade_out)},'
                          f'adelay={round(c.start*1000)}:all=1[{au_label}]']
                if getattr(c, 'audio_role', '') == 'music':
                    music_labels.append(au_label)
                elif c.audio_role in {'dialogue', 'voiceover'}:
                    dialogue_labels.append(au_label)
                else:
                    effect_labels.append(au_label)
                index += 1

            if music_labels and dialogue_labels and any(c.ducking_priority > 0 for c in project.clips if c.kind == 'audio' and c.audio_role == 'music'):
                d_lab = dialogue_labels[0]
                if len(dialogue_labels) > 1:
                    graph += [''.join(f'[{x}]' for x in dialogue_labels) + f'amix=inputs={len(dialogue_labels)}:normalize=0:duration=longest[dlg]']
                    d_lab = 'dlg'

                m_lab = music_labels[0]
                if len(music_labels) > 1:
                    graph += [''.join(f'[{x}]' for x in music_labels) + f'amix=inputs={len(music_labels)}:normalize=0:duration=longest[msc]']
                    m_lab = 'msc'

                # A filter output can be consumed once: split dialogue for the detector
                # and the audible mix, otherwise FFmpeg fails for multi-track dialogue.
                graph += [f'[{d_lab}]asplit=2[dialogue_detector][dialogue_mix]',
                          f'[{m_lab}][dialogue_detector]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[ducked_msc]',
                          '[dialogue_mix][ducked_msc]amix=inputs=2:normalize=0:duration=longest[mix]']
                alabel = 'mix'
                if effect_labels:
                    graph += ['[mix]' + ''.join(f'[{x}]' for x in effect_labels) + f'amix=inputs={len(effect_labels)+1}:normalize=0:duration=longest[mixfx]']
                    alabel = 'mixfx'
            elif len(dialogue_labels) + len(music_labels) + len(effect_labels) > 1:
                all_audios = dialogue_labels + music_labels + effect_labels
                graph += [''.join(f'[{x}]' for x in all_audios) + f'amix=inputs={len(all_audios)}:normalize=0:duration=longest[mix]']
                alabel = 'mix'
        dest = tmp / ('preview.mp4' if preview else f'export.{container}')
        normalizer = loudnorm_filter(spec) if audio and project.normalize_audio else None
        if normalizer:
            # loudnorm resamples internally; return to 48 kHz before the AAC encoder.
            graph.append(f'[{alabel}]{normalizer},aresample=48000[audio_normalized]')
            alabel='audio_normalized'
        if not audio and ':' not in alabel:
            # A silent export still built an audio chain for its cuts or crossfades; every
            # filter output must be consumed or FFmpeg rejects the whole graph.
            graph.append(f'[{alabel}]anullsink')
        if container == 'mp4':
            graph.append(f'[{vlabel}]format=yuv420p,{REC709_FRAMES}[video_tagged]')
            vlabel = 'video_tagged'
        if graph:
            # Passed as one argv value, never through a shell. Titles are PNG inputs.
            # filter_complex_script was removed in newer FFmpeg builds.
            args += ['-filter_complex', ';'.join(graph)]
        def mapped(label):
            return label if ':' in label else f'[{label}]'
        args += ['-map', mapped(vlabel)]
        if audio:
            args += ['-map', mapped(alabel)] + (audio_encode_args(spec) if container == 'mp4' else ['-c:a', 'libopus', '-ar', '48000'])
        else:
            args += ['-an']
        args += video_encode_args(spec, high) if container == 'mp4' else ['-c:v', 'libvpx-vp9', '-crf', '32', '-b:v', '0', '-deadline', 'realtime', '-cpu-used', '6', '-pix_fmt', 'yuv420p']
        args += ['-r', fps_arg, '-t', str(duration), str(dest)]
        job.update(state='encoding', progress=None, phase='Compositing timeline')
        ffmpeg(args, job, timeout=1200)
        return ingest(dest, dest.name, job)
