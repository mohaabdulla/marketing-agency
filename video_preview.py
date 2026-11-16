"""Managed still-frame composition previews, explicitly separate from a final color render."""
import tempfile
from pathlib import Path
from PIL import Image,ImageOps
from video_assets import path_for, ingest
from video_measure import frame_at
from video_editor import primary_layout
from video_captions import cue_style,render_caption_image,CaptionStyle
from video_storage import DATA


def stills(project,report,job=None):
    import cv2
    layout,duration=primary_layout(project)
    moments=[max(0,min(duration-.005,v)) for v in [min(1.3,duration*.25),max(.05,duration-min(1.4,duration*.2))]]
    w,h=project.canvas.width,project.canvas.height
    result=[]
    with tempfile.TemporaryDirectory(dir=DATA/'work',prefix='composition-preview-') as folder:
        for index,time in enumerate(moments):
            if job and job.cancelled():
                from video_ffmpeg import Cancelled
                raise Cancelled()
            clip,start,_=next((c,s,o) for c,s,o in layout if s<=time<s+c.duration)
            frame=frame_at(path_for(clip.asset_id),clip.trim+(time-start)*clip.speed)
            if frame is None:continue
            image=ImageOps.fit(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),(w,h)).convert('RGBA')
            if clip.zoom>1:
                zw,zh=round(w/clip.zoom),round(h/clip.zoom)
                x=max(0,min(w-zw,round(clip.zoom_x*w-zw/2)));y=max(0,min(h-zh,round(clip.zoom_y*h-zh/2)))
                image=image.crop((x,y,x+zw,y+zh)).resize((w,h),Image.Resampling.LANCZOS)
            for graphic in project.clips:
                if graphic.kind=='video' or not graphic.start<=time<graphic.start+graphic.duration:continue
                if graphic.kind=='title' and graphic.graphic_style:
                    style=CaptionStyle.model_validate({k:v for k,v in graphic.graphic_style.items() if k not in {'canvas_width','canvas_height'}})
                    image.alpha_composite(render_caption_image(graphic.text,w,h,style))
                elif graphic.kind=='overlay' and graphic.layout_box:
                    art=Image.open(path_for(graphic.asset_id)).convert('RGBA')
                    if graphic.logo_backplate:
                        pad=max(8,round(art.width*.05));plate=Image.new('RGBA',(art.width+2*pad,art.height+2*pad),(7,17,28,215));plate.alpha_composite(art,(pad,pad));art=plate
                    x0,y0,x1,y1=map(round,graphic.layout_box)
                    image.alpha_composite(art.resize((max(1,x1-x0),max(1,y1-y0)),Image.Resampling.LANCZOS),(x0,y0))
            for track in project.caption_tracks:
                for segment in track.get('segments',[]):
                    if segment['start']<=time<segment['end']:
                        image.alpha_composite(render_caption_image(segment['text'],w,h,cue_style(track,segment)))
            path=Path(folder)/f'composition-{index+1}.png';image.convert('RGB').save(path)
            asset=ingest(path,path.name,job)
            result.append(dict(asset=asset,time=time,notice='Actual graphic layout over a decoded source frame. Final regional color/background processing and animation are not represented in this composition-only still.'))
    return result
