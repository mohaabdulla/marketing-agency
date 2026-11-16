"""Transfer measured pacing/energy/color statistics, never a reference's media or copy."""
from video_analysis import analyze_asset
from video_assets import read,path_for
from video_measure import frame_at


def analyze(asset_id,job=None):
    import cv2
    import numpy as np
    asset=read('assets',asset_id)
    if asset['kind']!='video':raise ValueError('Choose a video as the style reference')
    analysis=analyze_asset(asset_id,job=job)
    lengths=[s.end-s.start for s in analysis.shots]
    colors=[]
    for fraction in (.2,.5,.8):
        if job and job.cancelled():
            from video_ffmpeg import Cancelled
            raise Cancelled()
        frame=frame_at(path_for(asset_id),asset['duration']*fraction)
        if frame is not None:
            hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
            colors.append(dict(saturation=float(np.median(hsv[:,:,1]))/255,luminance=float(np.median(hsv[:,:,2]))/255,
                               red_blue_balance=float(frame[:,:,2].mean()-frame[:,:,0].mean())/255))
    color={k:round(sum(c[k] for c in colors)/len(colors),4) for k in colors[0]} if colors else None
    return dict(asset_id=asset_id,source_sha=analysis.source_hash,analysis_version=analysis.analysis_version,
                average_shot_seconds=round(sum(lengths)/len(lengths),3) if lengths else None,
                cuts_per_minute=round(max(0,len(lengths)-1)/max(.01,asset['duration'])*60,3),
                motion_energy=round(sum(s.motion_score or 0 for s in analysis.shots)/max(1,len(analysis.shots)),3),color=color,
                caption_hierarchy=None,graphic_density=None,zoom_frequency=None,hook_semantics=None,cta_structure=None,music_energy=None,
                not_measured=['caption font/hierarchy/OCR','graphic density','semantic hook/CTA','music classification','zoom tracking'],
                notice='Only numeric shot, motion and color statistics transfer. No imagery, text, music or other copyrighted assets are copied.')


def pacing_threshold(reference,current):
    average=reference.get('average_shot_seconds')
    return max(.45,min(.95,current*(.8 if average and average<2.5 else 1.2 if average and average>6 else 1.)))
