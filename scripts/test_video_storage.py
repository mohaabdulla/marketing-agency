"""Windows sharing-lock regression and recovery of a job whose worker already stopped."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-storage-')
os.environ['VIDEO_DATA_DIR']=TEMP.name
from video.storage import atomic,DATA,uid
from video.jobs import jobs


class StorageTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_atomic_save_survives_a_real_temporary_read_lock(self):
        import ctypes
        from ctypes import wintypes
        target=Path(TEMP.name)/'locked.json'
        atomic(target,{'version':1})
        create=ctypes.windll.kernel32.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        close=ctypes.windll.kernel32.CloseHandle
        close.argtypes=[wintypes.HANDLE]
        handle=create(str(target),0x80000000,3,None,3,0x80,None) # read/write sharing, deliberately no DELETE sharing
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        self.assertEqual(json.loads(target.read_text()),{'version':1})
        def release():
            time.sleep(.15)
            close(handle)
        thread=threading.Thread(target=release);thread.start()
        atomic(target,{'version':2})
        thread.join()
        self.assertEqual(json.loads(target.read_text()),{'version':2})
        self.assertFalse(list(target.parent.glob('*.tmp')))

    def test_orphaned_job_cannot_stay_running_forever(self):
        key=uid()
        atomic(DATA/'jobs'/(key+'.json'),dict(id=key,state='running',phase='Analyzing speech'))
        state=jobs.status(key)
        self.assertEqual(state['state'],'failed')
        self.assertIn('worker stopped',state['error'])


if __name__=='__main__':unittest.main(verbosity=2)
