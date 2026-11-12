import hashlib
import io
import json
import ssl
import sys
import tempfile
import unittest
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from banana_mv.music_structure import validate_result,local_structure,load_structure,direction,REVISION,MODEL,VERSION
from banana_mv.audio_analysis import source_hash,audio_guidance


def prediction():
    return {'bpm':120,'beats':[.5,1,1.5,2,2.5,3,3.5],'downbeats':[.5,2.5],
            'segments':[{'start':0,'end':2,'label':'verse'},{'start':2,'end':4,'label':'chorus'}]}


class StructureTests(unittest.TestCase):
    def test_local_time_and_padding(self):
        cue=local_structure(validate_result(prediction(),4),{'start':1,'seconds':2})
        self.assertEqual(cue['downbeats_s'],[1.5])
        self.assertEqual(cue['sections'][0],{'start_s':0,'end_s':1,'predicted_label':'verse','begins_here':False})
        self.assertEqual(cue['sections'][1]['start_s'],1)
        self.assertTrue(cue['sections'][1]['begins_here'])
        tail=local_structure(validate_result(prediction(),4),{'start':3,'seconds':4})
        self.assertEqual(tail['sections'][0]['end_s'],1)
        self.assertIn('fallible',direction(cue))

    def test_invalid_predictions_rejected(self):
        for change in ({'bpm':float('nan')},{'beats':[2,1]},{'downbeats':[5]},
                       {'segments':[{'start':0,'end':4,'label':'guitar'}]},
                       {'segments':[{'start':0,'end':1,'label':'verse'}]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_result(dict(prediction(),**change),4)

    def test_cache_bound_to_source_and_missing_runtime_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song';song.write_bytes(b'original');cache=root/'cache.json'
            identity={'version':VERSION,'source_sha256':source_hash(song),'revision':REVISION,'model':MODEL}
            cache.write_text(json.dumps(dict(prediction(),**identity)))
            with patch.dict('os.environ',{'BANANA_MUSIC_PYTHON':str(root/'missing')}):
                self.assertEqual(load_structure(song,cache,4)['bpm'],120)
                song.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'尚未安裝'):
                    load_structure(song,cache,4)
            self.assertEqual(song.read_bytes(),b'changed')

    def test_final_prompt_retains_music_cues(self):
        cue=local_structure(validate_result(prediction(),4),{'start':0,'seconds':4})
        text=audio_guidance({'relative_energy':'high','energy_change_db':0,'transient_candidates_s':[],
                             'quiet_intervals_s':[],'music_structure':cue})
        for word in ('chorus','downbeats','do not cut on every beat'):
            self.assertIn(word,text)

    def test_demucs_fallback_is_only_for_expired_certificates(self):
        from banana_mv import music_structure as m
        expired = urllib.error.URLError(
            ssl.SSLCertVerificationError(1, 'certificate verify failed: certificate has expired'))
        self.assertTrue(m._expired_download_certificate(expired))
        self.assertFalse(m._expired_download_certificate(urllib.error.URLError('connection refused')))
        self.assertFalse(m._expired_download_certificate(
            urllib.error.URLError(ssl.SSLCertVerificationError(1, 'self-signed certificate'))))

    def test_demucs_mirror_restores_verified_checkpoint_without_redownload(self):
        from banana_mv import music_structure as m
        data = b'a known, safe test checkpoint'
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / m.DEMUCS_CHECKPOINT_NAME
            with patch.object(m, '_demucs_checkpoint_target', return_value=target), \\
                 patch.object(m, 'DEMUCS_CHECKPOINT_SHA256', hashlib.sha256(data).hexdigest()), \\
                 patch.object(m.urllib.request, 'urlopen', return_value=io.BytesIO(data)) as download:
                self.assertEqual(m._restore_demucs_checkpoint(), target)
                self.assertEqual(target.read_bytes(), data)
                self.assertEqual(m._restore_demucs_checkpoint(), target)
            download.assert_called_once_with(m.DEMUCS_MIRROR_URL, timeout=60)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_demucs_mirror_never_keeps_corrupt_download(self):
        from banana_mv import music_structure as m
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / m.DEMUCS_CHECKPOINT_NAME
            with patch.object(m, '_demucs_checkpoint_target', return_value=target), \\
                 patch.object(m, 'DEMUCS_CHECKPOINT_SHA256', '0' * 64), \\
                 patch.object(m.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')):
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    m._restore_demucs_checkpoint()
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_run_model_retries_only_after_expired_source_certificate(self):
        from banana_mv import music_structure as m
        @dataclass
        class Output:
            bpm: float
            beats: list
            downbeats: list
            segments: list
        failed = urllib.error.URLError(
            ssl.SSLCertVerificationError(1, 'certificate verify failed: certificate has expired'))
        result = Output(120, [0.5], [0.5], [{'start': 0, 'end': 1, 'label': 'verse'}])
        analyze = Mock(side_effect=[failed, result])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.json'
            modules = {'torch': SimpleNamespace(set_num_threads=Mock()),
                       'allin1_infer': SimpleNamespace(analyze=analyze)}
            with patch.dict(sys.modules, modules), \\
                 patch.object(m, '_restore_demucs_checkpoint') as restore:
                m.run_model('track.wav', output, tmp)
            self.assertEqual(json.loads(output.read_text())['bpm'], 120)
            self.assertEqual(analyze.call_count, 2)
            restore.assert_called_once()

            analyze = Mock(side_effect=urllib.error.URLError('connection refused'))
            modules['allin1_infer'] = SimpleNamespace(analyze=analyze)
            with patch.dict(sys.modules, modules), \\
                 patch.object(m, '_restore_demucs_checkpoint') as restore:
                with self.assertRaises(urllib.error.URLError):
                    m.run_model('track.wav', output, tmp)
            analyze.assert_called_once()
            restore.assert_not_called()

    def test_worker_routes_structure_before_planning(self):
        from banana_mv import server
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job_id='abcdef123456';(root/job_id).mkdir();lock=threading.Lock();lock.acquire()
            seg={'index':0,'start':1,'seconds':2,'status':'waiting'}
            job={'id':job_id,'status':'running','request':{'audio_analysis':True,'music_structure':True,
                 'director_version':2,'story_plan':True,'rewrite':True,'director_schema':5},'size':[32,32],'segments':[seg]}
            def stop(*args,**kwargs):
                self.assertEqual(seg['audio_evidence']['music_structure']['sections'][1]['start_s'],1)
                raise RuntimeError('STOP_AFTER_ROUTING')
            with patch.object(server,'RUNS',root),patch.object(server,'GPU_LOCK',lock), \
                 patch.object(server,'load_analysis',return_value={'seconds':4,'pulse':None}), \
                 patch.object(server,'load_structure',return_value=validate_result(prediction(),4)) as load, \
                 patch.object(server,'segment_evidence',return_value={}), \
                 patch.object(server,'ensure_plan',side_effect=stop), \
                 patch.object(server.backend,'queue_prompt') as queue:
                server.worker(job,{'comfy_input_dir':str(root)},[],root/'song',root/'song')
                load.assert_called_once();self.assertIn('STOP_AFTER_ROUTING',job['error'])
                self.assertEqual(job['audio_analysis']['structure']['status'],'ready')
                self.assertFalse(lock.locked());queue.assert_not_called()

    def test_actual_allocator_and_clip_writer_receive_music_evidence(self):
        from unittest.mock import Mock
        from banana_mv import server
        from banana_mv.story_plan import ensure_plan
        from test_shoot_plan import ShootPlanTests,allocation,native_prompt
        from test_unified_direction import timeline
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=ShootPlanTests().fixture(root)
            rows=timeline()
            for s in rows:
                s['audio_evidence']={'relative_energy':'medium','energy_change_db':0,
                    'transient_candidates_s':[],'quiet_intervals_s':[],
                    'music_structure':local_structure(validate_result(prediction(),4),s)}
            allocator=Mock(return_value=allocation())
            plan=ensure_plan(cfg,req,rows,images,root,allocator)
            upper=json.loads(allocator.call_args.args[2][0][1])
            self.assertEqual(upper['timeline'][0]['audio_evidence'],rows[0]['audio_evidence'])
            seg=dict(rows[1],director_plan=plan['segments'][1])
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer):
                output=server.local_prompt(cfg,req,seg,images,None)
            lower=writer.call_args.args[2][0][1]
            context=json.loads(lower.split('Clip timing and audio context:\n',1)[1])
            self.assertEqual(context['audio_evidence'],rows[1]['audio_evidence'])
            self.assertIn('Write their timing into the shots',lower)
