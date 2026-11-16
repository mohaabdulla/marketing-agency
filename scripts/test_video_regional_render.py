"""Actual regional color, easing/reframing pixels, speech processing and rubric persistence."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TEMP=tempfile.TemporaryDirectory(prefix='lexnis-regional-render-')
os.environ['VIDEO_DATA_DIR']=TEMP.name
from video_assets import ingest,path_for,annotate
from video_editor import render
from video_projects import Project,Clip,Canvas,ColorPipeline,RegionalGrade
from video_jobs import Job
from video_ffmpeg import ffmpeg
from video_measure import frame_at
from video_review import set_rubric,RubricRequest,review_record
from unittest.mock import patch
import numpy as np


class RealRenderTests(unittest.TestCase):
    def test_graphic_motion_presets_render_and_reveal(self):
        from video_captions import CaptionStyle,render_caption_image
        source=Path(TEMP.name)/'motion-source.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=gray:s=320x240:r=24:d=1.2','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
        asset=ingest(source,source.name)
        style=CaptionStyle(id='title',name='Title',font_size_px=24,reference_width=320,y_pct=.5,background='#152335ff',padding=8)
        box=render_caption_image('Team Update',320,240,style).info['caption_layout']['box']
        for motion in ('fade','slide-up','masked-reveal','soft-scale'):
            title=Clip(kind='title',text='Team Update',duration=1.2,motion=motion,layout_box=box,graphic_style=dict(style.model_dump(),canvas_width=320,canvas_height=240))
            project=Project(canvas=Canvas(width=320,height=240),clips=[Clip(asset_id=asset['id'],duration=1.2),title])
            result=render(project,Job('export'),audio=False)
            before=frame_at(path_for(asset['id']),.6).astype('float32')
            late=frame_at(path_for(result['id']),.6).astype('float32')
            changed=np.abs(late-before).max(axis=2)>30
            self.assertGreater(changed.sum(),1500,motion)
            if motion=='masked-reveal':
                early=frame_at(path_for(result['id']),.08).astype('float32')
                ys=np.nonzero(np.abs(early-before).max(axis=2)>30)[0]
                full=np.nonzero(changed)[0]
                self.assertLess(ys.max()-ys.min(),(full.max()-full.min())*.75)

    def test_continuous_crop_reframes_measured_anchor_positions(self):
        source=Path(TEMP.name)/'two-regions.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=red:s=640x360:r=24:d=3,drawbox=x=320:y=0:w=320:h=360:color=blue:t=fill','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
        original=source.read_bytes();asset=ingest(source,source.name)
        project=Project(canvas=Canvas(width=202,height=360),clips=[Clip(asset_id=asset['id'],duration=3,reframe_keyframes=[dict(time=0,x=.2,y=.5),dict(time=3,x=.8,y=.5)])])
        result=render(project,Job('export'),audio=False)
        first=frame_at(path_for(result['id']),.2).mean(axis=(0,1));last=frame_at(path_for(result['id']),2.8).mean(axis=(0,1))
        self.assertGreater(first[2]-first[0],150)
        self.assertGreater(last[0]-last[2],150)
        middle_a=frame_at(path_for(result['id']),1.45).mean(axis=(0,1));middle_b=frame_at(path_for(result['id']),1.55).mean(axis=(0,1))
        self.assertLess(np.abs(middle_a-middle_b).max(),70)
        self.assertEqual(source.read_bytes(),original)

    def test_subject_grade_does_not_wash_out_the_background(self):
        source=Path(TEMP.name)/'backlit.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=0xb9c5d5:s=320x240:r=24:d=2,drawbox=x=110:y=65:w=100:h=130:color=0x34303b:t=fill','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
        mask=Path(TEMP.name)/'mask.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=black:s=320x240:r=12:d=2,drawbox=x=110:y=65:w=100:h=130:color=white:t=fill','-c:v','libx264','-pix_fmt','yuv420p',str(mask)])
        asset=ingest(source,source.name)
        project=Project(canvas=Canvas(width=320,height=240),clips=[Clip(asset_id=asset['id'],duration=2)],
            color_pipeline=ColorPipeline(source_asset_id=asset['id'],regional=True,subject=RegionalGrade(gamma=1.15,shadows=.08),background=RegionalGrade()))
        with patch('video_segmentation.cached_mask',return_value=(mask,{'subject_found':True})):
            result=render(project,Job('export'),audio=False)
        before=frame_at(path_for(asset['id']),1).astype('float32');after=frame_at(path_for(result['id']),1).astype('float32')
        self.assertGreater(after[90:170,130:190].mean()-before[90:170,130:190].mean(),3)
        self.assertLess(np.abs(after[20:60,20:100]-before[20:60,20:100]).mean(),2)

    def test_review_rubric_is_per_render_and_never_automatically_scored(self):
        # Persistence is real; no model, render-quality judgment or fabricated identity.
        from PIL import Image
        source=Path(TEMP.name)/'review.png';Image.new('RGB',(128,128),'black').save(source)
        asset=ingest(source,source.name)
        annotate(asset,render_revision_id='b'*32,edit_report={'caption_state':'none'})
        self.assertNotIn('rubric',review_record(asset['id']))
        record=set_rubric(asset['id'],RubricRequest(scores={'composition':3,'lighting':4},notes='Human review fixture'))
        self.assertEqual(record['rubric']['render_revision_id'],'b'*32)
        self.assertEqual(review_record(asset['id'])['rubric']['scores'],{'composition':3,'lighting':4})
        self.assertNotIn('overall_score',record['rubric'])


if __name__=='__main__':unittest.main(verbosity=2)
