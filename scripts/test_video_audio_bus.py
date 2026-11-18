"""Real multi-bus rendering: dialogue ducks music while editorial SFX retain their level."""
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-audio-bus-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name
import numpy as np
from video.assets import ingest, path_for
from video.ffmpeg import ffmpeg
from video.editor import render
from video.projects import Project, Clip, Canvas
from video.jobs import Job
from video.measure import audio_quality


class AudioBusTests(unittest.TestCase):
    def test_music_ducking_with_voiceover_and_sfx(self):
        folder = Path(TEMP.name)
        source = folder / 'source.mp4'
        ffmpeg(['-f','lavfi','-i','color=c=0x223344:s=320x240:r=24:d=3',
                '-f','lavfi','-i',"sine=frequency=330:sample_rate=48000:duration=3,volume=3,aeval=val(0)*between(t\\,0.5\\,1.5)",
                '-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
        video = ingest(source, 'source.mp4')
        tracks = {}
        for role, frequency in [('music',880),('voiceover',440),('sfx',1320)]:
            wav = folder / (role+'.wav')
            ffmpeg(['-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=48000:duration=3','-c:a','pcm_s16le',str(wav)])
            tracks[role] = ingest(wav,wav.name)
        project = Project(canvas=Canvas(width=320,height=240),clips=[Clip(asset_id=video['id'],duration=3)] +
            [Clip(kind='audio',asset_id=a['id'],duration=3,audio_role=role,volume=1.5 if role=='music' else .2,
                  ducking_priority=1 if role=='music' else 0) for role,a in tracks.items()])
        result = render(project,Job('export'))
        decoded = folder/'decoded.wav'
        ffmpeg(['-i',str(path_for(result['id'])),'-vn','-ac','1','-ar','8000','-c:a','pcm_s16le',str(decoded)])
        with wave.open(str(decoded)) as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')/32768.
        def amplitude(frequency, time):
            signal=samples[int(time*8000):int((time+.25)*8000)]
            spectrum=np.abs(np.fft.rfft(signal*np.hanning(len(signal))))
            bins=np.fft.rfftfreq(len(signal),1/8000)
            return float(spectrum[np.abs(bins-frequency)<5].max())
        self.assertLess(amplitude(880,.9),amplitude(880,2.3)*.8)
        self.assertAlmostEqual(amplitude(1320,.9)/amplitude(1320,2.3),1.,delta=.18)
        self.assertGreater(amplitude(330,.9),amplitude(330,2.3)*5)

    def test_hum_is_a_measured_indicator_and_analysis_is_cached(self):
        wav=Path(TEMP.name)/'hum.wav'
        ffmpeg(['-f','lavfi','-i','sine=frequency=60:duration=2:sample_rate=48000','-c:a','pcm_s16le',str(wav)])
        result=audio_quality(wav)
        self.assertTrue(next(h for h in result['hum_candidates'] if h['frequency_hz']==60)['possible_hum'])
        self.assertEqual(audio_quality(wav),result)
        self.assertIn('not an isolated noise floor',result['limitations'])


if __name__=='__main__':
    unittest.main(verbosity=2)
