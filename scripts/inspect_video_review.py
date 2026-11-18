"""Decode a real edit and create a before/after review sheet and pixel measurements."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
from PIL import Image,ImageDraw
from video.measure import frame_at
from video.grade import light_stats,hue_difference
from video.ffmpeg import probe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path)
    parser.add_argument('source',type=Path)
    args=parser.parse_args()
    evidence=json.loads(args.result.read_text(encoding='utf-8'))
    result=evidence['result'];report=result['edit_report'];output=args.result.parent/'edited.mp4'
    source_sha=hashlib.sha256(args.source.read_bytes()).hexdigest()
    if source_sha!=evidence['source_sha256']:raise ValueError('Source SHA does not match the review record')
    width,height=result['width'],result['height']
    sheet=Image.new('RGB',(width*2,(height+32)*2),'#101820')
    measurements=[]
    for row,time in enumerate([min(2.5,result['duration']*.2),min(10.5,result['duration']*.7)]):
        original=time
        for cut in sorted(report['cuts'],key=lambda c:c['start']):
            if original+.001>=cut['start']:original+=cut['end']-cut['start']
        before,after=frame_at(args.source,original),frame_at(output,time)
        if before is None or after is None:raise ValueError('A review frame could not be decoded')
        # These sample times are outside the purpose-driven emphasis shot for this fixture.
        # Metrics stay explicitly approximate if another source is reframed at the samples.
        first,second=light_stats(before,report.get('face')),light_stats(after,report.get('face'))
        def background_sharpness(frame):
            roi=frame[int(height*.12):int(height*.30),int(width*.04):int(width*.25)]
            return round(float(cv2.Laplacian(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var()),2)
        measurements.append(dict(edited_time=time,source_time=original,before=first,after=second,
            face_luma_change=round(second['face_luma']-first['face_luma'],4) if first['face_luma'] is not None and second['face_luma'] is not None else None,
            face_hue_shift=hue_difference(first['face_hue'],second['face_hue']) if first['face_hue'] is not None and second['face_hue'] is not None else None,
            upper_left_roi_sharpness=dict(source=background_sharpness(before),edited=background_sharpness(after))))
        for column,(frame,label) in enumerate([(before,'Original'),(after,'Edited')]):
            image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((width,height))
            sheet.paste(image,(column*width,row*(height+32)+32))
            ImageDraw.Draw(sheet).text((column*width+10,row*(height+32)+9),f'{label} / {time:.2f}s',fill='white')
    sheet.save(args.result.parent/'before-after.png')
    inspection=dict(source_sha256=source_sha,source_unchanged=hashlib.sha256(args.source.read_bytes()).hexdigest()==source_sha,
        output_metadata=probe(output),samples=measurements,
        caveat='Face rectangles are approximate and are not transformed for reframing. The upper-left ROI is a diagnostic region, not automatic subject/background classification.')
    (args.result.parent/'inspection.json').write_text(json.dumps(inspection,indent=2),encoding='utf-8')
    print(json.dumps(dict(source_unchanged=inspection['source_unchanged'],samples=measurements),indent=2))


if __name__=='__main__':main()
