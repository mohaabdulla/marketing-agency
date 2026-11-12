"""Managed video storage. Public APIs use UUIDs, never client filesystem paths."""
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('VIDEO_DATA_DIR', str(ROOT / 'output/video'))).resolve()
LOCK = threading.RLock()
MAX_UPLOAD = int(os.getenv('VIDEO_MAX_UPLOAD_MB', '256')) * 1024**2
QUOTA = int(os.getenv('VIDEO_DISK_QUOTA_GB', '8')) * 1024**3
for folder in ('assets', 'projects', 'jobs', 'work'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)


def uid():
    return uuid.uuid4().hex


def identifier(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid identifier')
    return value


def atomic(path, value):
    with LOCK:
        temp = path.with_name(path.name + '.' + uid() + '.tmp')
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def read(folder, key):
    path = DATA / folder / (identifier(key) + '.json')
    with LOCK:
        if not path.is_file():
            raise FileNotFoundError('Item not found')
        return json.loads(path.read_text(encoding='utf-8'))


def listing(folder):
    with LOCK:
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in (DATA / folder).glob('*.json')],
                      key=lambda x: x.get('updated', x.get('created', 0)), reverse=True)


def space(required=0):
    used = 0
    for p in DATA.rglob('*'):
        try:
            if p.is_file():
                used += p.stat().st_size
        except FileNotFoundError:
            pass  # Another completed job may be removing its temporary work directory.
    if used + required > QUOTA or shutil.disk_usage(DATA).free < required + 512 * 1024**2:
        raise ValueError('Video storage limit reached or insufficient free disk space')


def cleanup():
    # Retain job metadata and originals; only abandoned work directories are expired.
    for p in (DATA / 'work').iterdir():
        if time.time() - p.stat().st_mtime > 86400:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
