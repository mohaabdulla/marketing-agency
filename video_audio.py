"""Separate local dialogue repair stages and optional enhancement-provider contracts."""
from abc import ABC,abstractmethod


class SpeechEnhancementProvider(ABC):
    @abstractmethod
    def enhance(self,source,output,job=None): ...


def dialogue_filters(project):
    chain=[]
    if project.dialogue_polish:
        chain+=['highpass=f=80','equalizer=f=250:t=q:w=1:g=-1.5','acompressor=threshold=-21dB:ratio=2.5:attack=8:release=120:makeup=1.5']
    if project.dialogue_noise_reduction:
        chain+=['afftdn=nr=6:nf=-40:tn=1']
    if project.dialogue_hum_hz:
        chain += [f'equalizer=f={project.dialogue_hum_hz}:t=q:w=8:g=-12',f'equalizer=f={project.dialogue_hum_hz*2}:t=q:w=8:g=-8']
    if project.dialogue_deess:
        chain+=['deesser=i=0.15:m=0.25:f=0.5']
    return chain


def plan(project):
    return dict(speech_cleanup='GENTLE_DSP' if project.dialogue_polish else 'OFF',
                noise_reduction='CONSERVATIVE_FFT' if project.dialogue_noise_reduction else 'OFF',
                hum_notches_hz=[project.dialogue_hum_hz,project.dialogue_hum_hz*2] if project.dialogue_hum_hz else [],
                eq=bool(project.dialogue_polish),compression=bool(project.dialogue_polish),deessing=project.dialogue_deess,
                dereverb='NOT_AVAILABLE',neural_enhancement='NOT_AVAILABLE',music='APPROVED_UPLOADED_ONLY',
                ducking='DIALOGUE_SIDECHAIN',sfx='SEPARATE_UPLOADED_BUS',mastering='MEASURED_BS1770',
                notice='DSP and loudness checks do not certify intelligibility or voice quality; listen before approving.')
