"""Bounded background queue with persistent status and cooperative subprocess cancellation."""
import concurrent.futures
import threading
import time
import traceback
from video_storage import DATA, atomic, read, uid, listing, cleanup
from video_ffmpeg import Cancelled

TERMINAL = {'completed', 'failed', 'cancelled'}


class Job:
    def __init__(self, kind):
        self.id = uid()
        self.event = threading.Event()
        self.value = dict(id=self.id, kind=kind, state='queued', created=time.time(), progress=None)
        self.update()

    def update(self, **kwargs):
        self.value.update(kwargs, updated=time.time())
        atomic(DATA / 'jobs' / (self.id + '.json'), self.value)

    def cancelled(self):
        return self.event.is_set()


class Jobs:
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='video')
        self.gpu_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-gpu')
        self.lock = threading.Lock()
        self.active = {}
        cleanup()
        for item in listing('jobs'):
            if item['state'] not in TERMINAL:
                item.update(state='failed', error='Server restarted; submit this job again', updated=time.time())
                atomic(DATA / 'jobs' / (item['id'] + '.json'), item)

    def submit(self, kind, function):
        with self.lock:
            if len(self.active) >= 8:
                raise ValueError('Video queue is full; wait for an existing job')
            job = Job(kind)
            self.active[job.id] = job
            executor = self.gpu_executor if kind in {'text-to-video', 'image-to-video'} else self.executor
            executor.submit(self._execute, job, function)
            return dict(job.value)

    def _execute(self, job, function):
        try:
            if job.cancelled():
                raise Cancelled()
            job.update(state='preparing')
            result = function(job)
            if job.cancelled():
                raise Cancelled()
            job.update(state='completed', result=result, progress=None)
        except Cancelled:
            job.update(state='cancelled', progress=None)
        except Exception as exc:
            (DATA / 'jobs' / (job.id + '.log')).write_text(traceback.format_exc(), encoding='utf-8')
            error = 'Video job failed; see local job diagnostics'
            if isinstance(exc, ValueError):
                error = str(exc) if not any(c in str(exc) for c in ('\\', '/')) else error
            if 'out of memory' in str(exc).lower():
                error = 'GPU out of memory. Close other GPU applications or use Image Animation.'
            job.update(state='failed', error=error, progress=None)
        finally:
            with self.lock:
                self.active.pop(job.id, None)

    def cancel(self, key):
        item = read('jobs', key)
        with self.lock:
            if key in self.active:
                self.active[key].event.set()
                # State remains running until the subprocess is actually stopped.
                self.active[key].update(cancel_requested=True)
        return read('jobs', key)


jobs = Jobs()
