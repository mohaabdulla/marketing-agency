"""OS file lock shared by local image and video subprocess launchers."""
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def gpu_slot(cancelled=lambda: False, timeout=1800):
    path = Path(__file__).resolve().parent / 'output/local-gpu.lock'
    path.parent.mkdir(exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0')
            handle.flush()
        started = time.monotonic()
        while True:
            if cancelled():
                from video_ffmpeg import Cancelled
                raise Cancelled()
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() - started > timeout:
                    raise ValueError('GPU is busy; retry after the current image or video job')
                time.sleep(.2)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
