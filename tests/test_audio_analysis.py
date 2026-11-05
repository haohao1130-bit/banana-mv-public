"""Real WAV/ffmpeg measurements plus the actual 9B prompt-input boundary."""
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from banana_mv.audio_analysis import (RATE, analyze_audio, audio_guidance,
                                      load_analysis, segment_evidence)


def wav(path, samples):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
        stream.writeframes((np.clip(samples, -1, 1)*32767).astype('<i2').tobytes())


class AudioAnalysisTests(unittest.TestCase):
    def test_analysis_failure_is_visible_and_releases_worker_lock(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); job_id='abcdef123456'; (root/job_id).mkdir()
            lock=threading.Lock(); lock.acquire()
            job={'id':job_id,'status':'running','request':{'audio_analysis':True},
                 'size':[32,32],'segments':[{'index':0,'status':'waiting'}]}
            with patch.object(server,'RUNS',root),patch.object(server,'GPU_LOCK',lock), \
                 patch.object(server,'load_analysis',side_effect=RuntimeError('歌曲分析無法解碼')), \
                 patch.object(server.backend,'queue_prompt') as queue:
                server.worker(job,{'comfy_input_dir':str(root)},[],root/'song',root/'song')
                saved=json.loads((root/job_id/'status.json').read_text())
                self.assertEqual(saved['status'],'error')
                self.assertIn('歌曲分析無法解碼',saved['error'])
                self.assertFalse(lock.locked())
                queue.assert_not_called()

    def test_real_pulses_silence_local_time_and_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'song.wav'
            samples = np.zeros(RATE*12)
            for t in np.arange(1, 11, .5):
                offset = int(t*RATE)
                n = np.arange(int(.09*RATE))
                samples[offset:offset+len(n)] = .7*np.sin(2*np.pi*1000*n/RATE)*np.exp(-n/(RATE*.018))
            wav(source, samples)
            before = source.read_bytes()
            analysis = analyze_audio(source)
            self.assertEqual(source.read_bytes(), before)
            self.assertAlmostEqual(analysis['seconds'], 12)
            self.assertIsNotNone(analysis['pulse'])
            self.assertAlmostEqual(analysis['pulse']['bpm_estimate'], 120, delta=2)
            self.assertTrue(any(a == 0 and b >= .9 for a,b in analysis['quiet_intervals']))
            evidence = segment_evidence(analysis, {'start':5, 'seconds':4})
            self.assertEqual(evidence['source_interval'], [5,9])
            self.assertTrue(evidence['transient_candidates_s'])
            self.assertTrue(all(0 <= t < 4 for t in evidence['transient_candidates_s']))
            # Final generation padding is not treated as real song silence.
            tail = segment_evidence(analysis, {'start':11, 'seconds':4})
            self.assertEqual(tail['source_interval'], [11,12])
            self.assertTrue(all(b <= 1 for a,b in tail['quiet_intervals_s']))
            self.assertIn('do not cut on every accent', audio_guidance(evidence))

    def test_silence_and_steady_tone_do_not_invent_beats(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'song.wav'
            for samples in (np.zeros(RATE*3), .2*np.sin(2*np.pi*440*np.arange(RATE*3)/RATE)):
                wav(source, samples)
                result = analyze_audio(source)
                self.assertIsNone(result['pulse'])
                self.assertLess(len(result['onsets']), 3)
                json.dumps(result, allow_nan=False)

    def test_energy_rise_vocal_stem_and_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,cache = Path(tmp)/'song.wav',Path(tmp)/'audio_analysis.json'
            t = np.arange(RATE*6)/RATE
            wav(source, (.01 + .5*(t/6)**2)*np.sin(2*np.pi*440*t))
            analysis = load_analysis(source, cache)
            with patch('banana_mv.audio_analysis.analyze_audio', side_effect=AssertionError('cache missed')):
                self.assertEqual(load_analysis(source, cache), analysis)
            ev = segment_evidence(analysis, {'start':0,'seconds':6})
            self.assertGreater(ev['energy_change_db'], 3)
            self.assertIn('Build visible movement', audio_guidance(ev))
            wav(source, np.zeros(RATE*6))
            quiet = load_analysis(source, cache)
            self.assertNotEqual(analysis['source_sha256'], quiet['source_sha256'])
            ev = segment_evidence(analysis, {'start':1,'seconds':4}, quiet)
            self.assertEqual(ev['provided_vocal_stem_quiet_intervals_s'], [[0,4]])
            cache.write_text('{broken')
            self.assertEqual(load_analysis(source, cache)['source_sha256'], quiet['source_sha256'])

    def test_evidence_reaches_9b_and_both_final_prompt_paths(self):
        from PIL import Image
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); photo=root/'image.png'; Image.new('RGB',(32,32)).save(photo)
            guide=root/'guide.md';guide.write_text('Write an H3 prompt.')
            cfg={'guides':{'ref':str(guide)}}
            evidence={'relative_energy':'high','energy_change_db':4,
                      'transient_candidates_s':[1.5,3.2], 'quiet_intervals_s':[[4,4.5]]}
            segment={'seconds':5,'model_frames':124,'audio_evidence':evidence}
            req={'prompt':'Keep the singer and industrial stage.','director':'performance',
                 'face_identity':False, 'rewrite':True}
            with patch.object(server.backend,'rewrite_local',return_value='subject_definitions: singer <Picture 1>. <Audio 1>: fully_copy') as rewrite:
                final=server.local_prompt(cfg,req,segment,[photo],None)
                text=''.join(value for kind,value in rewrite.call_args.args[2] if kind=='text')
                self.assertIn('MEASURED AUDIO EVIDENCE',text)
                self.assertIn('1.5',text)
                self.assertIn('AUDIO-RESPONSIVE DIRECTION',final)
                self.assertEqual(req['prompt'],'Keep the singer and industrial stage.')
                req['rewrite']=False
                fallback=server.local_prompt(cfg,req,segment,[photo],None)
                self.assertIn('AUDIO-RESPONSIVE DIRECTION',fallback)
                self.assertEqual(rewrite.call_count,1)
                # Legacy saved projects without evidence stay on the old path.
                segment.pop('audio_evidence')
                self.assertNotIn('AUDIO-RESPONSIVE',server.local_prompt(cfg,req,segment,[photo],None))
