"""Cached non-identifying face trajectories and bounded, eased framing keyframes."""
import hashlib
import json
import math
from pathlib import Path
from video_assets import path_for,read
from video_storage import DATA,atomic


def track(asset_id,job=None,sample_fps=2):
    import cv2
    source=path_for(asset_id);asset=read('assets',asset_id)
    cascade_path=Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'
    hasher=hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
    digest=hasher.hexdigest()
    version=hashlib.sha256(cascade_path.read_bytes()).hexdigest()[:12]
    cache=DATA/'analysis'/f'track-v1-{digest}-{cv2.__version__}-{version}-{sample_fps}.json'
    if cache.is_file():return json.loads(cache.read_text(encoding='utf-8'))
    detector=cv2.CascadeClassifier(str(cascade_path));capture=cv2.VideoCapture(str(source))
    points=[];multiple=0;last=None
    try:
        for index in range(max(1,int(asset['duration']*sample_fps))):
            if job and job.cancelled():
                from video_ffmpeg import Cancelled
                raise Cancelled()
            time=index/sample_fps;capture.set(cv2.CAP_PROP_POS_MSEC,time*1000);ok,frame=capture.read()
            if not ok:continue
            ratio=min(1,480/max(frame.shape[:2]));frame=cv2.resize(frame,None,fx=ratio,fy=ratio)
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);h,w=gray.shape
            boxes=detector.detectMultiScale(gray,scaleFactor=1.1,minNeighbors=5,minSize=(24,24))
            if len(boxes)>1:multiple+=1
            if not len(boxes):continue
            def distance(box):
                x,y,bw,bh=box;return ((x+bw/2)/w-last['x'])**2+((y+bh/2)/h-last['y'])**2 if last else -bw*bh/(w*h)
            x,y,bw,bh=map(int,min(boxes,key=distance))
            cx,cy=(x+bw/2)/w,(y+bh/2)/h
            if last:
                cx=last['x']*.65+cx*.35;cy=last['y']*.65+cy*.35
            point=dict(time=round(time,3),x=round(cx,5),y=round(cy,5),box=[x/w,y/h,(x+bw)/w,(y+bh)/h],confidence=.8 if len(boxes)==1 else .4)
            points.append(point);last=point
    finally:capture.release()
    result=dict(source_sha=digest,detector_version=version,sample_fps=sample_fps,points=points,multiple_face_samples=multiple,
        requires_review=bool(multiple),hands=None,identity='NOT_INFERRED',method='Repeated local Haar face measurements with exponential smoothing; no identity recognition',
        limitation='Profiles/occlusion may be missed. Multiple faces need user selection; no hand or gesture tracker is claimed.')
    atomic(cache,result);return result


def keyframes(tracking,start,end,speed=1):
    if tracking.get('requires_review'):return []
    points=[p for p in tracking.get('points',[]) if start-.01<=p['time']<=end+.01]
    if len(points)<2:return []
    stride=max(1,math.ceil(len(points)/20));points=points[::stride]
    return [dict(time=round(max(0,(p['time']-start)/speed),4),x=p['x'],y=p['y']) for p in points]


def expression(points,key,variable,default):
    if not points:return str(float(default))
    value=str(float(points[-1][key]))
    for a,b in reversed(list(zip(points,points[1:]))):
        span=max(.001,b['time']-a['time']);u=f'min(1,max(0,({variable}-{a["time"]:.4f})/{span:.4f}))'
        ease=f'({u}*{u}*(3-2*{u}))'
        segment=f'({a[key]:.5f}+({b[key]-a[key]:.5f})*{ease})'
        value=f'if(lt({variable},{b["time"]:.4f}),{segment},{value})'
    return value
