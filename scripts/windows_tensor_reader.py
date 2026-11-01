"""Avoid Windows Safetensors mmap access violations in the isolated worker.

Use the public `pread` backend before Diffusers/Transformers import safe_open.
No installed library files or the server's Python environment are modified.
"""
import sys


def pread_reader(original):
    def open_tensor_file(*args, **kwargs):
        # load_file passes its default backend='mmap' explicitly; override it too.
        kwargs['backend'] = 'pread'
        return original(*args, **kwargs)
    open_tensor_file._lexnis_pread = True
    return open_tensor_file


def configure_windows_tensor_reader():
    if sys.platform != 'win32':
        return 'mmap'
    import safetensors
    import safetensors.torch
    if not getattr(safetensors.safe_open, '_lexnis_pread', False):
        reader = pread_reader(safetensors.safe_open)
        safetensors.safe_open = reader
        safetensors.torch.safe_open = reader
    return 'pread'
