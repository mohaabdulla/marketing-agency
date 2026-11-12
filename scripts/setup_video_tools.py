"""Opt-in Windows FFmpeg/FFprobe installer. Linux: sudo apt install ffmpeg fonts-dejavu-core."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Explicitly download the Windows GPL FFmpeg essentials build')
    args=parser.parse_args()
    if not args.install:
        parser.print_help();return
    if os.name!='nt':
        raise SystemExit('Use your system package manager: sudo apt install ffmpeg fonts-dejavu-core')
    target=ROOT/'output/video-tools';target.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(target).free<1024**3:
        raise SystemExit('Free at least 1 GB for tool installation')
    checksum=requests.get(SOURCE+'.sha256',timeout=30);checksum.raise_for_status()
    expected=checksum.text.split()[0].lower()
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
        raise SystemExit('Invalid publisher checksum; installation stopped')
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        archive=Path(tmp)/'ffmpeg.zip';digest=hashlib.sha256();size=0
        with requests.get(SOURCE,stream=True,timeout=(15,120)) as response:
            response.raise_for_status()
            with archive.open('wb') as out:
                for chunk in response.iter_content(1024**2):
                    size+=len(chunk)
                    if size>300*1024**2:raise ValueError('Tool archive exceeds size limit')
                    digest.update(chunk);out.write(chunk)
        if digest.hexdigest()!=expected:raise ValueError('Publisher checksum mismatch; retry after the release update completes')
        with zipfile.ZipFile(archive) as bundle:
            for name in ['ffmpeg.exe','ffprobe.exe']:
                member=next(n for n in bundle.namelist() if n.endswith('/bin/'+name))
                # Never extract archive paths; only write the two explicitly named binaries.
                (target/name).write_bytes(bundle.read(member))
        (target/'provenance.json').write_text(json.dumps(dict(source=SOURCE,sha256=expected,license='GPL build; see FFmpeg legal notes'),indent=2))
    print('Installed FFmpeg and FFprobe in output/video-tools. No PATH changes made.')


if __name__=='__main__':main()
