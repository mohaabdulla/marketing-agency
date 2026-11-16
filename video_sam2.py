"""Optional operator-installed SAM 2.1 image-anchor refinement, with existing temporal flow.

This is SAM image refinement, not SAM's recurrent video tracker and not optical alpha matting.
No checkpoint is downloaded. GPU memory is released after each complete masking job.
"""
import os
from pathlib import Path


class Sam2Provider:
    model='sam2_tiny'
    can_propagate=True
    preferred_analysis_edge=960
    def __init__(self,checkpoint,coarse):
        self.checkpoint=Path(checkpoint)
        self.coarse=coarse
        self.device=os.getenv('AGENCY_SAM2_DEVICE','cpu')
        if self.device not in {'cpu','cuda'}:raise ValueError('SAM 2 device must be cpu or cuda')
        self.uses_gpu=self.device=='cuda'
        self.predictor=None
        self.last_score=None

    def mask(self,rgb):
        import numpy as np
        import torch
        if self.predictor is None:
            if self.uses_gpu and not torch.cuda.is_available():raise ValueError('Configured SAM 2 GPU runtime is unavailable; use CPU or the U-2-Net fallback.')
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            # Local checkpoint path and package configuration only; no HF/network loader.
            model=build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(self.checkpoint),device=self.device)
            self.predictor=SAM2ImagePredictor(model)
        rough=self.coarse.mask(rgb)
        ys,xs=np.nonzero(rough>127)
        if not len(xs):return rough
        box=np.array([xs.min(),ys.min(),xs.max(),ys.max()],dtype='float32')
        with torch.inference_mode():
            self.predictor.set_image(rgb)
            logits,scores,_=self.predictor.predict(box=box,multimask_output=True,return_logits=True)
        index=int(np.argmax(scores));self.last_score=float(scores[index])
        soft=1/(1+np.exp(-np.clip(logits[index],-20,20)))
        return (soft*255).astype('uint8')

    def release(self):
        self.predictor=None
        if self.uses_gpu:
            import torch
            torch.cuda.empty_cache()
