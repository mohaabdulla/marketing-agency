"""Bounded FFmpeg execution: no shell, network protocols or user input paths."""
import json
import os
import shutil
import subprocess
import signal
import tempfile
import time
from pathlib import Path
from video_storage import DATA, ROOT


def binary(name):
    configured = os.getenv(name.upper() + '_BIN')
    candidates = [configured, shutil.which(name), str(ROOT / 'output/video-tools' / (name + ('.exe' if os.name == 'nt' else '')))]
    if name == 'ffmpeg':
        try:
            import imageio_ffmpeg
            candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
        except ImportError:
            pass
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


class Cancelled(Exception):
    pass


def stop_process(process):
    """Terminate only the process tree launched for this job, including imageio's encoder."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,shell=False,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run(args, job=None, timeout=600, executable='ffmpeg'):
    exe = binary(executable)
    if not exe:
        raise ValueError(f'{executable} missing. Install FFmpeg and FFprobe; see README Video Studio.')
    with tempfile.TemporaryFile(dir=DATA / 'work') as log:
        process = subprocess.Popen([exe, *map(str, args)], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   shell=False, start_new_session=os.name!='nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        checked = started
        try:
            while process.poll() is None:
                if job and job.cancelled():
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    raise ValueError('Media processing time limit exceeded')
                if time.monotonic() - checked > 2:
                    from video_storage import space
                    space()
                    checked = time.monotonic()
                time.sleep(.08)
            log.seek(0)
            output = log.read(2 * 1024**2).decode('utf-8', errors='replace')
            if process.returncode:
                # Detailed diagnostics stay local, never in public error responses.
                (DATA / 'work/last-ffmpeg-error.log').write_text(output, encoding='utf-8')
                if job:
                    (DATA/'jobs'/(job.id+'.ffmpeg.log')).write_text(output,encoding='utf-8')
                raise ValueError('Media processing failed; see local video diagnostics')
            return output
        finally:
            if process.poll() is None:
                stop_process(process)
            process.wait()


def probe(path):
    result = json.loads(run(['-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams',
                             '-of', 'json', str(path)], timeout=20, executable='ffprobe'))
    streams = result.get('streams', [])
    v = next((s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), {})
    a = next((s for s in streams if s.get('codec_type') == 'audio'), {})
    duration = float(result.get('format', {}).get('duration') or v.get('duration') or 0)
    rate = v.get('avg_frame_rate', '0/1').split('/')
    fps = float(rate[0]) / max(float(rate[-1]), 1)
    return dict(duration=duration, width=int(v.get('width', 0)), height=int(v.get('height', 0)),
                fps=fps, video_codec=v.get('codec_name'), audio_codec=a.get('codec_name'), has_audio=bool(a))


def ffmpeg(args, job=None, timeout=600):
    bounded = []
    for value in args:
        if value == '-i':
            bounded += ['-threads','1']
        bounded.append(value)
    bounded = bounded[:-1] + ['-threads','2',bounded[-1]]
    return run(['-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-threads', '2',
                '-filter_threads', '1', '-filter_complex_threads', '1', *bounded], job, timeout)
