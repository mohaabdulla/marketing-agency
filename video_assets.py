"""Validated uploads and direct reuse of existing campaign outputs."""
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit, unquote
from PIL import Image
from video_storage import DATA, ROOT, MAX_UPLOAD, atomic, uid, read, space
from video_ffmpeg import probe, ffmpeg

IMAGES = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEOS = {'.mp4', '.mov', '.webm', '.gif'}
AUDIO = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}
EXTENSIONS = IMAGES | VIDEOS | AUDIO


def path_for(asset_id):
    asset = read('assets', asset_id)
    path = DATA / 'assets' / asset['filename']
    if path.parent != DATA / 'assets' or not path.is_file():
        raise FileNotFoundError('Media asset missing')
    return path


def ingest(path, name, job=None, move=False):
    ext = Path(name).suffix.lower()
    if ext not in EXTENSIONS or path.stat().st_size > MAX_UPLOAD:
        raise ValueError('Unsupported media type or file exceeds upload limit')
    space(path.stat().st_size if not move else 0)
    with path.open('rb') as f:
        head = f.read(32)
    if head.startswith((b'#EXTM3U', b'<', b'<!', b'<?')):
        raise ValueError('Playlists and document formats are not accepted')
    if ext in IMAGES:
        with Image.open(path) as im:
            formats = {'JPEG':{'.jpg','.jpeg'},'PNG':{'.png'},'WEBP':{'.webp'}}
            if ext not in formats.get(im.format,set()):
                raise ValueError('Image signature does not match the extension')
            width, height = im.size
            if width > 8192 or height > 8192 or width * height > 32_000_000:
                raise ValueError('Image dimensions exceed limits')
            im.verify()
        meta = dict(width=width, height=height, duration=0, fps=0, has_audio=False)
        kind = 'image'
    else:
        if ext in {'.mp4', '.mov', '.m4a'} and b'ftyp' not in head:
            raise ValueError('Invalid MP4/MOV signature')
        if ext == '.webm' and not head.startswith(b'\x1aE\xdf\xa3'):
            raise ValueError('Invalid WebM signature')
        if ext == '.gif' and not head.startswith((b'GIF87a', b'GIF89a')):
            raise ValueError('Invalid GIF signature')
        if ext == '.wav' and not (head.startswith(b'RIFF') and head[8:12] == b'WAVE'):
            raise ValueError('Invalid WAV signature')
        if ext == '.flac' and not head.startswith(b'fLaC'):
            raise ValueError('Invalid FLAC signature')
        if ext == '.ogg' and not head.startswith(b'OggS'):
            raise ValueError('Invalid OGG signature')
        meta = probe(path)
        if not 0 < meta['duration'] <= 3600 or max(meta['width'], meta['height']) > 4096:
            raise ValueError('Media duration or resolution exceeds limits')
        video_codecs = {'h264', 'hevc', 'vp8', 'vp9', 'av1', 'gif', 'mpeg4', 'prores', 'mjpeg'}
        audio_codecs = {'aac', 'mp3', 'pcm_s16le', 'pcm_s24le', 'pcm_f32le', 'vorbis', 'opus', 'flac', 'alac'}
        if meta['video_codec'] and meta['video_codec'] not in video_codecs:
            raise ValueError('Unsupported video codec')
        if meta['audio_codec'] and meta['audio_codec'] not in audio_codecs:
            raise ValueError('Unsupported audio codec')
        kind = 'audio' if ext in AUDIO else 'video'
        if (kind == 'video' and not meta['video_codec']) or (kind == 'audio' and not meta['audio_codec']):
            raise ValueError('Media streams do not match file extension')
        if kind == 'video' and (not meta['width'] or not meta['height'] or meta['fps'] > 120):
            raise ValueError('Unsupported video dimensions or frame rate')
    asset_id = uid()
    dest = DATA / 'assets' / (asset_id + ext)
    if move:
        shutil.move(str(path), dest)
    else:
        shutil.copyfile(path, dest)
    item = dict(id=asset_id, name=Path(name.replace('\\', '/')).name[:160], filename=dest.name, kind=kind,
                size=dest.stat().st_size, created=time.time(), url=f'/api/video/media/{asset_id}', **meta)
    if kind == 'image':
        with Image.open(dest) as im:
            im.thumbnail((320, 240))
            im.convert('RGB').save(dest.with_suffix('.thumb.jpg'))
        item['thumbnail_url'] = f'/api/video/thumbnails/{asset_id}'
    else:
        try:
            args = ['-protocol_whitelist','file,pipe','-i',str(dest)]
            if kind == 'video':
                args += ['-vf','scale=320:240:force_original_aspect_ratio=decrease']
            else:
                args += ['-filter_complex','aformat=channel_layouts=mono,showwavespic=s=320x80:colors=0x65e7f4']
            ffmpeg(args+['-frames:v','1','-update','1',str(dest.with_suffix('.thumb.jpg'))],job,timeout=12)
            item['thumbnail_url'] = f'/api/video/thumbnails/{asset_id}'
        except ValueError:
            pass  # Optional thumbnail failure must not hide a validated source.
    atomic(DATA / 'assets' / (asset_id + '.json'), item)
    return item


def annotate(asset, **metadata):
    asset.update(metadata)
    atomic(DATA/'assets'/(asset['id']+'.json'),asset)
    return asset


def existing(url):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Use an application media URL')
    value = unquote(parsed.path)
    for prefix, directory in [('/renders/', ROOT / 'output/renders'), ('/uploads/', ROOT / 'output/uploads'),
                              ('/static/assets/', ROOT / 'static/assets')]:
        if value.startswith(prefix):
            name = value[len(prefix):]
            if not name or '/' in name or '\\' in name or '..' in name:
                break
            path = (directory / name).resolve()
            if path.parent == directory.resolve() and path.is_file():
                return ingest(path, name)
    raise ValueError('Source must be an existing campaign image, GIF, or video')
