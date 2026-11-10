import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from banana_mv.sound_effects import validate_effects,effect_mix
from banana_mv.core import command,assemble
from banana_mv.sound_effects import samples


def wav(path,x):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes((x*32767).astype('<i2').tobytes())


class EffectsTests(unittest.TestCase):
    def test_sparse_track_stays_quiet_and_source_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song.wav';fx=root/'fx.wav'
            t=np.arange(160000)/16000;music=.3*np.sin(2*np.pi*220*t)
            effects=np.zeros_like(t);effects[16000:24000]=.8*np.sin(2*np.pi*880*t[16000:24000])
            wav(song,music);wav(fx,effects);before=(song.read_bytes(),fx.read_bytes())
            info=validate_effects(fx,song,10)
            self.assertLess(info['coverage'],.06);self.assertLessEqual(info['gain'],.18)
            self.assertFalse(info['auto_generated'])
            output=root/'mixed.wav'
            command(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-i',song,'-i',fx,
                     '-filter_complex',effect_mix(info['gain']),'-map','[mixed]','-t','10','-c:a','pcm_s16le',output])
            with wave.open(str(output)) as w:mixed=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')/32768
            self.assertEqual(len(mixed),len(music))
            self.assertLess(np.max(np.abs(mixed[:15000]-music[:15000])),.001)
            self.assertLess(np.max(np.abs(mixed[16000:24000]-music[16000:24000])),.06)
            part=root/'part.mp4'
            command(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=32x32:r=24:d=10',
                     '-c:v','libx264','-threads','1',part])
            final=root/'final.mp4'
            assemble([part],song,final,10,effects={'path':fx,'gain':info['gain']})
            decoded=samples(final)
            self.assertAlmostEqual(len(decoded)/16000,10,delta=.05)
            self.assertLess(np.sqrt(np.mean((decoded[:15000]-music[:15000])**2)),.015)
            self.assertEqual(before,(song.read_bytes(),fx.read_bytes()))

    def test_dense_long_or_misaligned_track_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song.wav';fx=root/'fx.wav';t=np.arange(160000)/16000
            wav(song,.2*np.sin(2*np.pi*220*t))
            for signal in (.2*np.sin(2*np.pi*440*t),np.r_[.2*np.sin(2*np.pi*440*t[:64000]),np.zeros(96000)],np.zeros(32000)):
                wav(fx,signal)
                with self.assertRaises(ValueError):validate_effects(fx,song,10)
