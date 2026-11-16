"""Measured soft-boundary proxies; consistency never certifies optical matting quality."""
import hashlib
import json
from video_storage import DATA,atomic
from video_measure import frame_at


def assess(mask_path,source_path,duration,face=None):
    import cv2
    import numpy as np
    hasher=hashlib.sha256()
    for path in (mask_path,source_path):
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
    cache=DATA/'analysis'/('matte-quality-v1-'+hasher.hexdigest()+'.json')
    if cache.is_file():return json.loads(cache.read_text(encoding='utf-8'))
    samples=[]
    for fraction in (.15,.5,.85):
        time=duration*fraction
        matte=frame_at(mask_path,time);frame=frame_at(source_path,time)
        if matte is None or frame is None:continue
        alpha=cv2.cvtColor(matte,cv2.COLOR_BGR2GRAY)
        gray=cv2.cvtColor(cv2.resize(frame,(alpha.shape[1],alpha.shape[0])),cv2.COLOR_BGR2GRAY).astype('float32')/255
        binary=(alpha>127).astype('uint8')
        edge=cv2.morphologyEx(binary,cv2.MORPH_GRADIENT,np.ones((3,3),'uint8'))>0
        gradient=cv2.magnitude(cv2.Sobel(gray,cv2.CV_32F,1,0),cv2.Sobel(gray,cv2.CV_32F,0,1))
        uncertain=(alpha>25)&(alpha<230)
        head_uncertain=None
        if face:
            x0=max(0,int((face['x']-.2*face['width'])*alpha.shape[1]));x1=min(alpha.shape[1],int((face['x']+1.2*face['width'])*alpha.shape[1]))
            y0=max(0,int((face['y']-.5*face['height'])*alpha.shape[0]));y1=min(alpha.shape[0],int((face['y']+.5*face['height'])*alpha.shape[0]))
            if x1>x0 and y1>y0:head_uncertain=round(float(uncertain[y0:y1,x0:x1].mean()),5)
        count,_,stats,_=cv2.connectedComponentsWithStats(binary,8)
        total=float(binary.sum())
        largest=float(stats[1:,cv2.CC_STAT_AREA].max())/total if count>1 and total else None
        samples.append(dict(time=round(time,3),uncertain_edge_share=round(float(uncertain.mean()),5),head_region_uncertainty=head_uncertain,
                            boundary_source_gradient=round(float(gradient[edge].mean()),5) if edge.any() else None,
                            largest_subject_component_share=round(largest,5) if largest is not None else None))
    result=dict(samples=samples,coarse_mask='SEGMENTATION_PROBABILITY',refined_mask='PROVIDER_DEPENDENT',
        alpha_matte='SOFT_PROBABILITY_NOT_OPTICAL_ALPHA',hair_edge_confidence=None,motion_edge_confidence=None,
        hair_ears_hands_fingers_motion_blur='HUMAN_REVIEW_REQUIRED',
        notice='Boundary uncertainty, fragmentation and image gradients are measurable proxies. They do not prove hair accuracy, correct transparency or natural compositing. Temporal IoU is assessed separately.')
    atomic(cache,result);return result
